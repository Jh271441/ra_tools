#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=8786
PROD_PORT=8785
PROD_EXPECTED_PID=10634
PROD_EXPECTED_BUILD=5fdc41ba8b0215170a8307237762e1ed50a9aaf2
S4_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
S4_FROZEN_SHA=bf745129e4e7359db3631c18ee60da3e20ab74f2
S4_BUILD=b75aa55
S5_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922
S4_RESTORE_DB=manual_s5_s4_restore_20260922
S5_SHA_FILE="$S5_ROOT/config/source_sha"
S5_PID_FILE="$S5_ROOT/runtime/s5.pid"
S4_SOURCE_ROOT="$S5_ROOT/s4-restore-source-bf74512"
S4_APP_ROOT="$S4_SOURCE_ROOT/ra_triage_dashboard"
S4_VENV=/volume/home/workspace/ra_triage_dashboard_venv
S4_DB_URL_FILE="$S5_ROOT/config/s4_restore_postgres_url"
S4_DATA_DIR="$S5_ROOT/data/s4_restore"
S4_LOG_FILE="$S5_ROOT/logs/restore_s4_8786.log"
LAYOUT_ID=release0508_1071_20260729

fail() { printf '%s\n' "$1" >&2; exit 1; }
listener() { ss -H -ltnp "sport = :$1"; }
listener_pid() { sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p'; }

[[ -d "$S5_ROOT" && "$(stat -c '%a' "$S5_ROOT")" == 700 ]] || fail "S5 private root is missing or not mode 0700."
[[ -f "$S5_SHA_FILE" && "$(stat -c '%a' "$S5_SHA_FILE")" == 600 ]] || fail "S5 source SHA file is missing or not mode 0600."
[[ -f "$S5_PID_FILE" && "$(stat -c '%a' "$S5_PID_FILE")" == 600 ]] || fail "S5 PID receipt is missing or not mode 0600."
S5_APP_SHA="$(cat "$S5_SHA_FILE")"
S5_PID="$(cat "$S5_PID_FILE")"
[[ "$S5_APP_SHA" =~ ^[a-f0-9]{40}$ && "$S5_PID" =~ ^[0-9]+$ ]] || fail "S5 source or PID receipt is invalid."
S5_APP_ROOT="$S5_ROOT/source-$S5_APP_SHA/ra_triage_dashboard"
[[ -d "$S4_ROOT" && "$(stat -c '%a' "$S4_ROOT")" == 700 ]] || fail "S4 smoke root is missing or not mode 0700."
[[ -f "$S4_DB_URL_FILE" && "$(stat -c '%a' "$S4_DB_URL_FILE")" == 600 ]] || fail "S5-owned S4-restore DB URL file is missing or not mode 0600."
S4_RESTORE_COUNTS="$(psql --dbname="$S4_RESTORE_DB" -Atqc "SELECT (SELECT COUNT(*) FROM issues), (SELECT COUNT(*) FROM dashboard_schema_migrations)")"
[[ "$S4_RESTORE_COUNTS" == "413|46" ]] || fail "S5-owned S4-restore database is not the pinned pre-S5 snapshot."
[[ -f "$S4_APP_ROOT/app/main.py" && "$(git -C "$S4_SOURCE_ROOT" rev-parse HEAD)" == "$S4_FROZEN_SHA" ]] || fail "Frozen S4 bf74512 source worktree is unavailable."
[[ -x "$S4_VENV/bin/python3" ]] || fail "Dashboard Python environment is missing."

PROD_LISTENER="$(listener "$PROD_PORT")"
[[ "$PROD_LISTENER" == *"0.0.0.0:$PROD_PORT"* && "$PROD_LISTENER" == *"pid=$PROD_EXPECTED_PID,"* ]] || fail "Production listener identity changed; refusing restore."
PROD_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PROD_PORT/health")"
printf '%s' "$PROD_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1]' "$PROD_EXPECTED_BUILD" || fail "Production health/build changed; refusing restore."

S5_LISTENER="$(listener "$PORT")"
[[ "$(printf '%s\n' "$S5_LISTENER" | sed '/^$/d' | wc -l | tr -d ' ')" == 1 ]] || fail "8786 must have exactly one S5 listener."
[[ "$S5_LISTENER" == *"127.0.0.1:$PORT"* && "$S5_LISTENER" == *"pid=$S5_PID,"* ]] || fail "8786 listener does not match the S5 PID receipt."
[[ -r "/proc/$S5_PID/cmdline" && -r "/proc/$S5_PID/environ" ]] || fail "S5 listener process is missing."
S5_ARGS="$(tr '\0' ' ' < "/proc/$S5_PID/cmdline")"
[[ "$S5_ARGS" == *"--app-dir $S5_APP_ROOT"* && "$S5_ARGS" == *"--host 127.0.0.1"* && "$S5_ARGS" == *"--port $PORT"* ]] || fail "8786 process is not the pinned S5 launcher."
S5_ENV="$(tr '\0' '\n' < "/proc/$S5_PID/environ")"
[[ "$S5_ENV" == *"DASHBOARD_BUILD_COMMIT=$S5_APP_SHA"* && "$S5_ENV" == *"DASHBOARD_BASE_PATH=/manual-s5"* ]] || fail "S5 process build/base-path identity mismatch."
S5_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s5/health")"
printf '%s' "$S5_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s5"' "$S5_APP_SHA" || fail "S5 health check failed; refusing restore."

kill -TERM "$S5_PID"
for _ in $(seq 1 30); do
  if [[ -z "$(listener "$PORT")" ]]; then break; fi
  sleep 1
done
[[ -z "$(listener "$PORT")" ]] || fail "Verified S5 process did not release 8786."

install -d -m 700 \
  "$(dirname "$S4_LOG_FILE")" \
  "$S4_DATA_DIR/media_layouts/$LAYOUT_ID" \
  "$S4_DATA_DIR/intent_media/bev" \
  "$S4_DATA_DIR/intent_media/camera41" \
  "$S4_DATA_DIR/issue_tag_sources" \
  "$S4_DATA_DIR/batch_bags"
nohup env \
  DASHBOARD_VENV_DIR="$S4_VENV" \
  DASHBOARD_DATABASE_URL_FILE="$S4_DB_URL_FILE" \
  DASHBOARD_DATA_DIR="$S4_DATA_DIR" \
  DASHBOARD_POSTGRES_PERSISTENT_DATA=false \
  DASHBOARD_BUILD_COMMIT="$S4_BUILD" \
  DASHBOARD_HOST=127.0.0.1 \
  DASHBOARD_PORT="$PORT" \
  DASHBOARD_BASE_PATH=/manual-s4 \
  DASHBOARD_BASELINES_FILE="$S4_ROOT/config/baselines.json" \
  DASHBOARD_BASELINE_LABEL_XLSX="$S4_ROOT/baselines/trail_0508_0206_subset.xlsx" \
  DASHBOARD_BASELINE_DATASET=0508 \
  DASHBOARD_BASELINE_SCOPE=release0508_1071_20260729 \
  DASHBOARD_BASELINE_OVERLAP_MODE=fail_skip \
  DASHBOARD_MEDIA_LAYOUT_ROOT="$S4_DATA_DIR/media_layouts" \
  DASHBOARD_MEDIA_LAYOUT="$LAYOUT_ID" \
  ARES_CAPTURE_RA_ROOT="$S4_DATA_DIR/media_layouts/$LAYOUT_ID" \
  ARES_CAPTURE_MANIFEST="$S4_DATA_DIR/media_layouts/$LAYOUT_ID/manifest.jsonl" \
  CAMERA_CACHE_ROOT="$S4_DATA_DIR/media_layouts/$LAYOUT_ID/camera/102" \
  ARES_CAPTURE_VIDEO_ROOT="$S4_DATA_DIR/media_layouts/$LAYOUT_ID/video" \
  DASHBOARD_INTENT_BEV_ROOT="$S4_DATA_DIR/intent_media/bev" \
  DASHBOARD_INTENT_CAMERA_ROOT="$S4_DATA_DIR/intent_media/camera41" \
  DASHBOARD_INTENT_CAMERA_MANIFEST="$S4_DATA_DIR/intent_media/camera41/source_manifest.jsonl" \
  DASHBOARD_ISSUE_TAG_SOURCE_0206_XLSX="$S4_DATA_DIR/issue_tag_sources/0206.xlsx" \
  DASHBOARD_ISSUE_TAG_SOURCE_0626_XLSX="$S4_DATA_DIR/issue_tag_sources/0626.xlsx" \
  DASHBOARD_SEED_EXAMPLES_ENABLED=false \
  DASHBOARD_DEPLOYMENT_MODE=production \
  DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=false \
  DASHBOARD_IDENTITY_DIAGNOSTICS=false \
  DASHBOARD_KYLIN_SSO_ENABLED=true \
  DASHBOARD_SSO_WRITE_USERS= \
  DASHBOARD_TEAM_DEFAULT_MANAGERS= \
  DASHBOARD_SYNC_TRAIL_ON_START=false \
  DASHBOARD_GT_SYNC_ENABLED=false \
  DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED=false \
  DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false \
  DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED=false \
  DASHBOARD_BATCH_PREDICTION_ENABLED=false \
  DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false \
  DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED=false \
  DASHBOARD_DCHAT_CREDENTIALS_FILE=/dev/null \
  DASHBOARD_RA_MODEL_API_KEY_FILE=/dev/null \
  DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE=/dev/null \
  DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE= \
  DASHBOARD_BOOTSTRAP_MODEL_JSON= \
  DASHBOARD_BATCH_BAG_CACHE_DIR="$S4_DATA_DIR/batch_bags" \
  RA_AUTO_TRIAGE_ROOT=/volume/home/workspace/ra_auto_triage \
  "$S4_VENV/bin/python3" -m uvicorn app.main:app \
    --app-dir "$S4_APP_ROOT" --host 127.0.0.1 --port "$PORT" \
  >> "$S4_LOG_FILE" 2>&1 </dev/null &
S4_PID=$!

S4_HEALTH=
for _ in $(seq 1 60); do
  if S4_HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/manual-s4/health" 2>/dev/null)"; then break; fi
  sleep 1
done
[[ -n "$S4_HEALTH" ]] || fail "Frozen S4 bf74512 source did not become healthy."
printf '%s' "$S4_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s4"' "$S4_BUILD" || fail "Frozen S4 build/base-path health mismatch."
S4_STATUS="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/status")"
printf '%s' "$S4_STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert int(d.get("database",{}).get("migration_count",0))==46; assert not d.get("batch_prediction_enabled"); assert not d.get("autotriage_push_enabled"); assert not (d.get("review_notifications",{}).get("enabled"))' || fail "Frozen S4 external writer or database state mismatch."
S4_SESSION="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/session")"
printf '%s' "$S4_SESSION" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only") is True and d.get("can_write") is False' || fail "Frozen S4 unauthenticated session is not read-only."
rm -f "$S5_PID_FILE"
printf 'Frozen S4 bf74512 restored on loopback 8786 (PID %s).\n' "$S4_PID"
