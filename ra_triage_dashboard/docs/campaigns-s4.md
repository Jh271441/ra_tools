# S4 Campaigns

S4 treats `issue_work_splits` as the compatibility table for a Campaign. The
Campaign service is the canonical read/write boundary for newly created tasks;
legacy split IDs and their existing Workset, assignment, Label, and Model Review
rows remain addressable.

## Domain rules

- `purpose` is `labeling` or `model_review`. Every native Campaign binds a
  frozen Workset. A Model Review Campaign also binds one existing
  `evaluation_run_id`; the current Workset schema is single-scope, so a Run-based
  Work Split must select one baseline per Campaign. Legacy rows without a
  Workset remain mapped only when explicit source evidence supports the mapping;
  otherwise they remain unclassified and read-only.
- Workset membership is copied into `campaign_issue_members`. Each Issue stores
  its actual `required_submitter_count`, derived from its unique assignee set;
  overlapping reviewers therefore do not share completion credit.
- A Campaign's reference is an immutable GT or Label result snapshot. Campaigns
  spanning scopes use `campaign_reference_items` and expose a reference-set
  digest. Labeling selection provenance stays on the Workset.
- Configuration versions, assignment changes, and lifecycle audit are
  append-only. Assignment mutations require `expected_revision` and an
  idempotency key; reassign replaces one assignee atomically and records the
  reason. Allowed lifecycle transitions are `draft -> active`,
  `draft|active -> cancelled`, `active -> superseded`, `active -> closed`, and
  `closed -> active`. Activation, cancellation, superseding, and reopening
  advance the config revision. A closed Campaign saves a per-Issue result
  snapshot; reopening preserves every earlier close snapshot. Cancelled and
  superseded Campaigns are terminal.
- A Task Group groups child Campaigns but does not combine their progress. Its
  read-only detail view shows the shared Workset/reference, member Runs, and
  each child Campaign's independent progress. A Model Review Group requires a
  shared Workset/reference and one child per Run.
- Discussion channels are independent: Case public discussion is keyed by
  baseline scope and Issue, Campaign discussion by Campaign and Issue, and
  Model Review discussion by Run and Issue. Replies remain in the parent
  channel. Campaign detail reuses the shared discussion dialog, shows Case
  public plus the current Campaign, groups other Campaign threads as read-only,
  and requires a channel choice before posting.
- Label Analysis separates Scene, Trigger/interaction, and Egress tags. It uses
  catalog labels in the UI and routes label rationales through the same
  deterministic reason-theme classifier as Review analysis. Raw tag keys remain
  available in tooltips and exports.

## API

- `GET /api/campaigns` and `GET /api/campaigns/{id}` list Campaigns and their
  per-Issue progress. Read endpoints expose summaries only.
- `POST /api/campaigns` creates one Campaign; the existing Run-based Work Split
  and Labeling task creation flows are compatibility adapters that create
  Campaign records for new tasks.
- `POST /api/review-task-groups` creates a Labeling group with one shared task
  or a Model Review group with per-Run child Campaigns;
  `GET /api/review-task-groups/{id}` preserves that grouping.
- `PATCH /api/campaigns/{id}/issues/{issue_id}/assignments` supports assign,
  unassign, and reassignment with optimistic concurrency and audit.
- `POST /api/campaigns/{id}/close` and `/reopen` persist close/reopen history.
- `POST /api/campaigns/{id}/activate`, `/cancel`, and `/supersede` enforce the
  lifecycle graph and append an idempotent audit record.
- `GET /api/review-task-groups/{id}` returns shared configuration and child
  Campaign progress. `GET /api/campaigns/{id}/issues/{issue_id}/discussion`
  returns Case, current Campaign, other Campaign references, and Run-channel
  comments with their channel scopes intact.
- Campaign comments have their own Issue discussion endpoints. Case comments
  use `/api/cases/{issue_id}/case-comments`; Model Review comments continue to
  use the Run-bound `/api/cases/{issue_id}/comments` endpoint. Replies across
  channels are rejected by the server.
- `GET /api/campaigns/{id}/analysis` returns Label Analysis metrics and a
  rationale-searchable Issue page. The admin-only CSV export includes the
  underlying label revisions and rationales.

All mutation routes require server-verified admin identity. Production's
existing identity middleware and request markers remain the authorization
boundary.

## Legacy mapping

`scripts/inventory_s4_campaigns.py` is read-only and computes a SHA-256 over the
legacy splits, assignments, Worksets, label records, review comments, and
Run-bound review revisions. `scripts/migrate_s4_campaigns.py` defaults to
read-only inventory output. `--apply` requires the exact current inventory SHA,
a private URL file, a local `manual_s4_smoke*` PostgreSQL database, actor, and
policy version. It maps only purpose supported by explicit Workset/Label or
Run-bound review evidence. Conflicting or ambiguous rows remain visible,
unclassified, and read-only. The source inventory is rechecked inside the
transaction before applying mappings.

The S4 PostgreSQL smoke runner is `scripts/smoke_s4_campaigns_postgres.py`; the
wrapper clones the isolated S4 smoke database into a unique disposable
PostgreSQL database, runs the fixtures, records query timings and EXPLAIN
summaries, then drops the fixture database. It never targets S3 or production.

See [the S4 smoke report](manual-s4-campaign-smoke-report-20260921.md) for the
isolated database, migration, tests, flags, browser check, smoke receipts, and
restore procedure.
