#!/usr/bin/env bash
set -euo pipefail

repo_root="${AUTOTRIAGE_BOT_REPO_ROOT:-/volume/home/workspace/ra_tools}"
data_dir="${AUTOTRIAGE_BOT_DATA_DIR:-/volume/home/workspace/ra_triage_bot_data}"
runtime_python="${AUTOTRIAGE_BOT_PYTHON:-/volume/home/workspace/ra_triage_dashboard_venv/bin/python3}"
webhook_secret_file="${AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE:-${data_dir}/webhook_secret}"

if [[ ! -x "${runtime_python}" ]]; then
  echo "Auto Triage Bot runtime Python 不可用。" >&2
  exit 1
fi
if [[ ! -f "${webhook_secret_file}" ]]; then
  echo "Auto Triage Bot webhook secret 尚未配置。" >&2
  exit 1
fi

umask 077
export PYTHONPATH="${repo_root}${PYTHONPATH:+:${PYTHONPATH}}"
export AUTOTRIAGE_BOT_ENABLED="${AUTOTRIAGE_BOT_ENABLED:-true}"
export AUTOTRIAGE_BOT_SMOKE_ENABLED="${AUTOTRIAGE_BOT_SMOKE_ENABLED:-true}"
export AUTOTRIAGE_BOT_ALLOWED_USERS="${AUTOTRIAGE_BOT_ALLOWED_USERS:-jasperchen}"
export AUTOTRIAGE_BOT_ALLOW_ALL_USERS="${AUTOTRIAGE_BOT_ALLOW_ALL_USERS:-false}"
export AUTOTRIAGE_BOT_HOST="${AUTOTRIAGE_BOT_HOST:-0.0.0.0}"
export AUTOTRIAGE_BOT_PORT="${AUTOTRIAGE_BOT_PORT:-8790}"
export AUTOTRIAGE_BOT_DATA_DIR="${data_dir}"
export AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE="${AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE:-token}"
export AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE="${webhook_secret_file}"
export AUTOTRIAGE_BOT_DASHBOARD_URL="${AUTOTRIAGE_BOT_DASHBOARD_URL:-http://127.0.0.1:8785}"
export AUTOTRIAGE_BOT_REVIEW_URL="${AUTOTRIAGE_BOT_REVIEW_URL:-https://auto-triage.intra.xiaojukeji.com/manual/review}"
export AUTOTRIAGE_BOT_DELIVERY_MODE="${AUTOTRIAGE_BOT_DELIVERY_MODE:-loopback}"
export AUTOTRIAGE_BOT_DCHAT_CREDENTIALS_FILE="${AUTOTRIAGE_BOT_DCHAT_CREDENTIALS_FILE:-/volume/home/workspace/ra_triage_dashboard_data/dchat_credentials.json}"
export AUTOTRIAGE_BOT_MODEL_CHAT_URL="${AUTOTRIAGE_BOT_MODEL_CHAT_URL:-http://ra-model.intra.xiaojukeji.com/v1/chat/completions}"
export AUTOTRIAGE_BOT_MODEL_API_KEY_FILE="${AUTOTRIAGE_BOT_MODEL_API_KEY_FILE:-/volume/home/workspace/ra_triage_dashboard_data/model_gateway_api_key}"
export AUTOTRIAGE_BOT_MODEL_ID="${AUTOTRIAGE_BOT_MODEL_ID:-Qwen3.5-9B-finetuned/base}"

cd "${repo_root}"
exec "${runtime_python}" -m uvicorn auto_triage_bot.main:app \
  --host "${AUTOTRIAGE_BOT_HOST}" \
  --port "${AUTOTRIAGE_BOT_PORT}" \
  --no-access-log
