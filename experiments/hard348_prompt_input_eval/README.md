# Hard-348 prompt/input evaluation

This directory is an evaluation-only, model-only experiment for RA Stuck ABC
triage. It changes only the prompt and the evidence projection sent to a
base VLM; it does not train adapters and does not modify the production
dashboard or triage contract.

The runner is deliberately fail-closed:

- the model receives facts, non-authoritative label-free reports, and the
  selected Camera/BEV images only;
- the input guard rejects prior model summaries or scored artifacts (for
  example `stats`, `model_yaml`, `parsed`, or `raw_response`) instead of
  treating them as raw evidence;
- expected labels are used only by the outer scorer, never by the model
  request;
- Contract logic, threshold-to-label mapping, case-specific rules, and GT or
  issue identifiers in the model input are prohibited;
- raw evidence artifacts, image caches, model responses, credentials, and
  metrics are runtime inputs/outputs and are not committed here;
- existing output files are never overwritten.

The image resolver accepts either `root/<issue_id>/0.jpg` plus `bev_0.jpg`
(the Fresh12 cache layout) or `root/<issue_id>_*/after_compress/` (the source
cache layout). It still requires exactly one matching directory and every
selected frame file.

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
  --score-receipt <external-gt-receipt.json> \
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
within the same comparison. `--score-receipt` is read only after the child
probe returns and is never passed to the model; use it when the raw evidence
artifact is deliberately label-free. Its rows must contain `issue_id` and
`expected_label_for_scoring_only` (or `gt`) and are used only for scoring.

## Candidate: role-first observation firewall

`causal_role_first_v1` with `observation_v1` is a single source-only
hypothesis, not a frozen result. It separates the trigger-time traffic-role
ledger from the post-trigger recovery ledger and removes observer state,
confidence, and prose conclusions that can cause recovery evidence to
override the trigger decision. Evaluate it on the declared source subset
first, then repeat the exact configuration on an independently frozen Fresh
set. Do not change its wording or input after inspecting Fresh results.

`causal_role_first_v2` is a separate source-only candidate. It adds only a
generic direct-cause check: background traffic is not automatically the cause
of Ego's stop, and a visible signal counts only when it applies to the current
intended maneuver. It must be evaluated and gated independently; do not mix
v1/v2 results or select between them using Fresh or Holdout.

`causal_role_first_v3` is a third source-only candidate paired with
`observation_v2`. It adds only the label-free `strongest_counter_evidence`
time/identity observation and a generic T/R conflict reconciliation; release
time alone is explicitly not a C rule.

Use these options with the batch command above:

```text
--report-mode observation_v1
--prompt-variant causal_role_first_v1
```

For the v2 candidate, change only the prompt variant:

```text
--report-mode observation_v1
--prompt-variant causal_role_first_v2
```

For the v3 candidate, use:

```text
--report-mode observation_v2
--prompt-variant causal_role_first_v3
```

`PROMPT_SPEC.md` records the business-state causal definitions used by the
current indexed prompt. `project_role_observer_facts.py` is an optional
label-free projection helper; it removes observer conclusions and retains
only auditable role, corridor, cross-frame, conflict, and visibility facts.

Run the local package checks before committing:

```bash
python3 experiments/hard348_prompt_input_eval/validate_package.py
```
