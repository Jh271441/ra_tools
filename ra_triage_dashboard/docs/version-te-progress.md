# Version composition and TE progress

The version page follows the existing Labeling summary design language: a bounded
1480px reading area, shared Workbench cards and command bar, 12px spacing, and a
small type hierarchy. The user-provided image is a grouping illustration rather
than a visual template. No fonts, UI libraries, endpoints or aggregation logic
are added for this redesign.

A labeled filter panel holds dataset, case scope and occurrence date (CST). Case
scope remains a view filter, not a configurable sampling strategy. All selectors
retain the shared native-select enhancement, including keyboard, Escape, outside
close, viewport positioning, disabled states and locale preservation. The topbar's
existing refresh action is the single manual refresh entry for this page.

Four shared stat cards separate the aggregate labels from their larger values;
values use the normal text color. TE progress, filled-result distribution
and occurrence-date progress each have their own card. Desktop widths follow
content needs rather than equal thirds. The donut includes both percentage and
filled/target count. Filled progress uses the shared success color, pending is
neutral and unknown uses the shared warning color. Result counts use one neutral
bar color: their labels carry the outcome, without making an observed failure
look successful. Composition uses a restrained accent/slate palette. All colors
follow existing theme tokens. Secondary export/paging/date actions use the shared
neutral button variant; the existing search action retains its emphasis. Daily rows keep dates, gauges, counts and percentages in stable columns;
long lists scroll locally. Source freshness and denominator scope stay visible.

Tablet uses two cards followed by a full-width date card. Phone layouts retain
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
