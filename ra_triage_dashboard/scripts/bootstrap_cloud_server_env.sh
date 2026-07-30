#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${DASHBOARD_VENV_DIR:-/volume/home/workspace/ra_triage_dashboard_venv}"

if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
  python3 -m venv --system-site-packages "$VENV_DIR"
fi

"$VENV_DIR/bin/python3" -m pip install \
  -r "$APP_ROOT/requirements-runtime.txt"

"$VENV_DIR/bin/python3" - <<'PY'
import fastapi
import multipart
import openpyxl
import pandas
import PIL
import uvicorn

print(
    "dashboard runtime:",
    f"fastapi={fastapi.__version__}",
    f"uvicorn={uvicorn.__version__}",
    f"python-multipart={multipart.__version__}",
    f"openpyxl={openpyxl.__version__}",
    f"pandas={pandas.__version__}",
    f"Pillow={PIL.__version__}",
)
PY
