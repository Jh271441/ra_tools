# S3 model-review domain

S3 separates Run-bound model diagnosis from shared Label/GT state.

## Storage

- `model_review_revisions` is append-only audit history keyed by Run, Issue,
  optional campaign/reference, reviewer, and WorkSplit provenance.
- `model_review_heads` points to one current revision per
  `(model_run_id, issue_id, campaign_id, reference_id, reviewer)` identity.
- `model_review_attachments` binds attachment metadata to the S3 revision.
- States are `pending`, `in_progress`, `completed`, and `blocked_by_label`.
  A conflicting or stale shared Label projection forces `blocked_by_label`.

Migration 044 also creates read-only compatibility views. `review_records`
projects S3 revisions into the legacy annotation response shape and unions legacy
annotations. S3 public IDs use a bounded numeric offset so a new revision sorts
after legacy rows without colliding with legacy primary keys. New writes never
insert an `annotations` row. `review_record_attachments` provides the equivalent
attachment read projection.

## Write boundary

The established `/api/cases/{issue_id}/annotations` JSON/multipart routes remain
the browser compatibility entry point:

- non-empty `model_run_id` appends a model-review revision;
- a new Review without a selected Run is rejected. Active Case-labeling scopes
  return 409 with the Label-workbench handoff; other scopes return 400 and ask
  the user to select a Run;
- WorkSplit membership, author and optimistic concurrency checks still run;
- expected-output, Tags and exclusion fields are not written into S3.

The Review UI hides shared-label editing controls in Run-bound mode and displays
the S3 state selector. Shared Label changes remain under `/api/labeling/...`.
Run discussion continues to use the existing Issue+Run comment namespace; new
unbound Review comments are rejected. Label discussion continues to use
`label_comment_links` and the labeling routes.

## Read boundary and compatibility

Gallery, detail, task progress, facets and Reason Analysis read the compatibility
projection. Indexed S3 heads win for the same Run/Issue/reviewer; legacy rows
remain as fallback and history. Reason Analysis and export include
`model_review_status` plus `review_domain`. The shadow endpoint compares new heads
with their deterministic legacy counterpart without mutating either domain.

`scripts/backfill_model_reviews.py` defaults to dry-run and migrates only
determinate 0206/0508 legacy rows with diagnostic content and no mixed label/tag/
exclusion payload. Mixed notes stay on legacy fallback.

## Smoke database

`scripts/build_manual_s3_smoke.py` operates only on a fresh logical restore whose
database name is `manual_s3_smoke` or starts with `manual_s3_smoke_`, and whose
PostgreSQL server address is local. It defaults
to dry-run and requires `--apply` for pruning. It selects 10% by stable SHA-256
rank, adds the requested Issue, one representative overlap from the two pinned
Runs, required Label states and task examples, records pinned additions and lineage, rebuilds task/workset counts and smoke
GT snapshots, removes attachment binaries/metadata and external-effect queues,
and fails on FK or unselected-Issue references.
If the source has no stale adjudication, it creates one explicitly marked
smoke-only stale state on a sampled Issue and records its synthetic revisions
in the cloud-only manifest.

Production PostgreSQL and port 8785 are never valid targets for this workflow.
