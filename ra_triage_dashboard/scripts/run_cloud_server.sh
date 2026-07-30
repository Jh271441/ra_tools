#!/usr/bin/env bash
set -e

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DASHBOARD_DATA_DIR="/volume/home/workspace/ra_triage_dashboard_data"
export RA_AUTO_TRIAGE_ROOT="/volume/home/workspace/ra_auto_triage"
export ARES_CAPTURE_MANIFEST="/volume/home/workspace/ra_auto_triage/bags/ares_capture_bev/manifest.jsonl"
export CAMERA_CACHE_ROOT="/volume/home/workspace/ra_auto_triage/bags/camera"
export DASHBOARD_BASELINE_LABEL_XLSX="/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx"
export DASHBOARD_BASELINE_DATASET="0508"
export DASHBOARD_BASELINE_SCOPE="release0508_1071_20260729"
export DASHBOARD_TRAIL_VIEW_ID="${DASHBOARD_TRAIL_VIEW_ID:-1000}"
export DASHBOARD_SYNC_TRAIL_ON_START="${DASHBOARD_SYNC_TRAIL_ON_START:-true}"

# Intentionally no default DASHBOARD_BOOTSTRAP_MODEL_JSON: the default model
# comparison is the read-only Trail field snapshot, not the historical 348 run.

exec python3 -m uvicorn app.main:app --app-dir "$APP_ROOT" --host 0.0.0.0 --port 8785
