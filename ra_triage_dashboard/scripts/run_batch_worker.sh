#!/usr/bin/env bash
set -eo pipefail
umask 077

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${DASHBOARD_PYTHON_BIN:-/volume/home/workspace/ra_triage_dashboard_venv/bin/python3}"
VOYAGER_SETUP_SCRIPT="${VOYAGER_SETUP_SCRIPT:-/volume/home/workspace/voyager/bazel/scripts/setup.sh}"
RA_AUTO_TRIAGE_ROOT="${RA_AUTO_TRIAGE_ROOT:-/volume/home/workspace/ra_auto_triage}"

if [[ ! -f "$VOYAGER_SETUP_SCRIPT" ]]; then
  echo "Voyager setup script is missing: $VOYAGER_SETUP_SCRIPT" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Dashboard worker Python is missing: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -d "$RA_AUTO_TRIAGE_ROOT/vlm" ]]; then
  echo "RA AutoTriage checkout is invalid: $RA_AUTO_TRIAGE_ROOT" >&2
  exit 1
fi

export RA_AUTO_TRIAGE_ROOT
export PYTHONUNBUFFERED=1

# Voyager's setup script reads optional unset variables, so enable nounset only
# after it has prepared PYTHONPATH and LD_LIBRARY_PATH for labeler/voy_vbag.
source "$VOYAGER_SETUP_SCRIPT" >/dev/null
set -u
exec "$PYTHON_BIN" "$APP_ROOT/app/batch_prediction_worker.py"
