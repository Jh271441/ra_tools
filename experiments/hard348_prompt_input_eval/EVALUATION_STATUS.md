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
| `causal_compare_v1` frozen complete-source18 control (`paired10`, narrative facts, compact reports, short JSON) | 14/18 (A 66.7%, B 85.7%, C 80.0%) | not run | source gate not passed |
| `causal_effect_gate_v3` + recovery-only, compact facts (historical source9 diagnostic) | 8/9 | 6/12 | rejected |
| same candidate, complete source18 (`paired10`, observation v2) | 11/18 (A 66.7%, B 28.6%, C 100.0%) | not run | rejected |
| same candidate with narrative facts (source9 diagnostic) | 6/9 | not run | rejected |
| staged trigger/recovery + generic role gate (temporary wrapper) | 12/16 | 6/12 | rejected |

The complete source18 recovery-only check over-predicted C and recalled only
two of seven B cases. It is not a candidate for Fresh12 or further expansion.
The smaller narrative-facts result also recalled no A case, but is retained
only as a diagnostic receipt. Intermediate accuracy below the project target
is diagnostic only; it does not justify adding case-specific rules or leaking
labels into the prompt.

The staged role-gate reproduction also failed independently: it retained all
four A cases but recalled only one of four B cases and one of four C cases.
The source16 result was directional only because its image cache was a mixed
provenance diagnostic cache; it is not a formal source18 result. This
candidate is therefore closed without a Holdout36 or 0508/full1071 run.

The complete-source18 control above had 18/18 successful model responses after
the two previously missing source cases were supplied from the matching
label-free Camera/BEV cache. It did not reproduce the historical 16/18 result,
so it is recorded as a control receipt rather than an accepted candidate. No
Fresh12, Holdout36, or 0508/full1071 run is authorized from this result.

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
