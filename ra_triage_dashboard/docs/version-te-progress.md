# Version composition and TE progress

The version page follows the established full-width Workbench layout: four
aggregate metrics in one row, followed by a full-width composition bar and TE
panel. This restores the original visual hierarchy after the user rejected the
side-by-side narrow summary and tiny date-tile redesign. Spacing is modestly
reduced; text and charts retain the original readable scale.

Inside the TE panel, overall progress, occurrence-date vertical bars and result
distribution share a row on desktop. Dates use natural-width bars rather than
stretching a single day across its column. The five usual result values fit in
compact label / gauge / count rows without nested scrolling. Longer date/result
lists can scroll with native controls. Tablet/mobile layouts wrap existing
components without document overflow. The chart keeps up to 14 dates and includes
a selected older date.0821 retains its fixed 312 members with no date chart.

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

The source line shows the last successful check and the number of result changes
in that observation. The latter counts updates to existing members, not new
members or an inferred annotation timestamp. A later successful check with zero
changes means the observed values are unchanged; stale/error states remain visible.
The API stays read-only and no-store, with bounded local snapshot reads and no
request-time Trail queries. Polling updates freshness even when gallery rows stay
identical and preserves existing card DOM when its contents do not change.
