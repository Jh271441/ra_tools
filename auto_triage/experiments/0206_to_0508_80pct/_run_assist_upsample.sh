#!/bin/bash
# Train one assistance-upsample variant on the 0206-only corpus, then score
# every checkpoint on the 0206 source-val split so the checkpoint (and the
# upsample factor itself) can be chosen without ever reading 0508.
#
# usage:  run_assist_upsample.sh <x3|x6|x10>
#
# Selection protocol, unchanged from the validated sourceval run:
#   1. forced-choice first-label-token scoring on 0206-1335-v2 val (132 rows)
#   2. one-standard-error rule over source-val macro-F1
#   3. 0508 is touched only after a checkpoint is frozen, for reporting
set -euo pipefail

if [ "${VLM_INIT_DONE:-0}" != "1" ]; then
  exec zsh -ic 'init_vlm >/dev/null 2>&1 && export VLM_INIT_DONE=1 && exec bash "$@"' init_vlm_runner "$0" "$@"
fi

variant="${1:?usage: $0 <x3|x6|x10>}"
case "$variant" in x3|x6|x10) ;; *) echo "[ERROR] bad variant: $variant" >&2; exit 2;; esac

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate vlm

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export RA_TOOLS_ENABLED=false
export TOKENIZERS_PARALLELISM=false
export FLA_TILELANG=0
export no_proxy='*'
export NO_PROXY='*'
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTORCH_ALLOC_CONF=expandable_segments:True

REMOTE_ROOT=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen
REPO="$REMOTE_ROOT/stuck_auto_triage_vlm"
EXP="$REMOTE_ROOT/experiments/qwen35_9b_1335_assist_upsample_20260726"
DATA="$EXP/data_assist_$variant/dataset"
CONFIG="$EXP/config_qwen35_9b_r16_upsample.yaml"
SCORER="$REMOTE_ROOT/experiments/qwen35_9b_1335_label_focus_20260726/evaluate_triclass_forced_scores.py"
OUT="$EXP/models/$variant"
VALSCORES="$EXP/sourceval_forced/$variant"
NUM_GPUS="${RESOURCE_NUM_GPU:-${NUM_GPUS:-1}}"

for p in "$REPO" "$DATA/train.jsonl" "$DATA/val.jsonl" "$CONFIG" "$SCORER"; do
  test -e "$p" || { echo "[ERROR] missing $p" >&2; exit 2; }
done
if [ -e "$OUT" ]; then echo "[ERROR] output exists, refusing overwrite: $OUT" >&2; exit 2; fi
mkdir -p "$EXP/logs" "$VALSCORES"

LOG="$EXP/logs/${variant}_$(date +%Y%m%d_%H%M%S)_$$.log"
echo "[log] $LOG"
exec > >(tee -a "$LOG") 2>&1

nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
cd "$REPO"

echo "[train] $variant -> $OUT  (gpus=$NUM_GPUS)"
torchrun --standalone --nproc_per_node="$NUM_GPUS" scripts/03_train.py \
  --config "$CONFIG" \
  --train-data "$DATA/train.jsonl" \
  --val-data "$DATA/val.jsonl" \
  --output-dir "$OUT"

shopt -s nullglob
cks=("$OUT"/checkpoint-*)
shopt -u nullglob
IFS=$'\n' cks=($(printf '%s\n' "${cks[@]}" | sort -t- -k2 -n)); unset IFS
test "${#cks[@]}" -ge 1

for ck in "${cks[@]}"; do
  name=$(basename "$ck")
  csv="$VALSCORES/$name.csv"
  [ -e "$csv" ] && { echo "[val] $name exists, skip"; continue; }
  echo "[val] scoring $name on 0206 source-val (132)"
  python "$SCORER" \
    --data "$DATA/val.jsonl" \
    --model-path "$ck" \
    --base-model Qwen/Qwen3.5-9B \
    --output "$csv" \
    --expected-n 132
done

echo "[done] $variant trained and source-val scored."
echo "[next] run the 1-SE selector over $VALSCORES, freeze one checkpoint,"
echo "       then score it once on release0508_v2 for reporting."
