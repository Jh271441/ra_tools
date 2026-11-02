# GT relation filters

Status: deployed 2026-10-30 12:58:50 CST, cache `manual-triage-719`.

Release: `ab015dd46905f1524d4b0e5cb4c7bd0c87afce95`; receipt:
`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261030T045536Z-ab015dd46905/result.json`.

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
  acceptance.
- Production release: 1169 passed / 7 skipped; isolated SQLite gray and exact-SHA
  PostgreSQL production gates passed. Existing writer/Batch policy was preserved.
  Read-only Review relation queries and invalid-value HTTP 400 passed; five served
  static assets matched the release bytes. In-app tab lookup and new-tab creation
  timed out, so signed-in production visual/Case API acceptance is not claimed.

## 原因聚类与标注汇总（2026-11-02）

- 原因聚类新增“标注状态 / GT”分组多选；标注汇总原“结果状态”入口升级为
  同一个共享控件。与 Review 共用分组、选项文案和多选交互，支持全选、反选、
  清除、键盘、运行时中英文切换及手机视口定位。
- 两个页面分别保存其原有枚举：原因聚类为 `label_state`，标注汇总为 `status`；
  GT 关系仍独立保存为 `gt_relation`。不改变数据库枚举或标注内容。
- 原因聚类的标注状态与 GT 关系基于当前共享 Issue 结论，与 Review 使用同一个
  状态判定；GT 关系使用当前所选 GT，非标准 raw GT 不视为 GT 缺失。
  只筛已有 Review 原因，不把没有 Review 的 Issue 合成为原因记录。
- 条件在聚类统计、GT 更新统计、明细分页和 CSV/XLSX 导出前生效。GT 关系组内
  OR，标注状态组内 OR，两组及其他条件之间 AND。分享 URL、刷新、语言切换、
  分页及导出保持有效选择；条件或每页条数变化回到第一页。
- 标注汇总保留既有任务投影和“明细仅展示已有提交”的口径。未标注可作为状态
  条件选择；这类 Issue 不凭空生成标注依据。分页复用 `.case-pagination`、共享
  增强下拉、`CASE_PAGE_SIZES` 和默认条数，页码跳转拒绝非整数并限制到有效范围。

Reason analysis and labeling summary reuse the Review grouped Label state / GT
multiselect. State and GT relation are independent URL/API fields, OR within each
group and AND across groups. Reason filtering uses the current shared Issue label
and selected GT before aggregates, pagination and all CSV/XLSX exports. It retains
existing Review reason candidates and never fabricates a reason for an untouched
Issue. Labeling summary keeps its existing task projection and submitted-detail
semantics. Locale changes preserve focused open controls and valid selections.
