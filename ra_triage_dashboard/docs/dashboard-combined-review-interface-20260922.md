# Combined model Review and Case labeling contract

Recorded: 2026-09-22 (Asia/Shanghai)

Scope: `codex/dashboard-product-ux` and the isolated 8786 UX database. Production
and historical mixed annotations are excluded from writes.

## Workflow mode

| Value | Meaning | Default |
| --- | --- | --- |
| `model_review_only` | Existing Run-bound model Review UI and writes | Yes, including every existing Campaign |
| `model_review_and_case_label` | One page exposes the shared Case vote and current Run Review | Explicit new-task or verified direct-browser selection only |

`issue_work_splits.workflow_mode` freezes the mode for a Campaign. A
`workflow=combined` query controls only direct-browser presentation; every API
request still verifies identity, Case-label permission and model Review
assignment separately.

## Storage map

| Concern | Storage |
| --- | --- |
| Shared Case vote | Existing `label_cases` + append-only `label_revisions`, keyed by label scope / Issue and author head; no Run identity is added to the vote |
| Run Review | Existing `model_review_revisions` + `model_review_heads`, keyed by Run / Issue / Campaign / reference / reviewer |
| Atomic submission link | `combined_review_submissions`; one `submission_group_id` links the two independent revision IDs or an acknowledged existing Case revision |
| Per-task progress | `combined_review_progress`; separate `model_review_submitted` and `case_label_acknowledged`, with overall completion derived only when both are true |
| Existing Case vote reuse | No new `label_revision` when the submitted value matches the current author head; the current Campaign receives an explicit acknowledgment row |
| Changed Case vote | A normal new `label_revision` supersedes the current author head; other reviewers remain untouched |
| Concurrency | Request carries the loaded model head, Case author head and Case resolution version; mismatch aborts the whole transaction with 409 |

## Atomic API

`POST /api/cases/{issue_id}/combined-review`

Required context: `model_run_id`, `campaign_id` for task mode, model Review
status/reason/evidence, Case expected output/rationale, and all loaded version
tokens. The database service performs both permission checks and both writes in
one transaction. A failure or stale token rolls back both domains.

Response includes `submission_group_id`, the independent Case and model Review
records, whether the Case vote was appended or acknowledged, and the two progress
markers. It never creates or updates an `annotations` mixed record.

## UI map

- Review defaults to `model_review_only`.
- A combined Campaign locks the page to combined mode. Verified direct browsing
  with both write capabilities may select combined mode through the page control
  or `workflow=combined`.
- The Review pane renders a shared Case-label card above the model Review form.
  It reuses the Case label options, tag/rationale controls, colors and validation.
- The header shows Case-label and model-Review status independently. Shared label
  conflict or `GT 待复核` never becomes a model Review status.
- With no Model Run, the Case card can be submitted independently; the model form
  remains unavailable and no combined-submit button is shown.

## Compatibility boundaries

- Existing Campaigns read as `model_review_only` without data migration.
- Historical Review rows, reasons, statuses, comments and statistics remain
  unchanged.
- The previous label-only historical import remains valid and can be explicitly
  acknowledged in a combined Campaign without creating a duplicate vote.
- Case conflict may coexist with a completed model Review. Conflict and pending
  adjudication remain properties of the shared Case label projection.
