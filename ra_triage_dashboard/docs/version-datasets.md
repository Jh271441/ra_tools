# Version data workbench

One page at `/manual/version-datasets` combines processing coverage, TE progress and one image gallery. The sidebar has only Version datasets and Daily tasks. Historical `/manual/daily-review` links redirect with version, reason, occurrence date, TE status, media, order and page preserved. 0821 remains a frozen312-case TE dataset; it does not enter the incremental collector or create a new Run.

## Membership and TE authority

The version registry is the current target denominator. `ra_review_result_new` snapshots supply TE status/results only. A new target absent from an older snapshot is unknown; no model/RD fallback. Sampling overrides low confidence for the displayed disjoint groups. Non-target candidates display an explicit outside-review state and do not inflate TE unknowns. TE status narrows the gallery without shrinking progress denominators; occurrence date, reason and Issue search scope both. Dates use CST occurrence time and late arrivals backfill older cohorts.

The bounded read-only projection selects metadata and prediction label/confidence in one query (20,000-case cap); it never reads video/bag files or calls Trail. CSV has the same filters and order as the gallery and requires a revision matching the current registry/snapshot. A changed revision returns409. Existing APIs and Campaign/Run-bound joint-review links remain available. No schema, membership, assignment, sampling, GT or scheduling mutation is part of this change.

## Case labeling entry and membership

`version-*` selector entries come from the database-backed operational catalog, not the static baseline registry. Dashboard configuration maps active labeling scopes through both catalogs; old hidden daily IDs remain valid for existing task links. A registered version is not automatically active: its scope must still have active status.

The model-free labeling gallery, full detail queue, summary, clusters, GT candidates and GT export previews use the same current-target membership restriction as Review. Source scopes alone include historical/non-target Issues and must not define a version gallery. Explicit Issue filters intersect the current targets; an empty intersection stays empty. Mixed selections union version targets and ordinary baseline members. An explicit historical task keeps its frozen membership. These are read-time projections; historical records and permissions are unchanged.

## Interaction and performance

One enhanced version selector covers each live release plus0821. Cards show model output/confidence, TE status, owner, trigger and arrival/occurrence times. Image opens the existing media preview; Issue identity retains its combined-review link. BEV/Camera, TE status, reason, date, Issue search, order and pagination are URL-restorable. The default order is latest registry arrival; bootstrap records may share a timestamp. Source-update, occurrence and Issue order remain available.

Overview and gallery paint independently of global Review/GT bootstrap.24-case pages and at most4 near-viewport thumbnail loads keep images bounded. Unchanged polling retains card/image DOM; hidden tabs pause. Failed same-scope refreshes preserve the result; a scope change clears stale cards/TE/export before loading. Import history loads only while expanded. The occurrence-day chart is supplementary and collapsed by default. Shared selects, Chinese/English, theme variables and responsive styles are retained.

## Incremental graph

The scheduler polls every5minutes. Each completed prediction can advance to Trail publication, target import and independent media while other cases continue inference. A current inference fraction includes its pending queue. Downstream nodes show cumulative finished-result coverage and a streaming label while upstream remains incomplete. A verified-video count does not prove bag cleanup; cleanup and retry status require their own receipts. No synthetic whole-batch success is inferred from a nonzero published count.

## Appendable version review tasks

`/manual/review-assignments` defaults to Version tasks: one stable `version:<dataset_id>` parent of type `version_live` per live release. This uses the persisted version dataset and task bindings; current targets and assignments grow automatically. Polling/import adds members to that same entry. Separate old/current fixed tasks, including0821, remain under All current tasks; source batches and every immutable ingestion receipt remain audit records.

The parent reads current target membership, actual assignees, and the existing `ASSIGNMENT_SUBMITTED_SQL`: combined tasks count complete only after both model review and Case acknowledgment. It never conflates TE completion with joint review. Detail filters/pagination compose over that parent and expose recent addition receipts. Case links retain the original Run/Campaign identity; parent detail does not issue edits against a virtual ID. Existing source-task management is linked separately. No Campaign/Label Case/Review records, members, owners or timestamps are rewritten by this consolidation.

Start combined review opens the unified version gallery scoped to the current assignee and pending joint review, with visible owner/state controls. Original frozen Campaigns keep their own scopes, including historical members no longer in the public target set. This UI grouping does not delete historical work or change the four-worker incremental launcher.
