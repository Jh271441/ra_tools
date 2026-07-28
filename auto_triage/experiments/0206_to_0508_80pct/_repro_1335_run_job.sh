#!/bin/bash
# Reproduction of the 2026-07-23 paired-labelrefresh 1335 track (Qwen3.5-9B r16),
# plus the missing source-val forced-choice selection artifact.
#
# Differences from the original run (documented deviations):
#   1. Only the 1335 track is trained (the 1052 baseline is not repeated).
#   2. After training, every checkpoint is scored with the forced-choice
#      first-label-token scorer on the 0206-1335-v2 val split (132 rows) so a
#      checkpoint can be selected without reading any 0508 data.
#   3. The 0508 sweep uses the same frozen TE-priority v1 file as the original
#      for comparability; v2-relabel rescoring is done offline from the same
#      predictions (11-label diff).
# Everything else (config, data, trainer, eval script) is byte-identical.
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
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTORCH_ALLOC_CONF=expandable_segments:True

REMOTE_ROOT="/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen"
TRAINING_REPO="${REMOTE_ROOT}/stuck_auto_triage_vlm"
SRC_EXPERIMENT="${REMOTE_ROOT}/experiments/qwen35_9b_1335_1052_labelrefresh_20260723"
EXPERIMENT_ROOT="${REMOTE_ROOT}/experiments/qwen35_9b_1335_labelrefresh_repro_20260726"
CONFIG="${EXPERIMENT_ROOT}/config_qwen35_9b_r16.yaml"
D1335="${TRAINING_REPO}/data_release0206_1335_relabel_exclude7_v2"
RELEASE0508="/nfs/dataset-ofs-remote-assist-stuck/dataset/stuck_auto_triage_vlm_finetune_dataset/release20260508_1071_te_priority_v1/dataset/full.jsonl"
SCORER="${REMOTE_ROOT}/experiments/qwen35_9b_1335_label_focus_20260726/evaluate_triclass_forced_scores.py"
NUM_GPUS="${RESOURCE_NUM_GPU:-4}"
NAME="1335_relabel_repro_20260726"

if [ "${RA_EXPERIMENT_TEE_DONE:-0}" != "1" ]; then
  export RA_EXPERIMENT_TEE_DONE=1
  mkdir -p "${EXPERIMENT_ROOT}/logs"
  LOG_FILE="${EXPERIMENT_ROOT}/logs/repro_train_$(date +%Y%m%d_%H%M%S)_$$.log"
  echo "[log] tee stdout/stderr to ${LOG_FILE}"
  exec > >(tee -a "${LOG_FILE}") 2>&1
fi

# Frozen config copied verbatim from the original experiment at submit time.
test -f "${CONFIG}"
cmp -s "${CONFIG}" "${SRC_EXPERIMENT}/config_qwen35_9b_r16.yaml" \
  || { echo "[ERROR] config drifted from original" >&2; exit 1; }
test -d "${D1335}/dataset"
test -f "${RELEASE0508}"
test -f "${SCORER}"
test "${NUM_GPUS}" -ge 1
mkdir -p "${EXPERIMENT_ROOT}/models" "${EXPERIMENT_ROOT}/eval_0508" \
  "${EXPERIMENT_ROOT}/sourceval_forced_scores"

nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
cd "${TRAINING_REPO}"

OUTPUT_DIR="${EXPERIMENT_ROOT}/models/lora_qwen35_9b_${NAME}"
test ! -e "${OUTPUT_DIR}"

echo "[train] ${NAME}: ${D1335} -> ${OUTPUT_DIR}"
torchrun --standalone --nproc_per_node="${NUM_GPUS}" scripts/03_train.py \
  --config "${CONFIG}" \
  --train-data "${D1335}/dataset/train.jsonl" \
  --val-data "${D1335}/dataset/val.jsonl" \
  --output-dir "${OUTPUT_DIR}"

# --- source-val forced-choice sweep: the selection artifact the original lacks
shopt -s nullglob
checkpoints=("${OUTPUT_DIR}"/checkpoint-*)
shopt -u nullglob
IFS=$'\n' checkpoints=($(printf '%s\n' "${checkpoints[@]}" | sort -t- -k2 -n))
unset IFS
test "${#checkpoints[@]}" -ge 1

for checkpoint in "${checkpoints[@]}"; do
  ck=$(basename "${checkpoint}")
  out="${EXPERIMENT_ROOT}/sourceval_forced_scores/${ck}.csv"
  [ -e "${out}" ] && { echo "[val-sweep] ${ck}: exists, skip"; continue; }
  echo "[val-sweep] ${ck} on 0206-1335-v2 val (132)"
  python "${SCORER}" \
    --data "${D1335}/dataset/val.jsonl" \
    --model-path "${checkpoint}" \
    --base-model Qwen/Qwen3.5-9B \
    --output "${out}" \
    --expected-n 132
done

# --- 0508 OOD sweep (reporting only, identical to original protocol)
for checkpoint in "${checkpoints[@]}"; do
  ck=$(basename "${checkpoint}")
  result="${EXPERIMENT_ROOT}/eval_0508/${ck}.json"
  [ -f "${result}" ] && { echo "[0508-sweep] ${ck}: exists, skip"; continue; }
  echo "[0508-sweep] ${ck} on frozen TE-priority 0508"
  torchrun --standalone --nproc_per_node="${NUM_GPUS}" scripts/05_evaluate.py \
    --config "${CONFIG}" \
    --model-path "${checkpoint}" \
    --test-data "${RELEASE0508}" \
    --holdout-data /nonexistent_holdout.jsonl \
    --output "${result}"
done

echo "[done] repro training + source-val forced sweep + 0508 sweep completed"
