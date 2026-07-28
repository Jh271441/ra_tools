#!/bin/bash
# One-shot driver: pull the refreshed Axe cookie from cloud_server, verify the
# API works, then DRY-RUN the three assist-upsample submissions.
# Deliberately stops before --execute: the execute step is run separately after
# the dry-run payloads and the current job list have been reviewed.
set -uo pipefail

export no_proxy='*' NO_PROXY='*'
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY 2>/dev/null

echo "== 1. fetch refreshed cookie from cloud_server =="
FOUND=""
for p in /volume/home/.axe_cookie '~/.axe_cookie' /tmp/axe_cookie.txt; do
  if ssh -o ConnectTimeout=20 cloud_server "test -s $p" 2>/dev/null; then
    FOUND="$p"
    echo "   found: $p"
    break
  fi
done
if [ -z "$FOUND" ]; then
  echo "   ERROR: no cookie file found on cloud_server" >&2
  exit 1
fi
scp -q -o ConnectTimeout=20 "cloud_server:$FOUND" /home/didi/.axe_cookie
chmod 600 /home/didi/.axe_cookie
echo "   installed -> /home/didi/.axe_cookie ($(stat -c%s /home/didi/.axe_cookie) bytes, mode 600)"

echo
echo "== 2. verify API =="
python3 /home/didi/.claude/skills/ra-triage/scripts/axe_status.py --page-size 15 || {
  echo "   ERROR: axe_status failed - cookie still not valid" >&2
  exit 1
}

echo
echo "== 3. dry-run payloads (NOT submitted) =="
SCRIPT=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/qwen35_9b_1335_assist_upsample_20260726/run_assist_upsample.sh
for v in x6 x3 x10; do
  echo "---- variant $v ----"
  python3 /home/didi/.claude/skills/ra-triage/scripts/axe_submit_h20_3e.py \
    --name "assist-upsample-$v-20260726" \
    --description "0206-only assist-pattern upsample $v; r16 recipe; sourceval 1-SE selection" \
    --resource h20-3e-4 \
    --script-path "$SCRIPT" \
    --script-param "$v" | tail -5
done

echo
echo "== done. review job list + payloads above, then submit with --execute =="
