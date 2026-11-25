#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=8786
PY=/volume/home/workspace/ra_triage_dashboard_venv/bin/python3
S4_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
S4_APP="$S4_ROOT/source-e86a99f/ra_triage_dashboard"
S4_APP_NEW="$S4_ROOT/source-fab4143/ra_triage_dashboard"
S4_APP_OLD="$S4_ROOT/source-c8ba26b/ra_triage_dashboard"
S3_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s3_smoke_20260921
S3_SCRIPT="$S3_ROOT/run_s3_smoke.sh"
S3_APP=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/model-review-s3-f626c1a-code/ra_triage_dashboard
S3_SESSION=ra_triage_dashboard_s3_restore_20260921
S3_URL=http://127.0.0.1:8786/manual-s3
EXPECTED_S3_SCRIPT_SHA=6833d7951687f6a8ec7a13cec15cba9e435959e8025213dfffe5eb160b0ef780
EXPECTED_S3_BUILD=53c9e67cfc5b9a95ea81b89643808ef39520d8e3

if [[ ! -x "$PY" || ! -x "$S3_SCRIPT" ]]; then
  echo "S3 restore prerequisites are missing." >&2
  exit 1
fi
ACTUAL_S3_SCRIPT_SHA="$(sha256sum "$S3_SCRIPT" | awk '{print $1}')"
if [[ "$ACTUAL_S3_SCRIPT_SHA" != "$EXPECTED_S3_SCRIPT_SHA" ]]; then
  echo "S3 launcher changed since the smoke baseline; refusing restore." >&2
  exit 1
fi

health_s3() {
  "$PY" - "$S3_URL/health" "$EXPECTED_S3_BUILD" <<'PY'
import json
import sys
from urllib.request import urlopen

url, expected_build = sys.argv[1], sys.argv[2]
with urlopen(url, timeout=4) as response:
    payload = json.load(response)
if payload.get("ok") is not True:
    raise SystemExit("S3 health endpoint did not report ok.")
if payload.get("build_commit") != expected_build:
    raise SystemExit("S3 build commit does not match the recorded smoke baseline.")
if payload.get("base_path") != "/manual-s3":
    raise SystemExit("S3 base path does not match the recorded smoke baseline.")
if payload.get("trail_attribute_write_enabled") is not False:
    raise SystemExit("S3 Trail attribute writes are not disabled.")
if payload.get("trail_attribute_review_write_enabled") is not False:
    raise SystemExit("S3 review writes are not disabled.")
if payload.get("batch_prediction_enabled") is not False:
    raise SystemExit("S3 batch prediction is not disabled.")
if payload.get("autotriage_push_enabled") is not False:
    raise SystemExit("S3 AutoTriage push is not disabled.")
if (payload.get("review_notifications") or {}).get("enabled") is not False:
    raise SystemExit("S3 DChat notifications are not disabled.")
print("S3_HEALTH_OK build_commit={} base_path={}".format(
    payload["build_commit"], payload["base_path"]
))
PY
}

listener="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
if [[ -n "$listener" ]]; then
  pid="$(sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' <<<"$listener" | head -1)"
  if [[ -z "$pid" || ! -r "/proc/$pid/cmdline" ]]; then
    echo "Cannot verify the process listening on port $PORT; refusing to stop it." >&2
    exit 1
  fi
  command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$command_line" == *"$S3_APP"* ]]; then
    health_s3
    echo "S3 is already serving 8786."
    exit 0
  fi
  if [[ "$command_line" != *"$S4_APP"* && "$command_line" != *"$S4_APP_NEW"* && "$command_line" != *"$S4_APP_OLD"* ]]; then
    echo "Port $PORT is held by an unknown application; refusing to stop it." >&2
    exit 1
  fi
  kill -TERM "$pid"
fi

for attempt in $(seq 1 30); do
  listener="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
  if [[ -z "$listener" ]]; then
    break
  fi
  pid="$(sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' <<<"$listener" | head -1)"
  if [[ -z "$pid" || ! -r "/proc/$pid/cmdline" ]]; then
    echo "Cannot verify the new port $PORT listener; refusing to continue." >&2
    exit 1
  fi
  command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$command_line" != *"$S4_APP"* && "$command_line" != *"$S4_APP_NEW"* && "$command_line" != *"$S4_APP_OLD"* ]]; then
    echo "Port $PORT changed to an unknown listener during restore; refusing to continue." >&2
    exit 1
  fi
  sleep 1
done
if [[ -n "$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)" ]]; then
  echo "S4 did not release port $PORT; S3 was not started." >&2
  exit 1
fi

if tmux has-session -t "$S3_SESSION" 2>/dev/null; then
  echo "Restore tmux session already exists; inspect it before retrying." >&2
  exit 1
fi
tmux new-session -d -s "$S3_SESSION" "bash $S3_SCRIPT"

for attempt in $(seq 1 60); do
  listener="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
  if [[ -n "$listener" ]]; then
    pid="$(sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' <<<"$listener" | head -1)"
    if [[ -z "$pid" || ! -r "/proc/$pid/cmdline" ]]; then
      echo "Cannot verify the process after starting S3." >&2
      exit 1
    fi
    command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$command_line" != *"$S3_APP"* ]]; then
      echo "Unexpected application bound to port $PORT after starting S3." >&2
      exit 1
    fi
    if health_output="$(health_s3 2>/dev/null)"; then
      printf '%s\n' "$health_output"
      echo "RESTORE_OK port=$PORT session=$S3_SESSION"
      exit 0
    fi
  fi
  sleep 1
done

echo "S3 did not pass its local health check after 60 seconds." >&2
exit 1
