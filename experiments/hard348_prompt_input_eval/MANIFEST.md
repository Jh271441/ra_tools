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

## Deliberately excluded

The following remain runtime inputs/outputs or historical scratch material,
not source files for this package:

- `artifacts/`, image caches, raw model responses, and summary JSON;
- GT/label receipts, holdout data, and issue-specific result tables;
- API keys, account state, and local gateway configuration;
- the dozens of historical F2/fusion wrappers and `/tmp`-dependent shims;
- training/LoRA code, checkpoints, and the previous hierarchical two-stage
  training experiment;
- deterministic Contract logic, threshold mappings, and per-case overrides.

The package intentionally has no dependency on a file under `/tmp`; all
runtime paths are explicit command-line arguments.
