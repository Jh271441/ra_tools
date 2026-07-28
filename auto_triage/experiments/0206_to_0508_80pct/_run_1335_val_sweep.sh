#!/bin/bash
# Forced-choice score every 1335-labelrefresh checkpoint on the 0206-1335-v2
# source val split (132 rows). Produces the missing source-val selection
# artifact so a checkpoint can be chosen without touching 0508.
# GPU 1 only (GPU 0 holds the resident vLLM servers).
set -euo pipefail

if [ "${VLM_INIT_DONE:-0}" != "1" ]; then
  exec zsh -ic 'init_vlm >/dev/null 2>&1 && export VLM_INIT_DONE=1 && exec bash "$@"' init_vlm_runner "$0" "$@"
fi

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
export CUDA_VISIBLE_DEVICES=1

EXP=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/qwen35_9b_1335_1052_labelrefresh_20260723
MODELS="$EXP/models/lora_qwen35_9b_1335_relabel_labelrefresh_20260723"
DATA=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/stuck_auto_triage_vlm/data_release0206_1335_relabel_exclude7_v2/dataset/val.jsonl
SCORER=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/qwen35_9b_1335_label_focus_20260726/evaluate_triclass_forced_scores.py
OUT="$EXP/sourceval_forced_scores_20260726"
mkdir -p "$OUT" "$EXP/logs"

for step in 70 100 110 120 130 140 150 160 170 180 190 200 204; do
  model="$MODELS/checkpoint-$step"
  csv="$OUT/checkpoint-$step.csv"
  [ -d "$model" ] || { echo "[skip] no $model"; continue; }
  [ -e "$csv" ] && { echo "[skip] exists $csv"; continue; }
  echo "[score] checkpoint-$step"
  python "$SCORER" \
    --data "$DATA" \
    --model-path "$model" \
    --base-model Qwen/Qwen3.5-9B \
    --output "$csv" \
    --expected-n 132
done
echo "[done] all requested checkpoints scored"
