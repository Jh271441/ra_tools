#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=8786
PROD_PORT=8785
PROD_EXPECTED_PID=10634
PROD_EXPECTED_BUILD=5fdc41ba8b0215170a8307237762e1ed50a9aaf2
S4_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
S4_SOURCE_SHA=e86a99f
S4_BUILD=b75aa55
S4_LAUNCHER_SHA=c3dc9e170e4f70fd1f55fe3ef03511f73e862da8569572c4759b6584f9a828dd
S4_APP_ROOT="$S4_ROOT/source-$S4_SOURCE_SHA/ra_triage_dashboard"
S4_LAUNCHER="$S4_APP_ROOT/scripts/run_s4_smoke.sh"
S5_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922
S5_SHA_FILE="$S5_ROOT/config/source_sha"
S5_PID_FILE="$S5_ROOT/runtime/s5.pid"

fail() { printf '%s\n' "$1" >&2; exit 1; }
listener() { ss -H -ltnp "sport = :$1"; }
listener_pid() { sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p'; }

[[ -d "$S5_ROOT" && "$(stat -c '%a' "$S5_ROOT")" == 700 ]] || fail "S5 private root is missing or not mode 0700."
[[ -f "$S5_SHA_FILE" && "$(stat -c '%a' "$S5_SHA_FILE")" == 600 ]] || fail "S5 source SHA file is missing or not mode 0600."
[[ -f "$S5_PID_FILE" && "$(stat -c '%a' "$S5_PID_FILE")" == 600 ]] || fail "S5 PID receipt is missing or not mode 0600."
S5_APP_SHA="$(cat "$S5_SHA_FILE")"
S5_PID="$(cat "$S5_PID_FILE")"
[[ "$S5_APP_SHA" =~ ^[a-f0-9]{40}$ && "$S5_PID" =~ ^[0-9]+$ ]] || fail "S5 source or PID receipt is invalid."
S5_APP_ROOT="$S5_ROOT/source-$S5_APP_SHA/ra_triage_dashboard"
[[ -x "$S4_LAUNCHER" ]] || fail "Pinned S4 launcher is missing."
printf '%s  %s\n' "$S4_LAUNCHER_SHA" "$S4_LAUNCHER" | sha256sum --check --status || fail "Pinned S4 launcher checksum changed."

PROD_LISTENER="$(listener "$PROD_PORT")"
[[ "$PROD_LISTENER" == *"0.0.0.0:$PROD_PORT"* && "$PROD_LISTENER" == *"pid=$PROD_EXPECTED_PID,"* ]] || fail "Production listener identity changed; refusing restore."
PROD_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PROD_PORT/health")"
printf '%s' "$PROD_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1]' "$PROD_EXPECTED_BUILD" || fail "Production health/build changed; refusing restore."

S5_LISTENER="$(listener "$PORT")"
[[ "$(printf '%s\n' "$S5_LISTENER" | sed '/^$/d' | wc -l | tr -d ' ')" == 1 ]] || fail "8786 must have exactly one S5 listener."
[[ "$S5_LISTENER" == *"127.0.0.1:$PORT"* && "$S5_LISTENER" == *"pid=$S5_PID,"* ]] || fail "8786 listener does not match the S5 PID receipt."
[[ -r "/proc/$S5_PID/cmdline" && -r "/proc/$S5_PID/environ" ]] || fail "S5 listener process is missing."
S5_ARGS="$(tr '\0' ' ' < "/proc/$S5_PID/cmdline")"
[[ "$S5_ARGS" == *"--app-dir $S5_APP_ROOT"* && "$S5_ARGS" == *"--host 127.0.0.1"* && "$S5_ARGS" == *"--port $PORT"* ]] || fail "8786 process is not the pinned S5 launcher."
S5_ENV="$(tr '\0' '\n' < "/proc/$S5_PID/environ")"
[[ "$S5_ENV" == *"DASHBOARD_BUILD_COMMIT=$S5_APP_SHA"* && "$S5_ENV" == *"DASHBOARD_BASE_PATH=/manual-s5"* ]] || fail "S5 process build/base-path identity mismatch."
S5_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s5/health")"
printf '%s' "$S5_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s5"' "$S5_APP_SHA" || fail "S5 health check failed; refusing restore."

kill -TERM "$S5_PID"
for _ in $(seq 1 30); do
  if [[ -z "$(listener "$PORT")" ]]; then break; fi
  sleep 1
done
[[ -z "$(listener "$PORT")" ]] || fail "Verified S5 process did not release 8786."

nohup "$S4_LAUNCHER" </dev/null >/dev/null 2>&1 &
S4_PID=$!
S4_HEALTH=
for _ in $(seq 1 60); do
  if S4_HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/manual-s4/health" 2>/dev/null)"; then break; fi
  sleep 1
done
[[ -n "$S4_HEALTH" ]] || fail "Pinned S4 launcher did not become healthy."
printf '%s' "$S4_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s4"' "$S4_BUILD" || fail "S4 build/base-path health mismatch."
S4_STATUS="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/status")"
printf '%s' "$S4_STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert int(d.get("database",{}).get("migration_count",0))==46; assert not d.get("batch_prediction_enabled"); assert not d.get("autotriage_push_enabled"); assert not (d.get("review_notifications",{}).get("enabled"))' || fail "Restored S4 is not in the expected read-only external-writer-disabled state."
S4_SESSION="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/session")"
printf '%s' "$S4_SESSION" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only") is True and d.get("can_write") is False' || fail "Restored S4 unauthenticated session is not read-only."
rm -f "$S5_PID_FILE"
printf 'Pinned S4 restored on loopback 8786: %s (process %s)\n' "$S4_BUILD" "$S4_PID"
