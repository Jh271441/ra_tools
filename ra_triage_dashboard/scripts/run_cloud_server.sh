#!/usr/bin/env bash
set -e

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${DASHBOARD_VENV_DIR:-/volume/home/workspace/ra_triage_dashboard_venv}"
PYTHON_BIN="${DASHBOARD_PYTHON_BIN:-$VENV_DIR/bin/python3}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Dashboard Python environment is missing: $PYTHON_BIN" >&2
  echo "Run: bash $APP_ROOT/scripts/bootstrap_cloud_server_env.sh" >&2
  exit 1
fi

export DASHBOARD_DATA_DIR="${DASHBOARD_DATA_DIR:-/volume/home/workspace/ra_triage_dashboard_data}"
DEFAULT_DATABASE_URL_FILE="$DASHBOARD_DATA_DIR/postgres_url"
if [[ -f "$DEFAULT_DATABASE_URL_FILE" ]]; then
  export DASHBOARD_DATABASE_URL_FILE="${DASHBOARD_DATABASE_URL_FILE:-$DEFAULT_DATABASE_URL_FILE}"
  POSTGRES_DATA_DIR="${DASHBOARD_POSTGRES_DATA_DIR:-/volume/postgresql/14/main}"
  if ! sudo test -f "$POSTGRES_DATA_DIR/PG_VERSION"; then
    echo "Persistent PostgreSQL data directory is missing: $POSTGRES_DATA_DIR" >&2
    echo "Run scripts/migrate_cloud_postgres_data.sh during a maintenance window." >&2
    exit 1
  fi
  CONFIGURED_DATA_DIR="$(sudo pg_conftool 14 main show data_directory | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d "'\"" | xargs)"
  if [[ "$CONFIGURED_DATA_DIR" != "$POSTGRES_DATA_DIR" ]]; then
    echo "Refusing to start against non-persistent PostgreSQL data: $CONFIGURED_DATA_DIR" >&2
    exit 1
  fi
  export DASHBOARD_POSTGRES_PERSISTENT_DATA=true
  if command -v pg_isready >/dev/null 2>&1 && ! pg_isready --quiet; then
    # cloud_server has no systemd init process, so recover PostgreSQL explicitly
    # after a host/container restart before starting the dashboard.
    sudo pg_ctlcluster 14 main start
  fi
fi
export DASHBOARD_BUILD_COMMIT="${DASHBOARD_BUILD_COMMIT:-unverified}"
export DASHBOARD_HOST="${DASHBOARD_HOST:-0.0.0.0}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-8785}"
# Root/direct-IP mode remains the default. For the Kylin rule that strips
# /dashboard before proxying, start with DASHBOARD_BASE_PATH=/dashboard.
export DASHBOARD_BASE_PATH="${DASHBOARD_BASE_PATH:-}"
export RA_AUTO_TRIAGE_ROOT="/volume/home/workspace/ra_auto_triage"
export ARES_CAPTURE_MANIFEST="/volume/home/workspace/ra_auto_triage/bags/ares_capture_bev/manifest.jsonl"
export CAMERA_CACHE_ROOT="/volume/home/workspace/ra_auto_triage/bags/camera"
export ARES_CAPTURE_VIDEO_ROOT="${ARES_CAPTURE_VIDEO_ROOT:-/volume/home/workspace/ra_auto_triage/bags/ares_capture_video_0508_1071_ra_stuck_swag_planning_2k_20260731}"
export DASHBOARD_BASELINE_LABEL_XLSX="/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx"
export DASHBOARD_BASELINE_DATASET="0508"
export DASHBOARD_BASELINE_SCOPE="release0508_1071_20260729"
export DASHBOARD_TRAIL_VIEW_ID="${DASHBOARD_TRAIL_VIEW_ID:-2410}"
export DASHBOARD_SYNC_TRAIL_ON_START="${DASHBOARD_SYNC_TRAIL_ON_START:-true}"
export DASHBOARD_VOYAGER_ISSUE_BASE_URL="${DASHBOARD_VOYAGER_ISSUE_BASE_URL:-https://voyager.intra.xiaojukeji.com/static/management/#/issue}"
export DASHBOARD_VOYAGER_ISSUE_VIEW_ID="${DASHBOARD_VOYAGER_ISSUE_VIEW_ID:-2410}"
export DASHBOARD_BATCH_PREDICTION_ENABLED="${DASHBOARD_BATCH_PREDICTION_ENABLED:-true}"
export DASHBOARD_AUTOTRIAGE_PUSH_ENABLED="${DASHBOARD_AUTOTRIAGE_PUSH_ENABLED:-false}"
export DASHBOARD_BATCH_MAX_ISSUES="${DASHBOARD_BATCH_MAX_ISSUES:-50}"
export DASHBOARD_BATCH_JOB_TIMEOUT_SECONDS="${DASHBOARD_BATCH_JOB_TIMEOUT_SECONDS:-7200}"
export DASHBOARD_BATCH_BAG_CACHE_DIR="${DASHBOARD_BATCH_BAG_CACHE_DIR:-$DASHBOARD_DATA_DIR/batch_bags}"
export DASHBOARD_RA_MODEL_CATALOG_URL="${DASHBOARD_RA_MODEL_CATALOG_URL:-http://ra-model.intra.xiaojukeji.com/v1/models}"
export DASHBOARD_RA_MODEL_CHAT_URL="${DASHBOARD_RA_MODEL_CHAT_URL:-http://ra-model.intra.xiaojukeji.com/v1/chat/completions}"
export DASHBOARD_RA_MODEL_TOKENSERVICE_CATALOG_URL="${DASHBOARD_RA_MODEL_TOKENSERVICE_CATALOG_URL:-https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/models}"
export DASHBOARD_RA_MODEL_TOKENSERVICE_CHAT_URL="${DASHBOARD_RA_MODEL_TOKENSERVICE_CHAT_URL:-https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/chat/completions}"
export DASHBOARD_RA_MODEL_DEFAULT_ID="${DASHBOARD_RA_MODEL_DEFAULT_ID:-auto}"
export DASHBOARD_RA_MODEL_CATALOG_TTL_SECONDS="${DASHBOARD_RA_MODEL_CATALOG_TTL_SECONDS:-300}"
export DASHBOARD_RA_MODEL_PROFILE_PATH="${DASHBOARD_RA_MODEL_PROFILE_PATH:-$APP_ROOT/config/model_profiles.json}"
export DASHBOARD_RA_MODEL_API_KEY_FILE="${DASHBOARD_RA_MODEL_API_KEY_FILE:-/volume/home/workspace/ra_triage_dashboard_data/model_gateway_api_key}"
export DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE="${DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE:-/volume/home/workspace/ra_triage_dashboard_data/tokenservice_api_key}"
export DASHBOARD_AUTO_TRIAGE_RECORD_BASE_URL="${DASHBOARD_AUTO_TRIAGE_RECORD_BASE_URL:-http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records}"
export DASHBOARD_AUTOTRIAGE_API_BASE_URL="${DASHBOARD_AUTOTRIAGE_API_BASE_URL:-http://10.190.57.183:8000}"

# Intentionally no default DASHBOARD_BOOTSTRAP_MODEL_JSON: the default model
# comparison is the read-only Trail field snapshot, not the historical 348 run.

exec "$PYTHON_BIN" -m uvicorn app.main:app --app-dir "$APP_ROOT" --host "$DASHBOARD_HOST" --port "$DASHBOARD_PORT"
