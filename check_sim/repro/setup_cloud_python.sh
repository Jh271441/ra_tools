#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
venv_dir="${repo_root}/.venv"
voy_sdk_python="/opt/voy-sdk/lib/python3/dist-packages"
ezsim_lib="${HOME}/.voyager/ezsim/binary/1665523/tmp/lib"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required but was not found in PATH" >&2
  exit 1
}

uv venv \
  --python 3.10 \
  --system-site-packages \
  --no-python-downloads \
  --allow-existing \
  "${venv_dir}"

PYTHONPATH="${voy_sdk_python}:${PYTHONPATH:-}" \
LD_LIBRARY_PATH="${ezsim_lib}:${LD_LIBRARY_PATH:-}" \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  "${venv_dir}/bin/python3" - <<'PY'
import numpy
import onnxruntime
import pandas
import requests
import rosbag

print("cloud Python environment is ready")
print(f"numpy={numpy.__version__}")
print(f"onnxruntime={onnxruntime.__version__}")
print(f"pandas={pandas.__version__}")
print(f"requests={requests.__version__}")
print(f"rosbag={rosbag.__file__}")
PY
