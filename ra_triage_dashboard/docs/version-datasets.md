# Version data workbench

One page at `/manual/version-datasets` combines processing coverage, TE progress and one image gallery. The sidebar has only Version datasets and Daily tasks. Historical `/manual/daily-review` links redirect with version, reason, occurrence date, TE status, media, order and page preserved. 0821 remains a frozen312-case TE dataset; it does not enter the incremental collector or create a new Run.

## Membership and TE authority

The version registry is the current target denominator. `ra_review_result_new` snapshots supply TE status/results only. A new target absent from an older snapshot is unknown; no model/RD fallback. Sampling overrides low confidence for the displayed disjoint groups. Non-target candidates display an explicit outside-review state and do not inflate TE unknowns. TE status narrows the gallery without shrinking progress denominators; occurrence date, reason and Issue search scope both. Dates use CST occurrence time and late arrivals backfill older cohorts.

The bounded read-only projection selects metadata and prediction label/confidence in one query (20,000-case cap); it never reads video/bag files or calls Trail. CSV has the same filters and order as the gallery and requires a revision matching the current registry/snapshot. A changed revision returns409. Existing APIs and Campaign/Run-bound joint-review links remain available. No schema, membership, assignment, sampling, GT or scheduling mutation is part of this change.

## Interaction and performance

One enhanced version selector covers each live release plus0821. Cards show model output/confidence, TE status, owner, trigger and arrival/occurrence times. Image opens the existing media preview; Issue identity retains its combined-review link. BEV/Camera, TE status, reason, date, Issue search, order and pagination are URL-restorable. The default order is latest registry arrival; bootstrap records may share a timestamp. Source-update, occurrence and Issue order remain available.

Overview and gallery paint independently of global Review/GT bootstrap.24-case pages and at most4 near-viewport thumbnail loads keep images bounded. Unchanged polling retains card/image DOM; hidden tabs pause. Failed same-scope refreshes preserve the result; a scope change clears stale cards/TE/export before loading. Import history loads only while expanded. The occurrence-day chart is supplementary and collapsed by default. Shared selects, Chinese/English, theme variables and responsive styles are retained.

## Incremental graph

The scheduler polls every5minutes. Each completed prediction can advance to Trail publication, target import and independent media while other cases continue inference. A current inference fraction includes its pending queue. Downstream nodes show cumulative finished-result coverage and a streaming label while upstream remains incomplete. A verified-video count does not prove bag cleanup; cleanup and retry status require their own receipts. No synthetic whole-batch success is inferred from a nonzero published count.
