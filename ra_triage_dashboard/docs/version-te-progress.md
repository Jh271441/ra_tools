# Version composition and TE progress

## Chart hover/focus emphasis (2026-10-29 candidate, cache706)

TE status legends and SVG ring segments highlight each other; RD progress/mix
legends and stacked segments do the same within their own block. Other segments
dim without changing category colors, counts, layout or filters. TE result rows
and daily progress rows get a subtle row highlight. Existing TE-status/date click
actions remain; readonly chart/legend inspection never loads or mutates data.
Pointer hover is limited to fine hover-capable pointers; keyboard focus uses the
same emphasis. Phone RD legend targets are44px and retain local horizontal scroll.
Reduced-motion disables transitions. No added popup, request or chart dependency.
Unchanged TE/RD markup retains focused nodes; refreshed counts/locale restore
focus. CSS state avoids listeners and polling-induced DOM mutations.

Validation:54 tests/6subtests and12 actual-module Chromium fixture combinations
(320/390/1440px,zh/en,dark/light), reciprocal hover, leave reset, card isolation,
keyboard/polling/locale focus, unchanged filter state, no API requests, zero/empty/
error/loading/unsupported states, reduced-motion and no page overflow passed.
Desktop and320px English/light screenshots inspected. Browser viewport tests only,
not physical-device or signed-in production acceptance. Candidate706 is not deployed.

The version page follows the existing Labeling summary design language: a bounded
1480px reading area, shared Workbench cards and command bar, 12px spacing, and a
small type hierarchy. The user-provided image is a grouping illustration rather
than a visual template. No fonts, UI libraries, endpoints or aggregation logic
are added for this redesign.

The released cache704 version merges the accepted chart colors with the
statistics-first filter/read optimization (2026-10-29 01:18 CST, cc22256). See
`version-datasets.md` for combined scope, tests and release status.

Metric cards and composition precede a single filter panel containing Dataset /
Case scope / Occurrence date (CST). The redundant View grouping is removed; all
three review modes (all targets, random sample, low excluding sample) are shown
in Case scope through the shared enhanced select in released cache705. An explicitly
restored legacy mode remains as the current extra option until switching back;
existing mode URLs and API values retain their meanings. RD legends now show
counts alongside percentages. Released2026-10-29 10:59:15 CST, commit75b14f7;
1079 cloud tests passed/7 skipped, isolated gray and production health passed.
See `version-datasets.md` for the receipt and exact asset verification.

The four metrics, TE charts, composition and gallery keep their visibility and
counts. The follow-up moves composition directly after the metrics, before TE.
TE result rows use label / count / filled-result share above a full-width bar,
with wrapping labels and natural height rather than a clipped inner scroll region.
No categories are combined or omitted. No tabs, extra cards, persistent explanatory rows
are added. Toolbar fields use three columns on desktop, two at tablet widths and
the existing narrow-phone stack. The chart's cohort is named in the TE denominator
line. Same-dataset filter changes retain charts with an explicit previous-scope
notice until replacement; stale cards/export clear immediately. Dataset changes
clear old charts. Bounded30-second caching and forced refresh behavior are documented
in `version-datasets.md`.

Case scope remains a view filter, not a configurable sampling strategy. All selectors
retain the shared native-select enhancement, including keyboard, Escape, outside
close, viewport positioning, disabled states and locale preservation. The topbar's
existing refresh action is the single manual refresh entry for this page.

Four shared stat cards separate the aggregate labels from their larger values;
values use the normal text color. TE progress, filled-result distribution
and occurrence-date progress each have their own card. Desktop widths follow
content needs rather than equal thirds. The donut includes both percentage and
filled/target count. Filled progress uses the shared success color, pending is
neutral and unknown uses the shared warning color. TE result categories use the
shared chart tokens, not alert states: correct/succeeded teal, false trigger
muted rose, no assistance blue, failed indigo, and unanswered slate. RD uses
the exact same label mapping for its legend and segments.
Raw TE values own colors regardless of rank or locale; unrecognized categories
use muted gray. Shares divide by filled results. Composition uses a restrained
accent/slate palette. The shared Reason analysis/Labeling summary GT donut uses
blue for to-update, muted indigo for needs-attention, and teal for matches-GT;
zero-value arcs no longer shift the palette away from the legend. All colors
follow existing theme tokens. Secondary export/paging/date actions use the shared
neutral button variant; the existing search action retains its emphasis. Daily rows keep dates, gauges, counts and percentages in stable columns;
long lists scroll locally. Source freshness and denominator scope stay visible.

At651–1240px, tablet uses two cards followed by a full-width date card. Phone layouts retain
the original controls, put progress then daily progress then results in one column,
use two-column metrics and filters where they fit, stack the primary filters at
430px and below to keep long scope names readable, and keep 44px touch targets.
0821 preserves its fixed312 targets and hides occurrence-date controls and charts.
Dark and light themes use the same shared tokens and card primitives.

A fixed “All dates” button clears only the occurrence-date filter; clicking the
selected day again also clears it. The selected date remains explicit beside the
TE scope. Same-version filtering keeps charts during loading and updates pressed
states immediately. Dataset switches clear the old scope. Existing request
cancellation, sequence guards, polling, chart focus and scroll retention remain.

Gallery filters have visible labels beneath a Cases heading and Issue search.
Cards keep four compact rows: Issue/cohort, model/confidence, TE/platform review
states, and owner/occurrence time. Trigger and added-time details remain in
accessible metadata and the media dialog. TE and platform review completion
remain independent.

The progress-heading info icon explains source, denominator and update cadence
on hover, focus or tap. Escape and outside interaction dismiss it; the tooltip
stays within the viewport. Shared scroll containers preserve native wheel and
keyboard behavior with theme-aware chrome and forced-color system defaults.

Version composition partitions **inferred, admitted** cases into final enum groups:
sample first, then low confidence, then other. Pending/excluded cases are separate,
never silently counted as other. The groups add up to the same completed cohort.
Gallery reason, owner, Review-status and TE-status filters do not redefine this
version composition; only version and occurrence date scope it.

TE counts remain limited to the low-confidence/sample target set and use only
Trail `ra_review_result_new`. Status filtering does not shrink that denominator;
missing observations remain unknown. Platform combined review is independent and
does not backfill Trail TE results. Nonempty raw values, including failure,
unanswered and out_of_scope, remain filled observations.

The source line shows the last successful check; its tooltip shows result changes
in that observation. The latter counts updates to existing members, not new
members or an inferred annotation timestamp. A later successful check with zero
changes means the observed values are unchanged; stale/error states remain visible.
The API stays read-only and no-store, with bounded local snapshot reads and no
request-time Trail queries. Polling updates freshness even when gallery rows stay
identical and preserves existing card DOM when its contents do not change.


Metric definitions use a top-right info control on each of the four summary
cards, with hover/focus/tap access and native Trail filter links. Definitions use a
whole-version, all-dates count_scope projection independent of gallery filters.
Discovery includes excluded and source-waiting cases; publication requires the
published state. Targets are the low/sample union; eligible completed cases form
the10% probability-sampling denominator, with sample precedence over low.
Historical0821 remains fixed and never claims incremental probability sampling.
Exclusions group known top-level trigger reasons; raw-event-only/unclassified
or business exclusions remain an explicit other bucket rather than an invented
trigger. No new Trail calls or model execution occurs.

Links open Voyager/Trail view2410 using its native encoded query_attrs format.
Keep the array-index marker literal (`query_attrs.$0`): Trail's outer codec uses
`decodeURI`, which preserves `%24` and silently drops that malformed filter.
Generic form-query decoders are insufficient link validation; verify with the
native Trail codec and the request it constructs.
Scopes without an equivalent reason query use issue_id IN for the exact
recorded cohort, including frozen0821 and source-waiting. Compact reason
queries are live field views, as described below. Links do
not inherit current gallery/date/owner/status filters. Empty cohorts omit the
link rather than issue an empty filter that could match all cases. No Trail
request is made during rendering. New shared scope choices support published, excluded, source-waiting and
sampled targets, while preserving older planned-sample and waiting views.
The interactive popovers preserve DOM on identical polls, support clickable
links, Escape/outside dismissal and viewport bounds, and retain the TE source
info control. No persistent explanatory paragraph is added to the page.


Incremental published/target/sample links use compact live reason-field queries:
release-family prefix + trip_category0 + RA2/3 + ODD2, then reason not_empty
or the low/sample enum values. Only1009 adds ra_trigger NOT_IN
kEndOfLaneSequence, excluding31 historical labeled EOL cases found by the
October26 audit. Other incremental versions have no extra trigger-link predicate.
This is a link-only exception; acquisition admission still excludes all four
configured triggers at top level or raw start. Counts remain recorded platform
states; a live Trail query can change independently. Link hover titles distinguish
live fields from exact recorded IDs. Discovery/excluded/source-waiting and frozen
0821 links preserve their exact recorded IDs; reason empty is not source-waiting.
Empty recorded scopes still omit links. No render-time Trail query is introduced.

## Local candidate validation (2026-10-28)

`python3 -m ra_triage_dashboard.tests.preview_version_filters --port 8794` serves
the actual page fragment, shared styles/selects and page modules at
`http://127.0.0.1:8794/version-datasets`. Its workbench uses synthetic in-memory
registry rows and temporary TE snapshots, never production data or Trail. All
mutations are unsupported; external links/media actions are inert in this fixture.
The fixture has no real media and does not establish production/SSO acceptance.
The Error button toggles failed reads; refresh or restarting resets fixture state.
The production frontend cache is bumped together with contract expectations.

Final local checks: 93 unittest cases passed (15 version frontend/workbench,
74 frontend contracts, 4 base-path checks); touched JavaScript syntax and
`git diff --check` passed. The workbench suite emitted an unclosed-event-loop
ResourceWarning after passing. History-driven dataset changes clear group memory;
same-dataset route restoration and locale switching preserve valid selections.

IAB responsive fixture checks covered 1440px Chinese/dark, 320px and 390px
English/light, and 900px tablet layout. Verified shared dropdown scope options,
sample/low denominators, group memory, locale switching, Escape dismissal and
popup/viewport bounds without page-level horizontal overflow. These are browser
viewport checks, not physical-phone or simulator acceptance. No authenticated
production, real-media or full-app-bootstrap acceptance is claimed. This is a
local fixture validation record, not a production acceptance claim.

The first deployment attempt (`b9e4aa9`, cache695) passed 1043 cloud tests
(7 skipped) and isolated gray, but failed when the old process took more than
30 seconds to exit. The original cache693 was restored with its saved
configuration and PostgreSQL health verified. The follow-up fixes deployment
ownership through delayed shutdown, and adds the requested composition order
and compact result rows (cache696). Release status is recorded below after
the exact-SHA production checks.

## Released 2026-10-28 15:55:29 CST

Production is `e286c6b7c7f9a08c2145891c9b1a209c93d2b402`, cache696.
The split prepare/promote release passed 1047 cloud tests (7 skipped), isolated
gray, exact runtime SHA, persistent PostgreSQL and overall health. Served shell,
loader, version module and version/mobile CSS match the exact commit. Access and
writer policy are unchanged; no schema migration. Receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261028T075121Z-e286c6b7c7f9/result.json`.

Follow-up local checks passed 126 tests; IAB verified six complete result rows,
composition before TE, 1440px Chinese/dark and 320/390px English/light with no
horizontal overflow or clipped chart content. English result labels include
Succeeded and Out of scope; source values remain untouched. Production Chrome
and IAB control timed out, so authenticated visual acceptance is not claimed.
The standard retention policy removed only the older unused clean candidate and
rollback trees of release `20261028T050903Z-59af7029ab17`; Git history and small
release records remain recoverable. No business data was removed.
