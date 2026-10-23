# Version composition and TE progress

The version page follows the established full-width Workbench layout: four
aggregate metrics in one row, followed by the full-width TE panel and then a
secondary full-width composition bar. This restores the original visual hierarchy after the user rejected the
side-by-side narrow summary and tiny date-tile redesign. Spacing is modestly
reduced; text and charts retain the original readable scale.

Inside the TE panel, overall counts and their filled-result distribution sit
adjacent on desktop, with a light divider connecting the two. The occurrence-date
section fills the remaining width with one horizontal progress row per day;
two dates no longer leave an elastic empty column between counts and results.
The same row keeps its date, gauge, filled/target count and percentage in stable
columns. Long lists scroll within the bounded chart. Tablet/mobile layouts wrap
existing components without document overflow; mobile puts daily progress before
the secondary result distribution and retains 44px touch targets. The chart keeps
up to 14 dates and includes a selected older date.0821 retains its fixed312
members with no date chart.

A fixed “All dates” button clears only the occurrence-date filter; clicking the
selected day again also clears it. Current selected date appears beside the TE
scope count, so changing the denominator is explicit. Same-version filtering keeps
charts mounted during loading, updates pressed states immediately, and leaves
cancellation controls reachable. Dataset switches clear the old scope; polling,
request sequence guards and all other filters remain unchanged. Count refreshes
retain the focused date and the chart scroll position.

The user-prioritized TE summary shows filled and pending counts prominently;
the shared denominator appears once beside its heading. The occurrence chart is
labeled “Filled / targets”, and the filled-result distribution has its own heading,
stable categorical colors, localized known values, and wrapping long labels.
Raw source values and filled/pending semantics remain unchanged. Source freshness
stays visible; per-check changes are secondary tooltip content.

Gallery cards use four compact rows: Issue/cohort, model/confidence, TE and platform
review states, and owner/occurrence time. Trigger and added-time details remain in
the card's accessible metadata and media dialog, reachable on touch devices too.
The two independent completion systems are never merged into one status.

The heading info icon explains source, denominator and update cadence on hover,
focus or tap. Escape and outside interaction dismiss it. Tooltip position stays
within the viewport. Shared scroll containers use native wheel/keyboard behavior
with theme-aware thin rounded chrome; forced-color mode keeps system defaults.
The collapsed sidebar's deliberate hidden scrollbar remains unchanged.

Design references, checked2026-10-23:

- [Grafana Stat](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/stat/): compact values for aggregate metrics.
- [Grafana Bar gauge](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/bar-gauge/) and [Table](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/table/): label/value gauges and compact rows.
- [Metabase dashboard width](https://www.metabase.com/docs/latest/dashboards/introduction#dashboard-width): bounded dashboard layouts across different display sizes.
- [Radix Scroll Area](https://www.radix-ui.com/primitives/docs/components/scroll-area): prefer native scrolling and CSS customization when sufficient.

These references inform existing metric, gauge and scrolling components. The
user-requested established Workbench layout takes precedence over the previously
tried bounded side-by-side overview; no new framework is introduced.

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
