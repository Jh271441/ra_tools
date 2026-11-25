#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=8786
PROD_PORT=8785
PROD_EXPECTED_PID=10634
PROD_EXPECTED_BUILD=5fdc41ba8b0215170a8307237762e1ed50a9aaf2
UX_ROOT="${UX_EXPERIMENT_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922}"
S6_ROOT="${S6_RESTORE_ROOT:-/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_s6_v2_legacy_cutover_20260922}"
S6_SHA="${S6_RESTORE_SHA:-c78aa6cedc90095639edea29e5fd4959ca3859a3}"
S6_LAUNCHER="$S6_ROOT/source-$S6_SHA/ra_triage_dashboard/scripts/run_s6_smoke.sh"

fail() { printf '%s\n' "$1" >&2; exit 1; }
listener() { ss -H -ltnp "sport = :$1"; }

[[ -x "$S6_LAUNCHER" ]] || fail "Frozen S6 v2 launcher is unavailable."
PROD="$(listener "$PROD_PORT")"
[[ "$PROD" == *"0.0.0.0:$PROD_PORT"* && "$PROD" == *"pid=$PROD_EXPECTED_PID,"* ]] || fail "Production identity changed."
curl -fsS "http://127.0.0.1:$PROD_PORT/health" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("build_commit")==sys.argv[1]' "$PROD_EXPECTED_BUILD" || fail "Production build changed."
CURRENT="$(listener "$PORT")"
[[ "$CURRENT" == *"127.0.0.1:$PORT"* ]] || fail "8786 is not the loopback experiment listener."
PID="$(printf '%s\n' "$CURRENT" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p')"
[[ -r "/proc/$PID/cmdline" ]] || fail "Cannot identify the UX listener."
ARGS="$(tr '\0' ' ' < "/proc/$PID/cmdline")"
[[ "$ARGS" == *"$UX_ROOT/"* ]] || fail "8786 is not owned by the UX smoke root."
kill -TERM "$PID"
for _ in $(seq 1 30); do [[ -z "$(listener "$PORT")" ]] && break; sleep 1; done
[[ -z "$(listener "$PORT")" ]] || fail "UX listener did not stop."
printf '%s\n' "$S6_SHA" > "$S6_ROOT/config/source_sha"
chmod 600 "$S6_ROOT/config/source_sha"
S6_EXPERIMENT_ROOT="$S6_ROOT" S6_SMOKE_PORT="$PORT" nohup "$S6_LAUNCHER" </dev/null >/dev/null 2>&1 &
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/manual-s6/health" >/tmp/restore-s6-health.json 2>/dev/null; then break; fi
  sleep 1
done
python3 -c 'import json,sys; d=json.load(open(sys.argv[2], encoding="utf-8")); assert d.get("ok") is True; assert d.get("build_commit")==sys.argv[1]; assert d.get("base_path")=="/manual-s6"' "$S6_SHA" /tmp/restore-s6-health.json
printf 'S6 v2 restored on loopback 8786: %s\n' "$S6_SHA"
