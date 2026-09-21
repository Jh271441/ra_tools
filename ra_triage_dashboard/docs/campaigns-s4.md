# S4 Campaigns

S4 treats `issue_work_splits` as the compatibility table for a Campaign. The
Campaign service is the canonical read/write boundary for newly created tasks;
legacy split IDs and their existing Workset, assignment, Label, and Model Review
rows remain addressable.

## Domain rules

- `purpose` is `labeling` or `model_review`. A Model Review Campaign binds one
  existing `evaluation_run_id`; a Labeling Campaign has no evaluation Run and
  must bind a frozen Workset.
- Workset membership is copied into `campaign_issue_members`. Each Issue stores
  its actual `required_submitter_count`, derived from its unique assignee set;
  overlapping reviewers therefore do not share completion credit.
- A Campaign's reference is an immutable GT or Label result snapshot. Campaigns
  spanning scopes use `campaign_reference_items` and expose a reference-set
  digest. Labeling selection provenance stays on the Workset.
- Configuration versions and assignment changes are append-only. Mutations
  require `expected_revision` and an idempotency key. A closed Campaign saves a
  per-Issue result snapshot; reopening starts a new configuration revision and
  preserves every earlier close snapshot.
- A Task Group groups child Campaigns but does not combine their progress. A
  Model Review Group requires a shared Workset/reference and one child per Run.
- Discussion channels are independent: Case public discussion is keyed by
  baseline scope and Issue, Campaign discussion by Campaign and Issue, and
  Model Review discussion by Run and Issue. Replies remain in the parent
  channel. Labeling pages can show Case public plus the selected Campaign;
  other Campaigns remain read-only references.

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
- Campaign comments have their own Issue discussion endpoints. Case comments
  use `/api/cases/{issue_id}/case-comments`; Model Review comments continue to
  use the Run-bound `/api/cases/{issue_id}/comments` endpoint.
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

See [the S4 smoke report](manual-s4-campaign-smoke-report-20260921.md) for the
isolated database, migration, tests, flags, browser check, and restore procedure.
