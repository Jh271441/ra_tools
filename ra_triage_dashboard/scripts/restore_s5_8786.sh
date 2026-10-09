#!/usr/bin/env bash
set -euo pipefail
umask 077
PORT=8786
S6_ROOT="${S6_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s6_legacy_cutover_20260922}"
S5_ROOT="${S5_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922}"
S5_DB="${S5_DB_NAME:-manual_s5_smoke_v3_20260922}"
S5_URL="$S6_ROOT/config/s5_restore_postgres_url"
S5_SHA="${S5_SOURCE_SHA:-b5466899a2d405c4d82ebd0f913cd7201a1dc102}"
VENV=/volume/home/workspace/ra_triage_dashboard_venv
fail(){ echo "$1" >&2; exit 1; }
listener(){ ss -H -ltnp "sport = :$1"; }
[[ -d "$S5_ROOT/source-$S5_SHA/ra_triage_dashboard" ]] || fail "S5 v3 source unavailable"
printf 'postgresql:///%s\n' "$S5_DB" > "$S5_URL"; chmod 600 "$S5_URL"
CURRENT=$(listener "$PORT"); [[ "$CURRENT" == *"127.0.0.1:$PORT"* ]] || fail "8786 is not loopback"
PID=$(printf '%s\n' "$CURRENT" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p'); kill -TERM "$PID"
for _ in $(seq 1 30); do [[ -z "$(listener "$PORT")" ]] && break; sleep 1; done
[[ -z "$(listener "$PORT")" ]] || fail "8786 did not stop"
DATA="$S6_ROOT/data/s5_restore"; LOG="$S6_ROOT/logs/restore_s5_8786.log"
install -d -m 700 "$DATA/media_layouts/s5_restore" "$DATA/intent_media/bev" "$DATA/intent_media/camera41" "$DATA/issue_tag_sources" "$DATA/batch_bags" "$(dirname "$LOG")"
env DASHBOARD_VENV_DIR="$VENV" DASHBOARD_DATABASE_URL_FILE="$S5_URL" DASHBOARD_DATA_DIR="$DATA" DASHBOARD_POSTGRES_PERSISTENT_DATA=false DASHBOARD_BUILD_COMMIT="$S5_SHA" DASHBOARD_HOST=127.0.0.1 DASHBOARD_PORT="$PORT" DASHBOARD_BASE_PATH=/manual-s5 DASHBOARD_BASELINES_FILE="$S5_ROOT/config/baselines.json" DASHBOARD_BASELINE_DATASET=0508 DASHBOARD_BASELINE_SCOPE=release0508_1071_20260729 DASHBOARD_SYNC_TRAIL_ON_START=false DASHBOARD_GT_SYNC_ENABLED=false DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED=false DASHBOARD_BATCH_PREDICTION_ENABLED=false DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED=false DASHBOARD_DCHAT_CREDENTIALS_FILE=/dev/null DASHBOARD_RA_MODEL_API_KEY_FILE=/dev/null DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE=/dev/null DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE= RA_AUTO_TRIAGE_ROOT=/volume/home/workspace/ra_auto_triage "$VENV/bin/python3" -m uvicorn app.main:app --app-dir "$S5_ROOT/source-$S5_SHA/ra_triage_dashboard" --host 127.0.0.1 --port "$PORT" >> "$LOG" 2>&1 </dev/null &
echo "S5 v3 restore started on 8786"
