# Manual S6 Legacy Cutover smoke report

Recorded: 2026-09-22 (Asia/Shanghai)

## Final runtime

- Branch: codex/legacy-cutover-s6
- Running application source: c78aa6cedc90095639edea29e5fd4959ca3859a3
- Active S6 v2 root: manual_s6_v2_legacy_cutover_20260922
- Active S6 database: manual_s6_smoke_v2_20260922
- 8786: 127.0.0.1:8786/manual-s6, migration 50, anonymous read-only.
- Production 8785 remained PID 10634, build 5fdc41ba8b0215170a8307237762e1ed50a9aaf2; no production deployment or merge.

S6 v2 was rebuilt from the retained S5 v3 logical state. S6 v1 remains preserved separately.

## Inventory and determinate mapping

Inventory SHA: c7dc63fd4d250cbeedbbfe6916df15110f1fbf5a97a09e65f62edcdea6aad062.

| Classification | Count | Treatment |
| --- | ---: | --- |
| model_review_mapped | 1 | Real S3 Model Review target exists. |
| label_history_mapped | 1 | Real source Label revision target exists. |
| legacy_mixed | 209 | Mixed model/label/tag/exclusion history retained read-only. |
| legacy_task_history | 0 | No pure task-only row in this fixture. |
| legacy_unbound_history | 0 | No empty-axis row in this fixture. |

Apply is append-only and idempotent. It checks expected inventory SHA in the same transaction. Source annotations, comments and attachments remain unchanged.

## Policy and shadow

All five v2 scopes ended canonical after component receipt validation. The 40 receipts are 25 pass and 15 expected_diff, with no unexpected defect. Required components were gallery, overview, reviewers, reason_analysis, reason_export, run_metadata, campaign_progress and trail_exclusion. Expected differences are issue-level legacy_mixed, legacy_unbound_history or legacy_task_history.

0508 canonical-to-shadow rollback was exercised with CAS epochs and then restored to canonical. Public endpoint hashes:

| Endpoint | Canonical | Shadow rollback |
| --- | --- | --- |
| /api/cases?page_size=20 | ed080e204f355c2d0bd87f3b24fca33c36d9d2ae5ec04505ea97a2ca795a7b11 | 8aeb6d8c7974dca493fa7ac1103ae5c6ef1fd998bdb34d12d3eb237 |
| /api/reviewers | e66e2692c7ac0b69d261a295b613cf7c17c2e5da9c36c417d64135086ba21f65 | same |
| /api/review-reason-analysis | b1089b9625de356a986cadf64a38d9c84b209a6a8b50f1ebc0c0f4ad51048509 | same |
| /api/model-runs | 262180f14e37ec253804fd0ae6e17f471b6c2ed2ddf0670727ea546b831dfac4 | same |

The cases response changed as expected when legacy fallback was removed; equal hashes on the other components reflect no determinate canonical delta in this fixture.

## Canonical projection and exclusion

Canonical Issue projection combines S1 shared Label state, selected Run prediction and exact Model Review heads by Run/Campaign/reference/reviewer. Without a reviewer filter it returns all heads plus an effective aggregate; it never fills from an unbound or prior Run. Legacy resolver endpoints retain annotation/comment/task evidence and expose canonical targets. Classified/canonical annotation deletion returns 409. Canonical scopes do not inherit legacy/prior Run draft tags. Exclusion projection is bulk per scope; pending/conflict/stale states are non-writable and only explicit resolved excluded state can become a Trail candidate. External Trail writers remained disabled.

## S5 regression and performance

Final v2 acceptance: 4,039 Issues, 5 scopes, 8 Runs; Evaluation evaluation-9cd6fce5-81de-41f6-88ec-220463c26e2f; Workset run-evaluation-workset-59f38d9292bc4639aaace7d312c02e78; compact detail 105,729 bytes; export 7,375,509 bytes / 4,039 items; Campaign campaign-30c830cba3614e3180a26c7ecc66fc56; Model Review Group campaign-group-8bd8533c35674a48a7b5846c3023515a with 8 child Campaigns; index plan idx_predictions_issue_run, execution 0.058 ms. Label snapshot Evaluation evaluation-0d26d157-77f6-48b9-a38f-c699ddc07264 uses snapshot label-result-78e143ec29a33c11bc021cc72a0648e7175e846609e54185cea16fed5adb00e8.

Clean disposable S6 suite database manual_s6_suite_v2_20260922: 578 passed, 1 skipped in 59.95 seconds.

## Preservation

| Database | Issues | Migrations |
| --- | ---: | ---: |
| manual_s5_smoke_v3_20260922 | 4,452 | 49 |
| manual_s6_smoke_v2_20260922 | 8,491 | 50 |
| manual_s6_suite_v2_20260922 | 9,458 | 50 |
| ra_triage_dashboard | 4,046 | 43 |

S3/S4 databases remain retained and unchanged. No production, Trail, Batch, AutoTriage or D-Chat writer was enabled. CUA was unavailable; HTTP/DOM and API checks were used.
