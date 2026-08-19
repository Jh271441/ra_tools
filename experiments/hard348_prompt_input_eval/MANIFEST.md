# Package manifest

## Included

| File | Role |
| --- | --- |
| `compact_business_probe.py` | Self-contained one-case multimodal prompt/input runner. |
| `compact_business_batch.py` | Sequential evaluation runner with raw-artifact coverage checks and same-config retry. |
| `project_role_observer_facts.py` | Optional label-free observer projection. |
| `PROMPT_SPEC.md` | Human-readable business-state prompt specification. |
| `validate_package.py` | Static and prompt-safety checks; it never calls a model. |
| `README.md` | Scope, constraints, and reproducible commands. |

The currently proposed candidates are the pairs
`causal_role_first_v1` + `observation_v1` and
`causal_role_first_v2` + `observation_v1`, plus
`causal_role_first_v3` + `observation_v2`. They are prompt/input hypotheses
awaiting independent source-only and Fresh validation; neither is a selected
model configuration. v2 only adds generic direct-cause isolation between
background traffic and the current maneuver; it is not a case-specific rule.

## Deliberately excluded

The following remain runtime inputs/outputs or historical scratch material,
not source files for this package:

- `artifacts/`, image caches, raw model responses, and summary JSON;
- GT/label receipts, holdout data, and issue-specific result tables;
- API keys, account state, and local gateway configuration;
- report prose that contains label/GT markers or issue identifiers is rejected
  by the runtime safety guard;
- the dozens of historical F2/fusion wrappers and `/tmp`-dependent shims;
- training/LoRA code, checkpoints, and the previous hierarchical two-stage
  training experiment;
- deterministic Contract logic, threshold mappings, and per-case overrides.

The package intentionally has no dependency on a file under `/tmp`; all
runtime paths are explicit command-line arguments.
