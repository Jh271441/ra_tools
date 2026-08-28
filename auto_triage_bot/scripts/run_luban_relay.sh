#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="${AUTOTRIAGE_BOT_REPO_ROOT:-$(cd "${script_dir}/../.." && pwd)}"
runtime_python="${AUTOTRIAGE_BOT_PYTHON:-python3}"
data_dir="${AUTOTRIAGE_BOT_DATA_DIR:-}"

if [[ -z "${data_dir}" ]]; then
  echo "Luban relay 必须显式配置持久化 AUTOTRIAGE_BOT_DATA_DIR。" >&2
  exit 1
fi
webhook_secret_file="${AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE:-${data_dir}/webhook_secret}"
worker_secret_file="${AUTOTRIAGE_BOT_RELAY_WORKER_SECRET_FILE:-${data_dir}/relay_worker_secret}"

if ! command -v "${runtime_python}" >/dev/null 2>&1 && [[ ! -x "${runtime_python}" ]]; then
  echo "Auto Triage Relay runtime Python 不可用。" >&2
  exit 1
fi
if [[ ! -f "${webhook_secret_file}" || ! -f "${worker_secret_file}" ]]; then
  echo "Relay webhook/worker token 尚未配置。" >&2
  exit 1
fi

umask 077
export PYTHONPATH="${repo_root}${PYTHONPATH:+:${PYTHONPATH}}"
export AUTOTRIAGE_BOT_ENABLED="${AUTOTRIAGE_BOT_ENABLED:-true}"
export AUTOTRIAGE_BOT_BASE_PATH="${AUTOTRIAGE_BOT_BASE_PATH:-/dchat}"
export AUTOTRIAGE_BOT_WORKER_BASE_PATH="${AUTOTRIAGE_BOT_WORKER_BASE_PATH:-/dchat-worker}"
export AUTOTRIAGE_BOT_ALLOWED_USERS="${AUTOTRIAGE_BOT_ALLOWED_USERS:-jasperchen}"
export AUTOTRIAGE_BOT_ALLOW_ALL_USERS="${AUTOTRIAGE_BOT_ALLOW_ALL_USERS:-false}"
export AUTOTRIAGE_BOT_HOST="${AUTOTRIAGE_BOT_HOST:-0.0.0.0}"
export AUTOTRIAGE_BOT_PORT="${AUTOTRIAGE_BOT_PORT:-18790}"
export AUTOTRIAGE_BOT_DATA_DIR="${data_dir}"
export AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE="${AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE:-token}"
export AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE="${webhook_secret_file}"
export AUTOTRIAGE_BOT_RELAY_WORKER_SECRET_FILE="${worker_secret_file}"
export AUTOTRIAGE_BOT_RELAY_WORKER_ID="${AUTOTRIAGE_BOT_RELAY_WORKER_ID:-cloud-server-1}"

cd "${repo_root}"
exec "${runtime_python}" -m auto_triage_bot.relay_server
