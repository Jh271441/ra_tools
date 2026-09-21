#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=8786
PROD_PORT=8785
PROD_EXPECTED_PID=10634
PROD_EXPECTED_BUILD=5fdc41ba8b0215170a8307237762e1ed50a9aaf2
S4_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s4_smoke_20260921_campaign
S4_BUILD=b75aa55
S4_FAB_BUILD=fab414311a00fb39e514b829802e88b2b660d927
S4_MAIN_SHA=36e116c70f2b0a461c73591e5131697c2b173f3dc42d4ca00616ecfe72c75d91
S4_E86_CORE_SHA=fcb24e0a3c49deb4ef1418e70d81285af035669f40a8f3e6ad984784fe782802
S4_FAB_CORE_SHA=3f666d7a016a2bff108712656d8a9d2a6b45d473
S5_ROOT=/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s5_run_collections_20260922
S4_FROZEN_ROOT="$S5_ROOT/s4-restore-source-bf74512"
S4_FROZEN_APP_ROOT="$S4_FROZEN_ROOT/ra_triage_dashboard"
S4_E86_APP_ROOT="$S4_ROOT/source-e86a99f/ra_triage_dashboard"
S4_FAB_APP_ROOT="$S4_ROOT/source-fab4143/ra_triage_dashboard"
S5_SHA_FILE="$S5_ROOT/config/source_sha"
S5_PID_FILE="$S5_ROOT/runtime/s5.pid"

fail() { printf '%s\n' "$1" >&2; exit 1; }
listener() { ss -H -ltnp "sport = :$1"; }
listener_pid() { sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p'; }
file_sha() { sha256sum "$1" | awk '{print $1}'; }

[[ -d "$S5_ROOT" && "$(stat -c '%a' "$S5_ROOT")" == 700 ]] || fail "S5 private root is missing or not mode 0700."
[[ -f "$S5_SHA_FILE" && "$(stat -c '%a' "$S5_SHA_FILE")" == 600 ]] || fail "S5 source SHA file is missing or not mode 0600."
S5_APP_SHA="$(cat "$S5_SHA_FILE")"
[[ "$S5_APP_SHA" =~ ^[a-f0-9]{40}$ ]] || fail "S5 source SHA is invalid."
S5_APP_ROOT="$S5_ROOT/source-$S5_APP_SHA/ra_triage_dashboard"
S5_LAUNCHER="$S5_APP_ROOT/scripts/run_s5_smoke.sh"
[[ -x "$S5_LAUNCHER" ]] || fail "Versioned S5 launcher is missing."
[[ -f "$S5_ROOT/config/postgres_url" && "$(stat -c '%a' "$S5_ROOT/config/postgres_url")" == 600 ]] || fail "S5 DB URL file is missing or not mode 0600."
[[ -d "$S4_FROZEN_ROOT" && "$(git -C "$S4_FROZEN_ROOT" rev-parse HEAD)" == "bf745129e4e7359db3631c18ee60da3e20ab74f2" ]] || fail "Frozen S4 restore worktree is not bf74512."

PROD_LISTENER="$(listener "$PROD_PORT")"
[[ "$PROD_LISTENER" == *"0.0.0.0:$PROD_PORT"* && "$PROD_LISTENER" == *"pid=$PROD_EXPECTED_PID,"* ]] || fail "Production listener identity changed; refusing the S5 switch."
PROD_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PROD_PORT/health")"
printf '%s' "$PROD_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1]' "$PROD_EXPECTED_BUILD" || fail "Production health/build changed; refusing the S5 switch."

[[ -z "$(listener 8787)" ]] || fail "Temporary preflight listener 8787 must be stopped before the final switch."
S4_LISTENER="$(listener "$PORT")"
[[ "$(printf '%s\n' "$S4_LISTENER" | sed '/^$/d' | wc -l | tr -d ' ')" == 1 ]] || fail "8786 must have exactly one verified S4 listener."
[[ "$S4_LISTENER" == *"127.0.0.1:$PORT"* ]] || fail "8786 is not loopback-only."
S4_PID="$(printf '%s\n' "$S4_LISTENER" | listener_pid)"
[[ -n "$S4_PID" && -r "/proc/$S4_PID/cmdline" && -r "/proc/$S4_PID/environ" ]] || fail "Cannot identify the current 8786 listener."
S4_ARGS="$(tr '\0' ' ' < "/proc/$S4_PID/cmdline")"
S4_ENV="$(tr '\0' '\n' < "/proc/$S4_PID/environ")"
[[ "$S4_ARGS" == *"--host 127.0.0.1"* && "$S4_ARGS" == *"--port $PORT"* ]] || fail "8786 process is not loopback S4."
if [[ "$S4_ARGS" == *"--app-dir $S4_FROZEN_APP_ROOT"* ]]; then
  [[ "$S4_ENV" == *"DASHBOARD_BUILD_COMMIT=$S4_BUILD"* ]] || fail "Frozen S4 process build mismatch."
  [[ "$(git -C "$S4_FROZEN_ROOT" rev-parse HEAD)" == "bf745129e4e7359db3631c18ee60da3e20ab74f2" ]] || fail "Frozen S4 source hash mismatch."
  EXPECTED_S4_BUILD="$S4_BUILD"
elif [[ "$S4_ARGS" == *"--app-dir $S4_E86_APP_ROOT"* ]]; then
  [[ "$S4_ENV" == *"DASHBOARD_BUILD_COMMIT=$S4_BUILD"* ]] || fail "S4 e86 process build mismatch."
  [[ "$(file_sha "$S4_E86_APP_ROOT/app/main.py")" == "$S4_MAIN_SHA" && "$(file_sha "$S4_E86_APP_ROOT/app/db_parts/core.py")" == "$S4_E86_CORE_SHA" ]] || fail "S4 e86 source files changed."
  EXPECTED_S4_BUILD="$S4_BUILD"
elif [[ "$S4_ARGS" == *"--app-dir $S4_FAB_APP_ROOT"* ]]; then
  [[ "$S4_ENV" == *"DASHBOARD_BUILD_COMMIT=$S4_FAB_BUILD"* ]] || fail "Current S4 process build mismatch."
  [[ "$(file_sha "$S4_FAB_APP_ROOT/app/main.py")" == "$S4_MAIN_SHA" && "$(file_sha "$S4_FAB_APP_ROOT/app/db_parts/core.py")" == "$S4_FAB_CORE_SHA" ]] || fail "Current S4 source files changed."
  EXPECTED_S4_BUILD="$S4_FAB_BUILD"
else
  fail "8786 process is not an allowlisted S4 source."
fi
[[ "$S4_ENV" == *"DASHBOARD_BASE_PATH=/manual-s4"* ]] || fail "S4 base-path identity mismatch."
S4_HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/health")"
printf '%s' "$S4_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s4"' "$EXPECTED_S4_BUILD" || fail "S4 health check failed; refusing the S5 switch."
S4_STATUS="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/status")"
printf '%s' "$S4_STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert int(d.get("database",{}).get("migration_count",0))==46; assert not d.get("batch_prediction_enabled"); assert not d.get("autotriage_push_enabled"); assert not (d.get("review_notifications",{}).get("enabled"))' || fail "S4 DB/writer state changed; refusing the S5 switch."
S4_SESSION="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s4/api/session")"
printf '%s' "$S4_SESSION" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only") is True and d.get("can_write") is False' || fail "S4 unauthenticated session is not read-only."

kill -TERM "$S4_PID"
for _ in $(seq 1 30); do
  if [[ -z "$(listener "$PORT")" ]]; then break; fi
  sleep 1
done
[[ -z "$(listener "$PORT")" ]] || fail "Verified S4 process did not release 8786."

install -d -m 700 "$(dirname "$S5_PID_FILE")"
nohup "$S5_LAUNCHER" </dev/null >/dev/null 2>&1 &
S5_PID=$!
printf '%s\n' "$S5_PID" > "$S5_PID_FILE"
chmod 600 "$S5_PID_FILE"
S5_HEALTH=
for _ in $(seq 1 60); do
  if S5_HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/manual-s5/health" 2>/dev/null)"; then break; fi
  sleep 1
done
[[ -n "$S5_HEALTH" ]] || fail "S5 did not become healthy; use the pinned S4 restore script."
printf '%s' "$S5_HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s5"' "$S5_APP_SHA" || fail "S5 build/base-path health mismatch."
S5_STATUS="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s5/api/status")"
printf '%s' "$S5_STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert int(d.get("database",{}).get("migration_count",0))==47; assert not d.get("batch_prediction_enabled"); assert not d.get("autotriage_push_enabled"); assert not (d.get("review_notifications",{}).get("enabled"))'
S5_SESSION="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/manual-s5/api/session")"
printf '%s' "$S5_SESSION" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only") is True and d.get("can_write") is False' || fail "Unauthenticated S5 session is not read-only."
printf 'S5 healthy on loopback 8786: %s\n' "$S5_APP_SHA"
