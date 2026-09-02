# RA reproduction validation: gen4-release-20260724

Date: 2026-08-29 (Asia/Shanghai)

## Scope

- Release: `gen4-release-20260724`
- Binary: `1743401`
- Manifest: `/tmp/ra_repro_20260828_sample50.csv`
- Balanced cohorts: 50 `positive_auto`, 50 `negative_auto`, 50 `positive_manual`
- Orion jobs: `45142551`, `45167929`, `45172265`
- Trigger metric: `dpe_assist_channel_triggered__group1 >= 1`

`negative_auto` means a road false-trigger dataset. Its historical road behavior
still expects a simulation trigger, while its business truth is negative.

## Final coverage and quality gates

| Check | Result |
|---|---:|
| Manifest scenarios | 150 |
| Terminal and completed scenarios | 150 / 150 |
| DPE-covered scenarios | 150 / 150 |
| Terminal failures | 0 |
| Simulator cache hits in selected results | 0 |
| Missing simulator-cache fields | 0 |
| Missing inference logs | 0 |
| Missing DPE outputs | 0 |
| Missing output bags | 0 |
| Failed evaluations | 0 |
| Cross-job trigger conflicts | 0 |

The parallel duplicate jobs produced six cached results, but all six scenarios
also had fresh, complete results from the original job. Final selection prefers
fresh results; no cached result contributes to the metrics below.

## Historical road-behavior reproduction

| Cohort | Expected simulation behavior | Match | Rate |
|---|---|---:|---:|
| `positive_auto` | Trigger | 39 / 50 | 78.00% |
| `negative_auto` | Trigger | 31 / 50 | 62.00% |
| `positive_manual` | No automatic trigger | 39 / 50 | 78.00% |
| Overall | Cohort-specific behavior | 109 / 150 | 72.67% |

## Business-truth metrics

Truth-positive cohorts are `positive_auto` and `positive_manual`.
`negative_auto` is truth-negative even though its historical road behavior was
an automatic false trigger.

| Item | Result |
|---|---:|
| TP | 50 |
| FN | 50 |
| FP | 31 |
| TN | 19 |
| Precision | 61.73% |
| Recall | 50.00% |
| Specificity | 38.00% |
| Accuracy | 46.00% |

## Full-run decision

**GO for full per-version simulation as a data-collection/evaluation run, with
guardrails.** The Orion/DPE pipeline passed the 150-case validation: concurrency
20 ran successfully, all scenarios reached terminal state, DPE coverage was
complete, and duplicate executions had zero trigger conflicts.

This is not an algorithm-quality approval. The 62.00% historical reproduction
for `negative_auto` and 46.00% truth accuracy show that full runs are needed to
measure the release-level behavior; they do not justify claiming high RA model
accuracy.

Required full-run guardrails:

1. Use every successfully converted scenario for each release; do not retain
   the 150-case validation cap.
2. Use controlled concurrency 20 initially and monitor actual RUNNING count.
3. Set simulator cache to `disabled` for fresh evaluation.
4. Record conversion/bag losses before launch and report the denominator after
   exclusions.
5. Require terminal completion, DPE coverage, output bags, inference logs, zero
   failed evaluations, and zero unresolved cross-job trigger conflicts before
   publishing a release metric.
6. Report historical road-behavior reproduction separately from business-truth
   precision/recall/specificity/accuracy.

## Reproduction command

```bash
ORION_CURRENT_REGION=CN \
ORION_DB_BASE_URL=http://10.82.129.7:8000 \
python3 scripts/ra_repro_validate_orion.py \
  --job-id 45142551 \
  --job-id 45167929 \
  --job-id 45172265 \
  --manifest /tmp/ra_repro_20260828_sample50.csv \
  --release 20260724
```
