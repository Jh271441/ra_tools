#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
APP_ROOT="$ROOT/source-fab4143/ra_triage_dashboard"
VENV_DIR=/volume/home/workspace/ra_triage_dashboard_venv
PORT=8786
LAYOUT_ID=release0508_1071_20260729

if [[ ! -d "$APP_ROOT" || ! -f "$APP_ROOT/app/main.py" ]]; then
  echo "S4 versioned application source is missing." >&2
  exit 1
fi
if [[ "$(stat -c '%a' "$ROOT")" != 700 || "$(stat -c '%U' "$ROOT")" != "$(id -un)" ]]; then
  echo "S4 experiment root must be owned and private (0700)." >&2
  exit 1
fi
if [[ "$(stat -c '%a' "$ROOT/config/postgres_url")" != 600 || "$(stat -c '%U' "$ROOT/config/postgres_url")" != "$(id -un)" ]]; then
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
  "$ROOT/logs" \
  "$ROOT/data/media_layouts/$LAYOUT_ID" \
  "$ROOT/data/intent_media/bev" \
  "$ROOT/data/intent_media/camera41" \
  "$ROOT/data/issue_tag_sources" \
  "$ROOT/data/batch_bags"

unset DASHBOARD_DATABASE_URL
export DASHBOARD_VENV_DIR="$VENV_DIR"
export DASHBOARD_DATABASE_URL_FILE="$ROOT/config/postgres_url"
export DASHBOARD_DATA_DIR="$ROOT/data"
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

export DASHBOARD_MEDIA_LAYOUT_ROOT="$ROOT/data/media_layouts"
export DASHBOARD_MEDIA_LAYOUT="$LAYOUT_ID"
export ARES_CAPTURE_RA_ROOT="$ROOT/data/media_layouts/$LAYOUT_ID"
export ARES_CAPTURE_MANIFEST="$ROOT/data/media_layouts/$LAYOUT_ID/manifest.jsonl"
export CAMERA_CACHE_ROOT="$ROOT/data/media_layouts/$LAYOUT_ID/camera/102"
export ARES_CAPTURE_VIDEO_ROOT="$ROOT/data/media_layouts/$LAYOUT_ID/video"
export DASHBOARD_INTENT_BEV_ROOT="$ROOT/data/intent_media/bev"
export DASHBOARD_INTENT_CAMERA_ROOT="$ROOT/data/intent_media/camera41"
export DASHBOARD_INTENT_CAMERA_MANIFEST="$ROOT/data/intent_media/camera41/source_manifest.jsonl"
export DASHBOARD_ISSUE_TAG_SOURCE_0206_XLSX="$ROOT/data/issue_tag_sources/0206.xlsx"
export DASHBOARD_ISSUE_TAG_SOURCE_0626_XLSX="$ROOT/data/issue_tag_sources/0626.xlsx"

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
export DASHBOARD_BATCH_BAG_CACHE_DIR="$ROOT/data/batch_bags"
export RA_AUTO_TRIAGE_ROOT=/volume/home/workspace/ra_auto_triage

exec "$VENV_DIR/bin/python3" -m uvicorn app.main:app \
  --app-dir "$APP_ROOT" --host "$DASHBOARD_HOST" --port "$DASHBOARD_PORT" \
  >> "$ROOT/logs/server.log" 2>&1
