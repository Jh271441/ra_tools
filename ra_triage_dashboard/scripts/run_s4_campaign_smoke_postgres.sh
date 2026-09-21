#!/usr/bin/env bash
set -euo pipefail
umask 077

KEEP_FIXTURE=false
if [[ "${1:-}" == "--keep-fixture" ]]; then
  KEEP_FIXTURE=true
  shift
fi
if [[ $# -gt 0 ]]; then
  echo "usage: $0 [--keep-fixture]" >&2
  exit 2
fi

ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
SOURCE_DB=manual_s4_smoke_20260921_campaign
TOKEN="$(date +%Y%m%d)_$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
FIXTURE_DB="manual_s4_smoke_campaign_fixture_$TOKEN"
DUMP="$ROOT/data/campaign-fixture-$TOKEN.dump"
FIXTURE_URL_FILE="$ROOT/config/campaign-fixture-$TOKEN.postgres_url"
RECEIPT="$ROOT/data/campaign-smoke-receipt-$TOKEN.json"
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE_CREATED=false

cleanup() {
  if [[ "$FIXTURE_CREATED" == true ]]; then
    if [[ "$KEEP_FIXTURE" == true ]]; then
      echo "SMOKE_FIXTURE_RETAINED database=$FIXTURE_DB url_file=$FIXTURE_URL_FILE dump=$DUMP"
      return
    fi
    dropdb --if-exists "$FIXTURE_DB" >/dev/null 2>&1 || true
  fi
  rm -f "$DUMP" "$FIXTURE_URL_FILE"
}
trap cleanup EXIT

if [[ "$(stat -c '%a' "$ROOT")" != 700 || "$(stat -c '%U' "$ROOT")" != "$(id -un)" ]]; then
  echo "S4 experiment root must be owned and private (0700)." >&2
  exit 1
fi
if [[ "$(stat -c '%a' "$ROOT/config/postgres_url")" != 600 ]]; then
  echo "S4 source PostgreSQL URL must be private (0600)." >&2
  exit 1
fi
if [[ "$(psql --dbname="$SOURCE_DB" --tuples-only --no-align --command="SELECT current_database()" | tr -d '[:space:]')" != "$SOURCE_DB" ]]; then
  echo "Source DB identity mismatch; refusing smoke clone." >&2
  exit 1
fi

pg_dump --no-owner --no-acl --format=custom --file="$DUMP" --dbname="$SOURCE_DB"
chmod 600 "$DUMP"
createdb --owner="$(id -un)" --template=template0 "$FIXTURE_DB"
FIXTURE_CREATED=true
pg_restore --no-owner --no-acl --dbname="$FIXTURE_DB" "$DUMP"
printf 'postgresql:///%s\n' "$FIXTURE_DB" > "$FIXTURE_URL_FILE"
chmod 600 "$FIXTURE_URL_FILE"

/volume/home/workspace/ra_triage_dashboard_venv/bin/python3 \
  "$APP_ROOT/scripts/smoke_s4_campaigns_postgres.py" \
  --database-url-file "$FIXTURE_URL_FILE" \
  --baselines-file "$ROOT/config/baselines.json" \
  --data-dir "$ROOT/data" \
  --receipt "$RECEIPT"

echo "SMOKE_FIXTURE_COMPLETED $FIXTURE_DB"
