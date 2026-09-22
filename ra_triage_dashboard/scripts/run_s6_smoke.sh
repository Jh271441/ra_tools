#!/usr/bin/env bash
set -euo pipefail
umask 077

S6_ROOT="${S6_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s6_legacy_cutover_20260922}"
SHA_FILE="$S6_ROOT/config/source_sha"
DB_URL_FILE="$S6_ROOT/config/postgres_url"
DATA_DIR="$S6_ROOT/data"
LOG_FILE="$S6_ROOT/logs/server.log"
VENV_DIR=/volume/home/workspace/ra_triage_dashboard_venv
PORT="${S6_SMOKE_PORT:-8786}"
[[ "$PORT" == 8786 || "$PORT" == 8787 ]] || { echo "S6 smoke only permits loopback 8786/8787." >&2; exit 1; }
[[ -f "$SHA_FILE" && "$(stat -c '%a' "$SHA_FILE")" == 600 ]] || exit 1
SHA="$(cat "$SHA_FILE")"
APP_ROOT="$S6_ROOT/source-$SHA/ra_triage_dashboard"
[[ -f "$APP_ROOT/app/main.py" && -f "$DB_URL_FILE" ]] || exit 1
[[ "$(stat -c '%a' "$DB_URL_FILE")" == 600 ]] || exit 1
[[ -z "$(ss -H -ltn "sport = :$PORT")" ]] || { echo "S6 port occupied." >&2; exit 1; }
install -d -m 700 "$DATA_DIR/media_layouts/s6_legacy_cutover" "$DATA_DIR/intent_media/bev" "$DATA_DIR/intent_media/camera41" "$DATA_DIR/issue_tag_sources" "$DATA_DIR/batch_bags" "$(dirname "$LOG_FILE")"
unset DASHBOARD_DATABASE_URL
export DASHBOARD_VENV_DIR="$VENV_DIR" DASHBOARD_DATABASE_URL_FILE="$DB_URL_FILE" DASHBOARD_DATA_DIR="$DATA_DIR"
export DASHBOARD_POSTGRES_PERSISTENT_DATA=false DASHBOARD_BUILD_COMMIT="$SHA" DASHBOARD_HOST=127.0.0.1 DASHBOARD_PORT="$PORT" DASHBOARD_BASE_PATH=/manual-s6
export DASHBOARD_BASELINES_FILE="$S6_ROOT/config/baselines.json" DASHBOARD_BASELINE_DATASET=0508 DASHBOARD_BASELINE_SCOPE=release0508_1071_20260729 DASHBOARD_BASELINE_OVERLAP_MODE=fail_skip
export DASHBOARD_BASELINE_LABEL_XLSX="$S6_ROOT/baselines/trail_0508_0206_subset.xlsx" DASHBOARD_MEDIA_LAYOUT_ROOT="$DATA_DIR/media_layouts" DASHBOARD_MEDIA_LAYOUT=s6_legacy_cutover
export ARES_CAPTURE_RA_ROOT="$DATA_DIR/media_layouts/s6_legacy_cutover" ARES_CAPTURE_MANIFEST="$DATA_DIR/media_layouts/s6_legacy_cutover/manifest.jsonl" CAMERA_CACHE_ROOT="$DATA_DIR/media_layouts/s6_legacy_cutover/camera/102" ARES_CAPTURE_VIDEO_ROOT="$DATA_DIR/media_layouts/s6_legacy_cutover/video"
export DASHBOARD_INTENT_BEV_ROOT="$DATA_DIR/intent_media/bev" DASHBOARD_INTENT_CAMERA_ROOT="$DATA_DIR/intent_media/camera41" DASHBOARD_INTENT_CAMERA_MANIFEST="$DATA_DIR/intent_media/camera41/source_manifest.jsonl" DASHBOARD_ISSUE_TAG_SOURCE_0206_XLSX="$DATA_DIR/issue_tag_sources/0206.xlsx" DASHBOARD_ISSUE_TAG_SOURCE_0626_XLSX="$DATA_DIR/issue_tag_sources/0626.xlsx"
export DASHBOARD_SEED_EXAMPLES_ENABLED=false DASHBOARD_DEPLOYMENT_MODE=production DASHBOARD_KYLIN_SSO_ENABLED=true DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=false DASHBOARD_IDENTITY_DIAGNOSTICS=false DASHBOARD_SSO_WRITE_USERS= DASHBOARD_TEAM_DEFAULT_MANAGERS=
export DASHBOARD_SYNC_TRAIL_ON_START=false DASHBOARD_GT_SYNC_ENABLED=false DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED=false DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED=false DASHBOARD_BATCH_PREDICTION_ENABLED=false DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED=false
export DASHBOARD_DCHAT_CREDENTIALS_FILE=/dev/null DASHBOARD_RA_MODEL_API_KEY_FILE=/dev/null DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE=/dev/null DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE= DASHBOARD_BOOTSTRAP_MODEL_JSON= DASHBOARD_BATCH_BAG_CACHE_DIR="$DATA_DIR/batch_bags" RA_AUTO_TRIAGE_ROOT=/volume/home/workspace/ra_auto_triage
exec "$VENV_DIR/bin/python3" -m uvicorn app.main:app --app-dir "$APP_ROOT" --host 127.0.0.1 --port "$PORT" >> "$LOG_FILE" 2>&1
