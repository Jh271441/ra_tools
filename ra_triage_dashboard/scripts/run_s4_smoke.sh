#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
APP_ROOT="$ROOT/source-fab4143/ra_triage_dashboard"
VENV_DIR=/volume/home/workspace/ra_triage_dashboard_venv
PORT=8786
LAYOUT_ID=release0508_1071_20260729
DB_URL_FILE="${DASHBOARD_DATABASE_URL_FILE:-$ROOT/config/postgres_url}"
DATA_DIR="${DASHBOARD_DATA_DIR:-$ROOT/data}"
LOG_FILE="${DASHBOARD_LOG_FILE:-$ROOT/logs/server.log}"

if [[ ! -d "$APP_ROOT" || ! -f "$APP_ROOT/app/main.py" ]]; then
  echo "S4 versioned application source is missing." >&2
  exit 1
fi
if [[ "$(stat -c '%a' "$ROOT")" != 700 || "$(stat -c '%U' "$ROOT")" != "$(id -un)" ]]; then
  echo "S4 experiment root must be owned and private (0700)." >&2
  exit 1
fi
case "$DB_URL_FILE" in
  "$ROOT"/config/*) ;;
  *) echo "S4 PostgreSQL URL file must stay under the private experiment config directory." >&2; exit 1 ;;
esac
case "$DATA_DIR" in
  "$ROOT"/data/*|"$ROOT"/data) ;;
  *) echo "S4 data directory must stay under the private experiment root." >&2; exit 1 ;;
esac
case "$LOG_FILE" in
  "$ROOT"/logs/*) ;;
  *) echo "S4 log file must stay under the private experiment logs directory." >&2; exit 1 ;;
esac
if [[ "$(stat -c '%a' "$DB_URL_FILE")" != 600 || "$(stat -c '%U' "$DB_URL_FILE")" != "$(id -un)" ]]; then
  echo "S4 PostgreSQL URL file must be owned and private (0600)." >&2
  exit 1
fi
if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
  echo "Dashboard Python environment is missing." >&2
  exit 1
fi
if ss -H -ltn "sport = :$PORT" | grep -q .; then
  echo "Port $PORT is occupied; refusing to replace an unverified process." >&2
  exit 1
fi

install -d -m 700 \
  "$(dirname "$LOG_FILE")" \
  "$DATA_DIR/media_layouts/$LAYOUT_ID" \
  "$DATA_DIR/intent_media/bev" \
  "$DATA_DIR/intent_media/camera41" \
  "$DATA_DIR/issue_tag_sources" \
  "$DATA_DIR/batch_bags"

unset DASHBOARD_DATABASE_URL
export DASHBOARD_VENV_DIR="$VENV_DIR"
export DASHBOARD_DATABASE_URL_FILE="$DB_URL_FILE"
export DASHBOARD_DATA_DIR="$DATA_DIR"
export DASHBOARD_POSTGRES_PERSISTENT_DATA=false
export DASHBOARD_BUILD_COMMIT=fab414311a00fb39e514b829802e88b2b660d927
export DASHBOARD_HOST=127.0.0.1
export DASHBOARD_PORT="$PORT"
export DASHBOARD_BASE_PATH=/manual-s4

export DASHBOARD_BASELINES_FILE="$ROOT/config/baselines.json"
export DASHBOARD_BASELINE_LABEL_XLSX="$ROOT/baselines/trail_0508_0206_subset.xlsx"
export DASHBOARD_BASELINE_DATASET=0508
export DASHBOARD_BASELINE_SCOPE=release0508_1071_20260729
export DASHBOARD_BASELINE_OVERLAP_MODE=fail_skip

export DASHBOARD_MEDIA_LAYOUT_ROOT="$DATA_DIR/media_layouts"
export DASHBOARD_MEDIA_LAYOUT="$LAYOUT_ID"
export ARES_CAPTURE_RA_ROOT="$DATA_DIR/media_layouts/$LAYOUT_ID"
export ARES_CAPTURE_MANIFEST="$DATA_DIR/media_layouts/$LAYOUT_ID/manifest.jsonl"
export CAMERA_CACHE_ROOT="$DATA_DIR/media_layouts/$LAYOUT_ID/camera/102"
export ARES_CAPTURE_VIDEO_ROOT="$DATA_DIR/media_layouts/$LAYOUT_ID/video"
export DASHBOARD_INTENT_BEV_ROOT="$DATA_DIR/intent_media/bev"
export DASHBOARD_INTENT_CAMERA_ROOT="$DATA_DIR/intent_media/camera41"
export DASHBOARD_INTENT_CAMERA_MANIFEST="$DATA_DIR/intent_media/camera41/source_manifest.jsonl"
export DASHBOARD_ISSUE_TAG_SOURCE_0206_XLSX="$DATA_DIR/issue_tag_sources/0206.xlsx"
export DASHBOARD_ISSUE_TAG_SOURCE_0626_XLSX="$DATA_DIR/issue_tag_sources/0626.xlsx"

export DASHBOARD_SEED_EXAMPLES_ENABLED=false
export DASHBOARD_DEPLOYMENT_MODE=production
export DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=false
export DASHBOARD_IDENTITY_DIAGNOSTICS=false
export DASHBOARD_KYLIN_SSO_ENABLED=true
export DASHBOARD_SSO_WRITE_USERS=
export DASHBOARD_TEAM_DEFAULT_MANAGERS=

export DASHBOARD_SYNC_TRAIL_ON_START=false
export DASHBOARD_GT_SYNC_ENABLED=false
export DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED=false
export DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false
export DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED=false
export DASHBOARD_BATCH_PREDICTION_ENABLED=false
export DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false
export DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED=false
export DASHBOARD_DCHAT_CREDENTIALS_FILE=/dev/null
export DASHBOARD_RA_MODEL_API_KEY_FILE=/dev/null
export DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE=/dev/null
export DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE=
export DASHBOARD_BOOTSTRAP_MODEL_JSON=
export DASHBOARD_BATCH_BAG_CACHE_DIR="$DATA_DIR/batch_bags"
export RA_AUTO_TRIAGE_ROOT=/volume/home/workspace/ra_auto_triage

exec "$VENV_DIR/bin/python3" -m uvicorn app.main:app \
  --app-dir "$APP_ROOT" --host "$DASHBOARD_HOST" --port "$DASHBOARD_PORT" \
  >> "$LOG_FILE" 2>&1
