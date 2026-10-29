# Version data workbench

One page at `/manual/version-datasets` combines processing coverage, TE progress and one image gallery. The sidebar has only Version datasets and Daily tasks. Historical `/manual/daily-review` links redirect with version, reason, occurrence date, TE status, media, order and page preserved. 0821 remains a frozen312-case TE dataset; it does not enter the incremental collector or create a new Run.

## Membership and TE authority

The version registry is the current target denominator. `ra_review_result_new` snapshots supply TE status/results only. A new target absent from an older snapshot is unknown; no model/RD fallback. Sampling overrides low confidence for the displayed disjoint groups. Non-target candidates display an explicit outside-review state and do not inflate TE unknowns. TE status narrows the gallery without shrinking progress denominators; occurrence date, reason and Issue search scope both. Dates use CST occurrence time and late arrivals backfill older cohorts.

The bounded read-only projection selects metadata and prediction label/confidence in one query (20,000-case cap); it never reads video/bag files or calls Trail. CSV has the same filters and order as the gallery and requires a revision matching the current registry/snapshot. A changed revision returns409. Existing APIs and Campaign/Run-bound joint-review links remain available. No schema, membership, assignment, sampling, GT or scheduling mutation is part of this change.

## Case labeling entry and membership

`version-*` selector entries come from the database-backed operational catalog, not the static baseline registry. Dashboard configuration maps active labeling scopes through both catalogs; old hidden daily IDs remain valid for existing task links. A registered version is not automatically active: its scope must still have active status.

The model-free labeling gallery, full detail queue, summary, clusters, GT candidates and GT export previews use the same current-target membership restriction as Review. Source scopes alone include historical/non-target Issues and must not define a version gallery. Explicit Issue filters intersect the current targets; an empty intersection stays empty. Mixed selections union version targets and ordinary baseline members. An explicit historical task keeps its frozen membership. These are read-time projections; historical records and permissions are unchanged.

## Review and Case labeling target cohorts (2026-10-28)

Both pages expose the shared bilingual **目标集合 / Target cohort** single-select.
These are existing `version_dataset_items` flags keyed by version dataset and
Issue ID, not human Issue tags or a confidence threshold calculated from the
currently selected Run:

- All (empty `target_group`, or API value `all`) preserves the existing scope,
  including frozen historical task membership.
- Random sample (`target_group=sample`) requires `is_target=1 AND is_sample=1`.
- Low confidence excluding samples (`target_group=low`) requires
  `is_target=1 AND is_low=1 AND is_sample=0`, matching version-page sample precedence.

The selected cohort intersects dataset, task, owner, progress and other filters.
No-match results remain empty; invalid cohort values return400 rather than widen
the scope. Explicit cohorts always use current registry flags, including when
viewing a frozen task; retired/non-target members stay accessible with All.
URL restoration, detail queues, pagination, exports and filtered task creation
retain the cohort. This does not add a cohort control to the separate labeling
summary page. No memberships, owners, human labels, GT or predictions are changed.

Released `70f14e297e46afa24b7cbe1583740e28052f9ed3`, cache698, at
2026-10-28 19:47:08 CST. Cloud suite1054 passed/7 skipped; isolated gray and
production exact SHA, persistent PostgreSQL and overall health passed. Served
shell, loader, changed picker/routing/labeling JS and layout CSS matched the commit.
Receipt: `/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261028T114409Z-70f14e297e46/result.json`.
Signed-in production Chrome desktop checks exercised both pages:1009 All628,
sample159 and low excluding samples469; both cohort choices updated the URL and
gallery. Screenshots confirmed actual controls and loaded business data. No
business submissions or exports were performed. No real-device testing claimed.

Local validation: suite1047 passed,
14 skipped (7Linux-only checks and7unconfigured disposable-PostgreSQL checks),
141 subtests passed. Actual frontend modules in isolated browser fixtures passed
24 page/viewport/language/theme combinations: Review and Case labeling at
320/390/1440px, Chinese/English, dark/light. Checks include shared widgets,
URL/request preservation, language switching, keyboard/Escape, popup boundaries,
44px phone targets, no page overflow and filter reset. These are viewport tests,
not physical-device acceptance; signed-in checks are separately recorded above. Regression coverage:
`tests/test_target_cohort_filter.py` and `tests/target_cohort_browser.cjs`.

## Interaction and performance

### Two-row correction (2026-10-29 candidate/cache703; not deployed)

User rejected cache701's third row, blank cells and bottom-edge task caption.
Desktop (>1024px) now uses nine equal columns, or eight with both task-progress
and workflow fields hidden; Case labeling uses six. Issue search spans two columns
on both pages; other fields occupy one, including Run/task/mode. Reset fills the remaining last-row cells. This
supersedes the previous140px auto-fit/double-span policy; DOM/tab order and shared
dropdowns/query state remain unchanged. Tablet/phone retain mobile.css ownership.

Task summary, assignment-list empty/error hints and locked-mode information live
inside field-heading right-hand shared info popovers, not beneath the form.
Desktop button/SVG is1em; phone preserves44px targets. Escape/outside dismissal,
focus/hover/click and viewport bounds use bindUiInfoPopovers. No new business writes.
The original task-exit button moves to its heading, retaining ID/listener.

Regression covers both progress/mode visible/hidden combinations at all desktop
widths, equal fields/two rows/no gaps, bilingual task summary and list empty/error,
info font-height/popup bounds/Escape, existing filters/URL/reset and mobile targets.
Validation:73 focused tests and6 subtests passed;64 browser combinations passed
at320/390/768/1024/1025/1180/1440/1920px, both languages/themes/pages. Browser
fixtures are local viewport checks, not production or real-device tests.

### Equal-width gallery filters (2026-10-28 released, cache701)

Released isolated commit276be79c73489a842c062686e06da214b0fb8e3c at
2026-10-28T13:12:53Z, based on current production09f943d. Existing RD and raw
planning-constraint features are retained. Main checkout/master remain unchanged;
production runs the managed candidate under release20261028T130931Z-276be79c7348.
Cloud1078passed/7skipped, isolated gray, exact production SHA/resources and
persistent PostgreSQL/overall health passed. After merging the live baseline,
90 local tests/15 subtests and all64 browser combinations passed again. Signed-in
Chrome and IAB automation timed out; no production visual or physical-device
acceptance is claimed. No migration, labels, GT or business-data mutation.

Review and Case labeling now share an adaptive desktop grid with a140px minimum
column unit and8px gaps. Ordinary categorical fields use one unit; Run, search,
task and Review mode use two. Reset stays compact at the right edge. Remove the
old per-field/nth-child spans rather than layering another override. At1920px
both filter bars fit two rows; narrower desktops wrap without squeezing normal
fields. Original DOM order, shared dropdown widgets, values and query semantics
stay unchanged. Final tablet/phone layout is still owned by mobile.css.

Validation:51 frontend/path contracts and6 subtests passed. The actual-module
browser fixture covers64 combinations at320/390/768/1024/1025/1180/1440/1920px,
both languages/themes/pages, plus task-progress hidden/visible in each. It checks
equal widths within/across pages, double-width fields,1920px two-row alignment,
popup boundaries, keyboard/Escape, selection/URL persistence, reset and phone
44px targets/no page overflow. Screenshots were visually inspected. This is
isolated viewport testing, not production or physical-device verification.

### RD overview (cache699)

Two compact blocks below TE show RD completion and the three-class distribution.
Both use TE's shared heading typography; each heading and inline scrollable legend
share a row on wide screens, with a thin chart below. Phone blocks stack and use
at most three rows each. No new chart library or dropdown implementation.

`workbench.rd` contains counts only from Manual's `project_issue_label_states`,
grouped by each Issue's original baseline scope in batches of at most400.
Resolved canonical conclusions count as completed. Conflict/stale states count
as conflicts needing recheck; all other states (including absent and incomplete)
are pending. Valid current Issue decisions participate through the same shared
projection and become stale on source changes. No model, GT, TE or joint-review
acknowledgement fallback; no human record, task, owner or schema writes.

Denominator: current version targets intersected with case scope, occurrence date
(CST), Issue search, assignee and joint-review filters, before pagination and the
gallery-only TE-status filter. Classification percentages use completed valid
conclusions, not total targets. Poll every30seconds through the existing request;
counts enter snapshot identity. Failed reads show an unavailable state, not zero.
Historical0821 explicitly reports RD unsupported rather than mixing today's
labels into its frozen membership contract. Existing endpoint permissions stay
unchanged; no individual labels, authors, rationale or history are added to it.

Local release gate:78 relevant tests and6 subtests passed. Real SQLite regression
covers original scopes, conflict/decision/stale state, GT/model/joint independence,
bounded queries, filters, pagination and revision refresh. Production frontend
modules in the isolated synthetic fixture were checked at1440zh-dark and320/390
en-light: no page overflow, matching14px/650 TE and RD headings, compact rows,
keyboard legend scrolling, bilingual error/empty and recovery. These are browser
viewport tests, not physical-device tests. Cloud suite/gray/production results
are recorded separately after the release succeeds.

One enhanced version selector covers each live release plus0821. Cards show model output/confidence, TE status, owner, trigger and arrival/occurrence times. Image opens the existing media preview; Issue identity retains its combined-review link. BEV/Camera, TE status, reason, date, Issue search, order and pagination are URL-restorable. The default order is latest registry arrival; bootstrap records may share a timestamp. Source-update, occurrence and Issue order remain available.

Overview and gallery paint independently of global Review/GT bootstrap.24-case pages and at most4 near-viewport thumbnail loads keep images bounded. Unchanged polling retains card/image DOM; hidden tabs pause. Failed same-scope refreshes preserve the result; a scope change clears stale cards/TE/export before loading. Import history loads only while expanded. The occurrence-day chart is supplementary and collapsed by default. Shared selects, Chinese/English, theme variables and responsive styles are retained.

## Incremental graph

The scheduler polls every5minutes. Each completed prediction can advance to Trail publication, target import and independent media while other cases continue inference. A current inference fraction includes its pending queue. Downstream nodes show cumulative finished-result coverage and a streaming label while upstream remains incomplete. A verified-video count does not prove bag cleanup; cleanup and retry status require their own receipts. No synthetic whole-batch success is inferred from a nonzero published count.

## Appendable version review tasks

`/manual/review-assignments` defaults to Version tasks: one stable `version:<dataset_id>` parent of type `version_live` per live release. This uses the persisted version dataset and task bindings; current targets and assignments grow automatically. Polling/import adds members to that same entry. Separate old/current fixed tasks, including0821, remain under All current tasks; source batches and every immutable ingestion receipt remain audit records.

The parent reads current target membership, actual assignees, and the existing `ASSIGNMENT_SUBMITTED_SQL`: combined tasks count complete only after both model review and Case acknowledgment. It never conflates TE completion with joint review. Detail filters/pagination compose over that parent and expose recent addition receipts. Case links retain the original Run/Campaign identity; parent detail does not issue edits against a virtual ID. Existing source-task management is linked separately. No Campaign/Label Case/Review records, members, owners or timestamps are rewritten by this consolidation.

Start combined review opens the unified version gallery scoped to the current assignee and pending joint review, with visible owner/state controls. Original frozen Campaigns keep their own scopes, including historical members no longer in the public target set. This UI grouping does not delete historical work or change the four-worker incremental launcher.
