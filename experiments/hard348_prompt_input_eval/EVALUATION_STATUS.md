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
| `causal_effect_gate_v3` complete source18 (`paired10`, narrative facts, compact reports, short JSON) | 14/18 (A 66.7%, B 71.4%, C 100.0%) | not run | rejected; B→C shift |
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

The complete-source18 `causal_effect_gate_v3` reproduction also scored 14/18,
but changed two B cases to C and recalled only five of seven B cases. Its
perfect C recall is a class-distribution shift, not a stable gain; it is closed
without a Fresh12, Holdout36, or 0508/full1071 run.

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

## Subsequent frozen source18 diagnostics (2026-08-20)

The following input-only diagnostics reused the complete source18 artifact,
score receipt, image cache, Qwen3.8-27B thinking-off, `causal_compare_v1`,
narrative facts, compact reports, `paired10` unless noted, and short JSON. They
were not used to select a new prompt or to change any label:

| Input change | Result | Decision |
| --- | ---: | --- |
| Full post-trigger visual sequence (`paired18`) | 14/18 (A 66.7%, B 85.7%, C 80.0%) | no net gain; reject |
| Camera-only (`camera5`) | 11/18 (A 50.0%, B 85.7%, C 40.0%) | reject |
| Dense full raw time ledger | 14/18 (A 83.3%, B 85.7%, C 60.0%) | FIX/HARM balance; reject |
| Dense pre-trigger ledger only | 13/18 (A 50.0%, B 85.7%, C 80.0%) | reject |
| Same-model two-pass causal worksheet, with fail-closed worksheet parser | 11/16 completed; 2 cases failed parsing | reject |

The dense ledger fixed some trigger-role errors but caused compensating
normal-wait versus no-assistance errors. The two-pass worksheet also showed
that an intermediate causal state can anchor the final model to a wrong
normal-mechanism hypothesis; it is not accepted for Fresh12. Manual review of
representative source cases found unresolved evidence/GT tension (for example,
a visible signal/queue case scored as A, and a single-lead/temporary-stop case
scored as C) as well as a clean background-construction-versus-current-corridor
distinction. These observations are diagnostic only and do not authorize GT
changes or case-specific prompt rules.

## Additional frozen source18 diagnostics (2026-08-20)

The same frozen `causal_compare_v1` configuration was rerun in a separate
output directory and again scored 14/18 with the same four predicted cases as
the prior control. This makes the observed source result stable at the label
level rather than a one-run decode fluctuation.

The following single-hypothesis checks were then run against the same raw
evidence, reports, images, model, and external score receipt. None was
promoted:

| Hypothesis | Result | Decision |
| --- | ---: | --- |
| `causal_compare_v1` + full `effect_gate_v3` rules | 10/18 (A 16.7%, B 85.7%, C 60.0%) | rejected; long-rule composition collapsed A |
| `causal_compare_v1` with label-only JSON output | 13/18 (A 66.7%, B 85.7%, C 60.0%) | rejected; output rationale was not the bottleneck |
| compact prompt rewritten as plain Chinese business prose | 12/18 (A 33.3%, B 71.4%, C 100.0%) | rejected; C/normal boundary remained unstable |
| narrow trigger-state lock on the effect gate | 10/18 (A 16.7%, B 85.7%, C 60.0%) | rejected; normal-mechanism overgeneralization |
| `effect_gate_v3` with `observation_v1` report projection | 10/18 (A 16.7%, B 100.0%, C 40.0%) | rejected |
| `causal_compare_v1` without Trigger/Recovery reports | 8/18 (A 16.7%, B 85.7%, C 20.0%) | rejected; reports carry useful role/timing evidence |

The failures are consistent with a business-state conflict, not a missing
label parser: prompting the model more strongly toward normal traffic removes
real-stuck A/C cases, while prompting more strongly toward release timing
turns normal B waits into C. The current evidence also contains source cases
where the visual/observer normal-mechanism explanation conflicts with the
external score receipt. No prompt may resolve that by importing GT or adding a
case-specific exception.

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
