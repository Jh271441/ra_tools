# Evaluation status

Updated 2026-08-20. This is a run-status record for the source package; raw
evidence, images, model responses, score receipts, and summaries remain
outside Git.

## Scope

The package is evaluation-only and model-only. It changes the evidence
projection and prompt sent to Qwen3.8-27B or Qwen3-VL-Plus. It does not train a
model, modify production triage logic, use a deterministic Contract, map a
threshold to a label, or use GT/issue information in the model request.

## Current decision

No prompt/input candidate is accepted for Hard-348 or 0508 full1071. A
candidate must first pass a source-only gate and reproduce on the exact
independent Fresh12 set before it can be evaluated on Holdout36 or a larger
set. The currently available candidates have not met that gate.

Representative results, all scored externally and not fed back into the
model input:

| Configuration | Source result | Fresh12 result | Decision |
| --- | ---: | ---: | --- |
| `causal_compare_v1` historical baseline | 16/18 | 8/12 | not stable |
| `causal_effect_gate_v3` + recovery-only, compact facts | 8/9 | 6/12 | rejected |
| same candidate with narrative facts (latest source check) | 6/9 | not run | rejected |

The latest source check predicted no A cases correctly, so it is not a
candidate for further expansion. Intermediate accuracy below the project
target is diagnostic only; it does not justify adding case-specific rules or
leaking labels into the prompt.

## Evaluation gates

1. Freeze one prompt, evidence projection, image selection, and model.
2. Run the declared source-only representative subset.
3. Reproduce the exact configuration on Fresh12 without changing wording or
   inputs.
4. Only a stable candidate may proceed to Holdout36, then Hard-348/full1071.

The 0508 full1071 run is not represented by this package unless a valid,
original, label-free evidence artifact and complete frozen image cache pass
the batch coverage checks. Existing summaries or prior model outputs are not
valid replacements for that artifact.

## Repository policy

Keep runtime outputs and caches in a unique directory outside Git. Run
`python3 -B experiments/hard348_prompt_input_eval/validate_package.py` before
committing. This experiment package belongs on
`experiment/ra-auto-triage`; it does not require a merge to `master` because
it is not a production behavior change.
