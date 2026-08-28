#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-http://127.0.0.1:8790}"

curl --fail --silent --show-error "${base_url}/health"
echo
curl --fail --silent --show-error \
  --request POST \
  "${base_url}/dchat/smoke"
echo
