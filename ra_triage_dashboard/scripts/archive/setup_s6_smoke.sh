#!/usr/bin/env bash
set -euo pipefail
umask 077

S6_SHA="${1:-}"
[[ "$S6_SHA" =~ ^[a-f0-9]{40}$ ]] || { echo "Usage: setup_s6_smoke.sh <full-s6-commit-sha>" >&2; exit 2; }
S6_ROOT="${S6_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s6_legacy_cutover_20260922}"
S5_ROOT="${S5_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922}"
S5_DB="${S5_DB_NAME:-manual_s5_smoke_v3_20260922}"
S6_DB="${S6_DB_NAME:-manual_s6_smoke_legacycutover_20260922}"
S6_URL_FILE="$S6_ROOT/config/postgres_url"
S6_S4_URL_FILE="$S6_ROOT/config/s4_restore_postgres_url"
S6_DUMP="$S6_ROOT/data/s5-v3-clone.dump"
S6_SOURCE="$S6_ROOT/source-$S6_SHA"

[[ -d "$S6_SOURCE/ra_triage_dashboard" ]] || { echo "S6 source worktree is missing." >&2; exit 1; }
[[ -d "$S5_ROOT" && "$(stat -c '%a' "$S5_ROOT")" == 700 ]] || { echo "S5 root unavailable." >&2; exit 1; }
[[ ! -e "$S6_URL_FILE" && ! -e "$S6_S4_URL_FILE" && ! -e "$S6_DUMP" ]] || { echo "S6 root already initialized; refusing overwrite." >&2; exit 1; }
[[ -f "$S5_ROOT/config/postgres_url" ]] || { echo "S5 v3 URL file unavailable." >&2; exit 1; }
install -d -m 700 "$S6_ROOT/config" "$S6_ROOT/data" "$S6_ROOT/logs" "$S6_ROOT/baselines" "$S6_ROOT/runtime"
printf '%s\n' "$S6_SHA" > "$S6_ROOT/config/source_sha"
chmod 600 "$S6_ROOT/config/source_sha"
cp "$S5_ROOT/config/baselines.json" "$S6_ROOT/config/baselines.json"
cp -a "$S5_ROOT/baselines/." "$S6_ROOT/baselines/"
chmod 600 "$S6_ROOT/config/baselines.json"

if sudo -n -u postgres psql --dbname=postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = '$S6_DB'" | grep -q '^1$'; then
  echo "S6 database already exists; refusing overwrite." >&2
  exit 1
fi
pg_dump --no-owner --no-acl --format=custom --file="$S6_DUMP" --dbname="$S5_DB"
chmod 600 "$S6_DUMP"
sudo -n -u postgres createdb --owner="$(id -un)" --template=template0 "$S6_DB"
pg_restore --no-owner --no-acl --dbname="$S6_DB" "$S6_DUMP"
printf 'postgresql:///%s\n' "$S6_DB" > "$S6_URL_FILE"
chmod 600 "$S6_URL_FILE"
printf 'postgresql:///%s\n' "${S6_S4_DB_NAME:-manual_s5_s4_restore_20260922}" > "$S6_S4_URL_FILE"
chmod 600 "$S6_S4_URL_FILE"
psql --dbname="$S6_DB" -Atqc "SELECT (SELECT COUNT(*) FROM issues), (SELECT COUNT(*) FROM dashboard_schema_migrations)"
