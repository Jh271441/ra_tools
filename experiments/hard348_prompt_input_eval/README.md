# Hard-348 prompt/input evaluation

This directory is an evaluation-only, model-only experiment for RA Stuck ABC
triage. It changes only the prompt and the evidence projection sent to a
base VLM; it does not train adapters and does not modify the production
dashboard or triage contract.

The runner is deliberately fail-closed:

- the model receives facts, non-authoritative label-free reports, and the
  selected Camera/BEV images only;
- expected labels are used only by the outer scorer, never by the model
  request;
- Contract logic, threshold-to-label mapping, case-specific rules, and GT or
  issue identifiers in the model input are prohibited;
- raw evidence artifacts, image caches, model responses, credentials, and
  metrics are runtime inputs/outputs and are not committed here;
- existing output files are never overwritten.

## Frozen evaluation configuration

The default comparable configuration is:

```text
model: Qwen3.8-27B/Qwen3.8-27B
visual: paired10
facts: narrative
reports: compact
prompt: causal_compare_v1
output: short
text layout: before_images
thinking: disabled
```

The same code can target Qwen3-VL-Plus by changing only `--model`; do not
change the evidence, images, or prompt settings within a comparison.

## Run one case

Set the gateway key outside the repository:

```bash
export RA_TRIAGE_GATEWAY_APIKEY='...'
```

Then provide an original evidence artifact, not a previous summary:

```bash
python3 experiments/hard348_prompt_input_eval/compact_business_probe.py \
  --artifact <raw-evidence.json> \
  --issue-id <issue-id> \
  --image-cache-root <frozen-image-root> \
  --output <new-output-dir>/<issue-id>.json \
  --endpoint <openai-compatible-chat-endpoint> \
  --model Qwen3.8-27B/Qwen3.8-27B \
  --max-tokens 64 \
  --visual-mode paired10 \
  --facts-mode narrative \
  --output-mode short \
  --report-mode compact \
  --prompt-variant causal_compare_v1 \
  --text-layout before_images
```

## Run an evaluation batch

The batch runner validates raw-evidence coverage, retries a missing-output
case with the exact same configuration once, and writes a separate case
directory plus summary. Use `--expected-count 1071` for the full 0508 set or
`--expected-count 348` for Hard-348.

```bash
python3 experiments/hard348_prompt_input_eval/compact_business_batch.py \
  --probe experiments/hard348_prompt_input_eval/compact_business_probe.py \
  --artifact <raw-evidence.json> \
  --trigger-artifact <label-free-trigger.json> \
  --recovery-artifact <label-free-recovery.json> \
  --image-cache-root <frozen-image-root> \
  --out-dir <new-run-dir>/cases \
  --summary <new-run-dir>/summary.json \
  --expected-count 1071 \
  --max-tokens 64 \
  --timeout 300 \
  --visual-mode paired10 \
  --facts-mode narrative \
  --output-mode short \
  --report-mode compact \
  --prompt-variant causal_compare_v1 \
  --text-layout before_images \
  --endpoint <openai-compatible-chat-endpoint> \
  --model Qwen3.8-27B/Qwen3.8-27B
```

The batch scorer is an external diagnostic only. It does not alter model
labels or apply a deterministic ABC rule. Keep all run directories outside
Git and do not use evaluation results to change the frozen prompt/input
within the same comparison.

`PROMPT_SPEC.md` records the business-state causal definitions used by the
current indexed prompt. `project_role_observer_facts.py` is an optional
label-free projection helper; it removes observer conclusions and retains
only auditable role, corridor, cross-frame, conflict, and visibility facts.

Run the local package checks before committing:

```bash
python3 experiments/hard348_prompt_input_eval/validate_package.py
```
