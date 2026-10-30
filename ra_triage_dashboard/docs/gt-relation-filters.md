# GT relation filters

Status: local candidate, not deployed (2026-10-30, cache `manual-triage-719`).

## UI

- Review keeps its existing two desktop rows and column count. The existing
  shared-label-state dropdown is labeled “标注状态 / GT / Label state / GT”.
  It reuses the shared grouped multiselect: GT relation first, label state second.
- Case labeling has a separate “GT 关系 / GT relation” shared multiselect. Its
  desktop grid has eight equal units; Issue search and task span two units,
  and Reset fills the end of the second row.
- Ordinary fields remain equal width. Phone/tablet layout remains owned by
  `mobile.css`. Field-local info uses a 1em icon on desktop and 44px mobile target.

## Contract

`gt_relation` accepts comma-separated `matches_gt`, `differs_from_gt`, and
`fills_missing_gt`. Empty / `all` means unfiltered. Invalid values return HTTP 400.
Selected relations use OR; relation and label-state/other filters use AND.

Compare the current resolved Case label with the selected immutable GT.
Unresolved, conflicting, stale, or noncanonical label results never match these
three relations. Missing GT means an empty GT; noncanonical raw GT observations
such as `out_of_scope` are unknown, not missing. Model correctness remains a
separate Review filter.

Review compares the shared Issue conclusion. Case labeling retains the existing
selected-task projection when a task is selected, otherwise the shared Issue
projection. Filtering occurs before pagination, detail queue, counts, clusters,
exports and filter-based task membership. No stored GT or label is changed.

URL, language changes, reset and assignment source links preserve/separate
`label_state` and `gt_relation`. Case labeling summary links and export previews
carry the same relation filter.

## Validation

- Integration regression covers Review and Case gallery, all queue IDs,
  summaries, clusters, GT export selection, invalid values, state/relation AND,
  raw GT, and filtering across the 400-row candidate boundary.
- Final local full suite: 1117 passed, 14 skipped, 165 subtests passed.
  Focused GT relation checks: 4 passed.
- Actual local source modules were exercised in the Codex side browser with
  synthetic state: Review and Case, 1440px desktop two-row layout; 320px/390px
  English/light dropdown bounds and selection preservation; Chinese/dark
  desktop screenshots. Case info targets were 11px desktop and 44px mobile.
  These are browser viewport checks, not real-device or signed-in production
  acceptance. No production deployment occurred.
