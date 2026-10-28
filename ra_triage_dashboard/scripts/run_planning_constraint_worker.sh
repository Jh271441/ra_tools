#!/usr/bin/env bash
set -eo pipefail
umask 077
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${DASHBOARD_PYTHON_BIN:-/volume/home/workspace/ra_triage_dashboard_venv/bin/python3}"
VOYAGER_SETUP_SCRIPT="${VOYAGER_SETUP_SCRIPT:-/volume/home/workspace/voyager/bazel/scripts/setup.sh}"
test -f "$VOYAGER_SETUP_SCRIPT"
test -x "$PYTHON_BIN"
source "$VOYAGER_SETUP_SCRIPT" >/dev/null
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1
exec "$PYTHON_BIN" "$APP_ROOT/scripts/planning_constraint_worker.py"
