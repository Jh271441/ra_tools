# Version composition and TE progress

The version page shows the occurrence-date TE chart directly. Each date uses its
own target denominator; clicking a date also scopes the gallery and version
composition. The chart keeps up to 14 dates and includes a selected older date.
0821 retains its fixed 312 members and has no occurrence-date chart.

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
