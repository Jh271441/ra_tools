#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
FIXTURE_DB="${1:-}"
PATTERN='^manual_s4_smoke_campaign_fixture_[0-9]{8}_[a-f0-9]{8}$'
SOURCE_DB=manual_s4_smoke_20260921_campaign

if [[ ! "$FIXTURE_DB" =~ $PATTERN || "$FIXTURE_DB" == "$SOURCE_DB" ]]; then
  echo "Refusing to drop a non-fixture S4 database." >&2
  exit 2
fi
if [[ "$(stat -c '%a' "$ROOT")" != 700 || "$(stat -c '%U' "$ROOT")" != "$(id -un)" ]]; then
  echo "S4 experiment root must be owned and private (0700)." >&2
  exit 1
fi
TOKEN="${FIXTURE_DB#manual_s4_smoke_campaign_fixture_}"
URL_FILE="$ROOT/config/campaign-fixture-$TOKEN.postgres_url"
DUMP="$ROOT/data/campaign-fixture-$TOKEN.dump"
if [[ ! -f "$URL_FILE" || "$(stat -c '%a' "$URL_FILE")" != 600 || "$(stat -c '%U' "$URL_FILE")" != "$(id -un)" ]]; then
  echo "Fixture URL file is missing or not private; refusing cleanup." >&2
  exit 1
fi
if [[ "$(psql --dbname="$FIXTURE_DB" --tuples-only --no-align --command="SELECT current_database()" | tr -d '[:space:]')" != "$FIXTURE_DB" ]]; then
  echo "Fixture database identity mismatch; refusing cleanup." >&2
  exit 1
fi

dropdb "$FIXTURE_DB"
rm -f "$URL_FILE" "$DUMP"
echo "SMOKE_FIXTURE_CLEANED $FIXTURE_DB"
