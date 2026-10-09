#!/usr/bin/env bash
set -euo pipefail
umask 077
PORT=8786
PROD_PORT=8785
PROD_EXPECTED_PID=10634
PROD_EXPECTED_BUILD=5fdc41ba8b0215170a8307237762e1ed50a9aaf2
S6_ROOT="${S6_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s6_legacy_cutover_20260922}"
S6_SHA_FILE="$S6_ROOT/config/source_sha"
S6_PID_FILE="$S6_ROOT/runtime/s6.pid"
fail(){ echo "$1" >&2; exit 1; }
listener(){ ss -H -ltnp "sport = :$1"; }
[[ -d "$S6_ROOT" && "$(stat -c '%a' "$S6_ROOT")" == 700 ]] || fail "S6 root unavailable"
SHA=$(cat "$S6_SHA_FILE"); [[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || fail "invalid S6 SHA"
APP_ROOT="$S6_ROOT/source-$SHA/ra_triage_dashboard"; LAUNCHER="$APP_ROOT/scripts/run_s6_smoke.sh"
[[ -x "$LAUNCHER" ]] || fail "S6 launcher unavailable"
PROD=$(listener "$PROD_PORT"); [[ "$PROD" == *"0.0.0.0:$PROD_PORT"* && "$PROD" == *"pid=$PROD_EXPECTED_PID,"* ]] || fail "production identity changed"
curl -fsS http://127.0.0.1:$PROD_PORT/health | python3 -c 'import json,sys; assert json.load(sys.stdin).get("build_commit")==sys.argv[1]' "$PROD_EXPECTED_BUILD" || fail "production build changed"
[[ -z "$(listener 8787)" ]] || fail "temporary port occupied"
CURRENT=$(listener "$PORT"); [[ "$CURRENT" == *"127.0.0.1:$PORT"* ]] || fail "8786 is not loopback"
PID=$(printf '%s\n' "$CURRENT" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p'); [[ -r /proc/$PID/cmdline ]] || fail "unknown 8786 process"
kill -TERM "$PID"; for _ in $(seq 1 30); do [[ -z "$(listener "$PORT")" ]] && break; sleep 1; done; [[ -z "$(listener "$PORT")" ]] || fail "old 8786 did not stop"
nohup "$LAUNCHER" </dev/null >/dev/null 2>&1 & NEWPID=$!; printf '%s\n' "$NEWPID" > "$S6_PID_FILE"; chmod 600 "$S6_PID_FILE"
HEALTH=""; for _ in $(seq 1 60); do HEALTH=$(curl -fsS --max-time 2 http://127.0.0.1:$PORT/manual-s6/health 2>/dev/null || true); [[ -n "$HEALTH" ]] && break; sleep 1; done
printf '%s' "$HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("build_commit")==sys.argv[1] and d.get("base_path")=="/manual-s6"' "$SHA" || fail "S6 health failed"
curl -fsS http://127.0.0.1:$PORT/manual-s6/api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); assert int(d.get("database",{}).get("migration_count",0))==50; assert not d.get("batch_prediction_enabled"); assert not d.get("autotriage_push_enabled"); assert not d.get("review_notifications",{}).get("enabled")' || fail "S6 status gate failed"
curl -fsS http://127.0.0.1:$PORT/manual-s6/api/session | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("read_only") is True and d.get("can_write") is False' || fail "S6 session gate failed"
echo "S6 healthy on loopback 8786: $SHA"
