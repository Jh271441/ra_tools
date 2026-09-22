# Manual S6 Legacy Cutover smoke report

Recorded: 2026-09-22 (Asia/Shanghai)

## Final runtime

- Branch: `codex/legacy-cutover-s6`
- Final pushed source: `c48835e9692c3b86757769fd82a7d8ed70d0e6ab`
- S6 service: `127.0.0.1:8786/manual-s6`
- S6 database: `manual_s6_smoke_20260922_legacycutover`
- S6 database migration count: 50
- Final health: `ok=true`, exact build `c48835e9692c3b86757769fd82a7d8ed70d0e6ab`, base path `/manual-s6`.
- S6 status: PostgreSQL, `persistent_data=false`; Batch, AutoTriage push and D-Chat notifications disabled.
- Anonymous session: `read_only=true`, `can_write=false`.
- Production remained untouched on 8785, PID 10634, build
  `5fdc41ba8b0215170a8307237762e1ed50a9aaf2`, base path `/manual`.

S6 was rebuilt from the S5 smoke-v3 logical state. S5 v3 remains retained as
`manual_s5_smoke_v3_20260922`; S3/S4/S5 databases were not modified.

## Inventory and mapping

The read-only S6 inventory covered five scopes:

| Scope | Legacy annotations | Issues represented |
| --- | ---: | ---: |
| 0206 | 50 | 39 |
| 0508 | 45 | 29 |
| 0522 | 1 | 1 |
| 0626 | 12 | 8 |
| 0821 | 103 | 52 |

Inventory SHA: `c7dc63fd4d250cbeedbbfe6916df15110f1fbf5a97a09e65f62edcdea6aad062`.

Append-only classification apply produced:

| Classification | Count | Treatment |
| --- | ---: | --- |
| `label_history_mapped` | 15 | Canonical Label history target when a source label revision exists. |
| `legacy_mixed` | 196 | Kept as historical evidence; model Run plus label/tag/exclusion/note axes are not automatically split. |
| `model_review_mapped` | 0 | No determinate pure model-review-only rows in this fixture; all such rows carried mixed legacy axes. |
| `legacy_task_history` | 0 | No pure task-only row in this fixture. |
| `legacy_unbound_history` | 0 | No empty-axis row in this fixture. |

Classification rows are keyed by source annotation ID and policy version. Re-running
the apply is idempotent; source annotations, comments and attachments are unchanged.

## Read policy and shadow

All five scopes have `legacy-cutover-v1` policies. Final policy is `shadow` for
each scope. The 0522 scope was explicitly switched `shadow → canonical → shadow`
using epochs 1, 2 and 3; rollback only changed the policy row and retained all
classification/history rows.

Five append-only gallery shadow receipts were recorded. Each is
`expected_diff`, with `legacy_mixed`, `legacy_unbound_history` and
`legacy_task_history` as the allowed difference kinds. No raw total-only comparison
was accepted; each receipt carries source inventory SHA and bounded Issue-level diff
evidence. Examples include 0508: legacy 45 / canonical 1 / expected diff 44, and
0206: legacy 50 / canonical 13 / expected diff 37.

## Canonical read and compatibility checks

- Canonical Issue projection combines Issue, S1 shared Label state, exact selected
  Run prediction and exact Model Review head by Run/Campaign/reference/reviewer.
  It does not use unbound or prior-Run annotation fallback.
- `GET /api/legacy/{kind}/{id}` resolves legacy annotation/comment/task evidence
  without rewriting it and returns the canonical target/projection where available.
- `GET /api/issues/{issue_id}/canonical-projection` returns exact shared label and
  exact Model Review context.
- Legacy annotations returned in Case history carry `legacy_read_only` and
  classification metadata; the UI labels them “历史 Review（只读）” and disables
  delete for those rows.
- `/api/status` exposes the five scope read policies and epochs.
- Exclusion projection is bulk per scope and marks pending/conflict/stale Label
  states non-writable; legacy exclusion is retained as historical evidence.
  The 0206 smoke projection returned 133 Issues and no writable conflict rows.

## S5 evaluation compatibility and performance

Final S6 acceptance token: `6abf7e2ce3`.

- 4,039 synthetic acceptance Issues across 5 scopes and 8 Runs.
- Workset: `run-evaluation-workset-82d3f8d2b4664fe1b933ca9334fe2d44`.
- Evaluation: `evaluation-49330832-5c0e-43ec-9cf9-b271bfd00c12`.
- Five GT snapshot IDs were frozen and recorded in the Evaluation reference.
- Compact page (50 Issues × 8 Runs): 105,729 bytes.
- Full export: 7,375,509 bytes, 4,039 items.
- Same frozen content reused the same Evaluation ID.
- Shared Labeling Campaign: `campaign-863a8dcc3be34529a8c182778450f4d2`.
- Model Review Group: `campaign-group-10fe1da5930d4efc8b6f6176d9d0b12b`, 8 child Campaigns.
- EXPLAIN used `idx_predictions_issue_run`; observed execution time was 0.068 ms.
- A formal Label snapshot context also passed:
  `evaluation-c6f40ae5-24a3-49ee-94db-c4423f52f900`, snapshot
  `label-result-a14ecb7f35b333c3b9030695af82eee77902da5248640d50739c064ebb506abe`.
- Divergent GT/shared-label acceptance passed:
  `evaluation-a0ae1530-0b69-4879-99f4-5943dc8b3d89`,
  Issue `s6-divergent-unique`: frozen GT reference `无需协助`, frozen shared
  human label `误触发`, `gt_relation=differs_from_gt`.

The full final cloud suite ran on disposable database
`manual_s6_suite_20260922`:

**578 passed, 1 skipped in 54.62 seconds.**

The final source includes S5 regression coverage plus S6 SQLite/PostgreSQL mapping,
policy CAS, compatibility, exclusion, shadow and canonical read checks.

## Database preservation

Final read-only counts:

| Database | Issues | Migrations | State |
| --- | ---: | ---: | --- |
| `manual_s3_smoke_20260921` | 413 | 44 | retained |
| `manual_s4_smoke_20260921_campaign` | 413 | 46 | retained |
| `manual_s5_smoke_v3_20260922` | 4,452 | 49 | retained S5 source |
| `manual_s6_smoke_20260922_legacycutover` | 17,536 | 50 | active S6 smoke |
| `ra_triage_dashboard` | 4,046 | 43 | production |

The S6 database includes the retained S5-v3 data plus unique S6 acceptance fixtures.
No production writer, Trail sync, Batch, AutoTriage publish or D-Chat path was enabled.

## Browser and recovery

CUA remained unavailable in the final pass. HTTP/DOM checks against loopback verified
the exact S6 health/build/base path, read-only session, policy/status endpoint and
legacy inventory endpoint. No public browser listener was opened.

`restore_s5_8786.sh` remains in the S6 source and restores the S5 v3 loopback
service from its retained database. The guarded S6 switch was exercised after each
source update and leaves S6 running on 8786. 8785 was never stopped or modified.
