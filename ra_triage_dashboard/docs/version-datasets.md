# Version datasets

## Arrival ordering and first paint (2026-10-23)

Version gallery and TE gallery default to latest platform arrival (`version_dataset_items.first_seen` descending, deterministic Issue tie-break), independent of the case occurrence date. Version gallery also supports source update order and Issue order; TE supports occurrence date and Issue order. Sort precedes pagination and is URL-restorable. Historical bootstrap records may share one arrival timestamp; that timestamp is the registry import time, not a reconstructed historical upload time.

The TE daily chart remains grouped by CST occurrence date. Late cases backfill older dates; bars are current completion ratios, not daily arrivals or labels. Sorting does not change the TE denominator, filters or `ra_review_result_new` authority. Export uses the same scope and sort.

Version first paint is independent of global Review/GT baseline initialization and never switches the global baseline. Four compact counters show candidates, published cases, review targets and missing source metadata; sampling overrides low confidence for the displayed disjoint counts. Cards expose prediction/confidence, owner, trigger, arrival and occurrence time. The original Run/Campaign combined-review links are preserved.

Items are paged at24. Thumbnails start near the viewport with at most4 active loads; missing media retains a placeholder. Unchanged polls retain card/image DOM; hidden tabs pause, stale requests are discarded, failed refreshes retain the prior result, and import history loads only when expanded. All modified selects use the shared enhanced component. No database migration or collector schedule change is part of this UI release.
