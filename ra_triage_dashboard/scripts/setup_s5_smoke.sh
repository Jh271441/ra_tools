#!/usr/bin/env bash
set -euo pipefail
umask 077

S5_SHA="${1:-}"
[[ "$S5_SHA" =~ ^[a-f0-9]{40}$ ]] || { echo "Usage: setup_s5_smoke.sh <full-s5-commit-sha>" >&2; exit 2; }

S5_ROOT="${S5_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922}"
S4_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
S3_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_smoke_20260921
S4_DB=manual_s4_smoke_20260921_campaign
S5_DB="${S5_DB_NAME:-manual_s5_smoke_20260922_runcollections}"
S4_RESTORE_DB="${S4_RESTORE_DB_NAME:-manual_s5_s4_restore_20260922}"
S4_RESTORE_SHA=bf745129e4e7359db3631c18ee60da3e20ab74f2
S4_RESTORE_ROOT="$S5_ROOT/s4-restore-source-bf74512"
APP_ROOT="$S5_ROOT/source-$S5_SHA/ra_triage_dashboard"
URL_FILE="$S5_ROOT/config/postgres_url"
S4_RESTORE_URL_FILE="$S5_ROOT/config/s4_restore_postgres_url"
DUMP_FILE="$S5_ROOT/data/s4-smoke-clone.dump"

[[ -f "$APP_ROOT/app/main.py" ]] || { echo "Archived S5 source tree is missing." >&2; exit 1; }
[[ -d "$S5_ROOT" && "$(stat -c '%a' "$S5_ROOT")" == 700 && "$(stat -c '%U' "$S5_ROOT")" == "$(id -un)" ]] || { echo "S5 experiment root must exist, be owned by this user, and have mode 0700." >&2; exit 1; }
[[ ! -e "$URL_FILE" && ! -e "$S4_RESTORE_URL_FILE" && ! -e "$DUMP_FILE" ]] || { echo "S5 configuration or dump already exists; refusing to overwrite it." >&2; exit 1; }
[[ -d "$S4_ROOT" && -d "$S3_ROOT/baselines" ]] || { echo "Validated S4/S3 smoke roots are unavailable." >&2; exit 1; }

PROD_LISTENER="$(ss -H -ltnp 'sport = :8785')"
[[ "$PROD_LISTENER" == *"0.0.0.0:8785"* && "$PROD_LISTENER" == *"pid=10634,"* ]] || { echo "Production listener identity changed; refusing S5 setup." >&2; exit 1; }
PROD_HEALTH="$(curl -fsS --max-time 5 http://127.0.0.1:8785/health)"
printf '%s' "$PROD_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")=="5fdc41ba8b0215170a8307237762e1ed50a9aaf2"' || { echo "Production health/build changed; refusing S5 setup." >&2; exit 1; }

install -d -m 700 "$S5_ROOT/config" "$S5_ROOT/data" "$S5_ROOT/logs" "$S5_ROOT/baselines" "$S5_ROOT/runtime"
if [[ -e "$S4_RESTORE_ROOT" ]]; then
  [[ "$(git -C "$S4_RESTORE_ROOT" rev-parse HEAD)" == "$S4_RESTORE_SHA" ]] || { echo "Existing S4 restore worktree is not the pinned S4 commit." >&2; exit 1; }
else
  git -C "$APP_ROOT" cat-file -e "$S4_RESTORE_SHA^{commit}"
  git -C "$APP_ROOT" worktree add --detach "$S4_RESTORE_ROOT" "$S4_RESTORE_SHA"
  chmod 700 "$S4_RESTORE_ROOT"
fi
printf '%s\n' "$S5_SHA" > "$S5_ROOT/config/source_sha"
chmod 600 "$S5_ROOT/config/source_sha"

cp "$S4_ROOT/config/baselines.json" "$S5_ROOT/config/baselines.json"
cp -a "$S3_ROOT/baselines/." "$S5_ROOT/baselines/"
python3 - "$S5_ROOT/config/baselines.json" "$S3_ROOT/baselines" "$S5_ROOT/baselines" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
old_root = str(Path(sys.argv[2]))
new_root = str(Path(sys.argv[3]))
payload = json.loads(manifest.read_text(encoding="utf-8"))

def replace_paths(value):
    if isinstance(value, dict):
        return {key: replace_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_paths(item) for item in value]
    if isinstance(value, str) and value.startswith(old_root + "/"):
        return new_root + value[len(old_root):]
    return value

manifest.write_text(json.dumps(replace_paths(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
chmod 600 "$S5_ROOT/config/baselines.json"

if sudo -n -u postgres psql --dbname=postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = '$S5_DB'" | grep -q '^1$'; then
  echo "S5 target database already exists; refusing to overwrite it." >&2
  exit 1
fi
pg_dump --no-owner --no-acl --format=custom --file="$DUMP_FILE" --dbname="$S4_DB"
chmod 600 "$DUMP_FILE"
sudo -n -u postgres createdb --owner="$(id -un)" --template=template0 "$S5_DB"
pg_restore --no-owner --no-acl --dbname="$S5_DB" "$DUMP_FILE"
printf 'postgresql:///%s\n' "$S5_DB" > "$URL_FILE"
chmod 600 "$URL_FILE"

if sudo -n -u postgres psql --dbname=postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = '$S4_RESTORE_DB'" | grep -q '^1$'; then
  echo "S5 S4-restore database already exists; refusing to overwrite it." >&2
  exit 1
fi
sudo -n -u postgres createdb --owner="$(id -un)" --template=template0 "$S4_RESTORE_DB"
pg_restore --no-owner --no-acl --dbname="$S4_RESTORE_DB" "$DUMP_FILE"
printf 'postgresql:///%s\n' "$S4_RESTORE_DB" > "$S4_RESTORE_URL_FILE"
chmod 600 "$S4_RESTORE_URL_FILE"

CLONE_COUNTS="$(psql --dbname="$S5_DB" -Atqc "SELECT (SELECT COUNT(*) FROM issues), (SELECT COUNT(*) FROM dashboard_schema_migrations)")"
[[ "$CLONE_COUNTS" == "413|46" ]] || { echo "S5 clone is not the validated S4 fixture (expected 413 Issues and 46 migrations)." >&2; exit 1; }
printf 'Created isolated S5 database from S4 fixture: %s (%s Issues, %s migrations before S5).\n' \
  "$S5_DB" "${CLONE_COUNTS%%|*}" "${CLONE_COUNTS##*|}"
S4_RESTORE_COUNTS="$(psql --dbname="$S4_RESTORE_DB" -Atqc "SELECT (SELECT COUNT(*) FROM issues), (SELECT COUNT(*) FROM dashboard_schema_migrations)")"
[[ "$S4_RESTORE_COUNTS" == "413|46" ]] || { echo "S5 restore database is not the validated S4 snapshot." >&2; exit 1; }
