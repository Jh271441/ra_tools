# Dashboard product UX acceptance

Recorded: 2026-09-22 (Asia/Shanghai)

## Runtime

- Branch: `codex/dashboard-product-ux`
- Deployed UX source: `9d7e3818cf0339381d47b8376a3dd1e69a32c6d6`
- UX smoke root: `/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922`
- UX smoke database: `manual_dashboard_product_ux_20260922`, cloned logically from S6 v2.
- UX endpoint: loopback `127.0.0.1:8786`, base path `/manual-s6`.
- Health: `ok=true`; writers, sync, Batch, AutoTriage, and D-Chat remain disabled.
- Production `8785` was not restarted or changed.

The UX smoke alone enables `DASHBOARD_SMOKE_LOOPBACK_ADMIN_ENABLED=true` with
`DASHBOARD_SMOKE_LOOPBACK_ADMIN_USERNAME=ux-smoke-admin`. Startup rejects this
mode unless the process binds loopback on port 8786 or 8787. Production does not
set either variable.

## Acceptance results

| Check | Result |
| --- | --- |
| Sidebar hierarchy | PASS: Case 标注 contains Case 标注、实验分配、标注汇总. 判错复核 contains 判错复核、任务分配、原因聚类、问题排除、模型结果、Run 对比、批次预测. 意图标注 and 系统管理 retain their stable items. |
| Sidebar child alignment | PASS: all three Case items share one common item layout. At the default 240px width their item/icon/text x coordinates were 26/33/72; at 320px all three shared 21/28/67. Active-state switches did not move them. Collapsed mode centered all three icons at x=16.5 in the 64px rail. |
| Removed navigation | PASS: no independent 模型评测 group and no `runCollectionsNavButton` are present in the rendered DOM. |
| Product routes | PASS: `/case-labeling`, `/labeling-experiments`, `/labeling-summary`, `/review-assignments`, and `/run-comparison` render their intended pages. |
| Legacy route | PASS: `/run-collections?baseline=0508` renders the existing Run 对比 page and activates `runComparisonNavButton`; the query string remains intact. |
| Review task separation | PASS: the Review workspace retains its task drawer; shared labels remain separate from model review completion. |
| Model Review status | PASS: the user-facing status set is 待开始 / 复核中 / 已完成. Shared Case conflict and GT 待复核 are separate fields; completion remains rejected while a shared label is conflicting or stale. Existing stored history is not rewritten. |
| Historical label copy | PASS: five per-dataset batches named `历史判错复核标签导入 · <dataset>` are `已导入`. Only label votes and frozen GT state were copied; reason, missing evidence, task progress, comments and attachments were not copied. |
| Reviewer deduplication | PASS: same reviewer/same label across Runs creates one vote with all sources; same reviewer/different labels creates a conflict; different-reviewer disagreement remains pending adjudication. |
| Idempotency | PASS: the second smoke import returned `duplicate=true` for all five batches and inserted zero votes and zero sources. |
| Review preservation | PASS: `annotations` 211, `review_comments` 13, `model_review_revisions` 9 and `model_review_heads` 9 retained identical row counts and table SHA256 values before and after import. |
| Read-only boundary | PASS: existing verified-admin gating remains. The temporary loopback smoke identity is verified, mapped to the explicit UX ACL row, and is not available to production or remote clients. |
| Frontend contracts | PASS: 68 frontend contract tests, 4 base-path tests, and 13 identity/access tests. |
| Syntax | PASS: shell launch/restore scripts and the changed JavaScript files parse successfully. |
| Combined workflow compatibility | PASS: existing Campaigns remain `model_review_only`; new tasks explicitly persist `model_review_and_case_label`. Direct browsing still defaults to model Review only. |
| Atomic combined submission | PASS: one API transaction wrote independent `label_revisions` and `model_review_revisions`, linked by `submission_group_id`; stale Case state returned 409 with no row-count change in either domain. |
| Cross-Run Case vote | PASS: Run A created one Case vote; Run B acknowledged the same vote without a duplicate revision. Both Run-bound model Reviews remained independently completed. |
| Combined progress | PASS: each task reported separate model-review and Case-label markers plus one overall completion. Shared-label conflict/GT review did not reduce model Review completion. |
| Full cloud suite | PASS: 587 passed, 1 skipped in 74.09 seconds on source `bb59a84`, using schema `ux_suite_bb59a84` inside the dedicated UX suite database. |
| Browser | PASS: the Codex in-app browser read the live accessibility tree and rendered DOM through the localhost tunnel. It verified the visible sidebar order and all routes listed above. |

## Browser evidence

The live browser session reported these visible groups in order:

1. Case 标注: Case 标注, 实验分配, 标注汇总
2. 判错复核: 判错复核, 任务分配, 原因聚类, 问题排除, 模型结果, Run 对比, 批次预测
3. 意图标注: 意图标注, 实验分配, 标注汇总
4. 系统管理: 系统状态, 用户管理

The old `/run-collections` deep link visibly showed title and heading `Run 对比`,
rendered `runComparisonPage`, selected `runComparisonNavButton`, and contained no
independent Run collection navigation item.

The live 标注汇总 page exposed a 来源 selector with `历史判错复核`, filtered to
the imported batch, and showed imported, resolved, GT-review, conflict and pending
adjudication counts. The 0508 row displayed 45 scanned Reviews, 39 effective label
sources, 30 reviewer-dedup votes, 22 resolved Cases, 15 GT-review Cases and 2
conflicts/pending adjudications.

## Smoke label import

| Dataset | Reviews | Label sources | Dedup votes | Resolved | GT 待复核 | Conflict / pending adjudication | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0206 | 50 | 43 | 41 | 33 | 6 | 3 | 7 |
| 0508 | 45 | 39 | 30 | 22 | 15 | 2 | 6 |
| 0522 | 1 | 1 | 1 | 1 | 0 | 0 | 0 |
| 0626 | 12 | 11 | 9 | 7 | 5 | 1 | 1 |
| 0821 | 103 | 101 | 87 | 42 | 30 | 10 | 2 |

The smoke database contains 172 imported reviewer vote rows, 197 provenance
sources and 122 imported Case-state rows. All 172 generated label revisions have
empty rationale, Tags and evidence gaps and `is_excluded=false`.

## Combined Review smoke

- Migration count: 52.
- Case / Run fixture: `cn34006269`, Runs `ec1724da…` and `b9d192fe…`.
- Combined Campaigns: `campaign-3be7739d…` and `campaign-a9eea9fc…`.
- Run A submitted a new Case vote and completed its model Review.
- Run B reused the same Case vote through acknowledgment and completed a separate
  model Review; the Case revision count did not increase.
- Changing the current user's vote appended a normal revision. The historical
  reviewer source stayed intact, yielding a shared-label conflict while the Run B
  model Review remained completed.
- A deliberately stale Case token returned HTTP 409. Label and model revision
  counts were identical before and after the rejected request.
- Historical `annotations` stayed at 211 rows with SHA256
  `d6209dd1e40db27def695b4f1e500ad37beef1e09d5bbed630c73cedc94ef0d1`;
  `review_comments` stayed at 13 rows with SHA256
  `a7845cef2a5aed281e2d1c81c3baab67f8c7417b500f2166d0847fcb941031b7`.

The live browser verified cache `manual-triage-491`. Default Review mode hid the
Case editor and disabled model save with no Run. Direct combined mode exposed a
Case-only save with no Run. The combined Campaign deep link locked the workflow
selector, showed the fixed GT snapshot, current shared conclusion, current vote,
other-source count and cross-Run notice, and displayed independent `GT待复核` and
`已完成` statuses above the atomic `提交联合复核` button.

## 0508 Case-label activation

The isolated 8786 scope `release0508_1071_20260729` was activated through the
copy-only guard in source `32a6eda51c5ab3e750624ac02c9aac2d03635f58`.

- Active GT snapshot: `gt-cb78d260a89666b68a271fdc0b56e391321892747cbc87222b5f723e865e0438`.
- Membership: 108 snapshot members / 108 scope Issues, all 108 with valid GT.
- Import batch: `label-import-7172bf0fcb45d7aeaaf1d7cd`, status `imported`.
- Inventory fingerprint: `4395bc444b9439c7166087444a98a76402d6da2d26a55cc7f3484df5535602b9`.
- Reconciled rows: 31 imported votes, 41 source records and 25 imported Case states.
- Activation state: epoch 1, policy `legacy-case-label-copy-v2`, status `active`.
- Receipt: `s6-shadow-5d7f2a35f3244c959737da7d098ae53b`, status `pass`, zero diffs.
- 0206 remains inactive and has no `labeling_scope_state` row.

Browser verification showed `当前已激活数据集 · 108 个 Case`, GT membership
`108/108`, no inactive-state message, and a 20-card first page with unlabeled
Cases rendered as `标注 —` alongside imported labels. The 0508 Review gallery
still showed 108 Issues and the existing shared `GT 待复核` / conflict states.

The activation did not change source Review data. Before/after row counts and
SHA256 values were identical for `annotations` (211), `review_comments` (13),
`model_review_revisions` (12) and `model_review_heads` (11).

## Legacy task deep-link acceptance

Exact input:

`/review?work_split=split-0718ea6745e64a589ad5e9b8bf2512a5&baselines=0522`

The task-context API resolved this as a legacy no-Run Split with 108 assignments,
scope `release0508_1071_20260729`, no Run and `model_review_only`. The browser
replaced the URL with `baselines=0508`, displayed all 108 assigned Issues, and
rendered `历史任务 · 108` as a compact field in the existing filter bar. The task
picker stays closed until explicitly opened, and the adjacent × exits the task.
No banner, blank gallery, 500 or anonymous “1 item failed” toast remained.

- Legacy/no-Run membership is read-only and does not create or fake a model Review.
- The Run picker is locked until `退出任务范围`; task creation is disabled without
  a Run and points Case-only work to Case 标注 > 实验分配.
- Selecting 0522 from the dataset picker exited the task, removed `work_split`,
  unlocked the Run picker and loaded 10 Cases.
- A missing task rendered an inline error card with reason, task ID, Retry and
  Exit controls; gallery skeletons were removed and all actions stayed disabled.
- Initial failures now identify the failed request by name.

## Unified select controls

Cache `manual-triage-500` replaces the newly added native dropdown surfaces with
the shared `ui-select` trigger/panel while retaining hidden native selects. This
covers task mode, Review page mode, labeling-summary source, Run-collection
project/revision/reference selectors and the dynamic model Review status.

Browser checks covered click and Arrow/Enter/Escape keyboard use, selected/check
state, disabled help text and English relabeling (`Model review only`,
`All sources`, `GT snapshot (frozen on create)`, `Completed`). The task-mode
control measured 38px high and 340px wide in the Review assignment dialog, with
no operating-system native popup.

## Minimal Review compatibility acceptance

The final UI follows the production `5fdc41ba` Review density. Model-only Review
shows exactly one read-only expected output derived from the resolved shared Case
label; missing, conflicting or pending labels remain `待确定` with a separate status.
The editable expected-output control appears only in combined mode and is excluded
from the model-only submission payload. Historical no-Run Review keeps the reason
and discussion read-only and exposes real `选择 Model Run` and `打开 Case 标注`
actions. The first action exits the task and opens the existing Run picker; the
second opened the same Issue in Case labeling on the 0508 dataset.

Actual browser checks covered ordinary Gallery, the exact legacy Split deep link,
historical no-Run detail, a Run-bound model-only detail and combined detail at
1280 and 1440 widths with collapsed and expanded sidebars. Combined mode retains
the existing Issue-tags and expected-output controls with only a small `联合复核`
badge; no full-width status bar or GT snapshot string is rendered. Empty async
Trail-link containers occupy no title space; a browser DOM-driven late metadata
check showed `RA 录屏` and `RA Event` links appearing after hydration. Browser
console errors were zero.

The UX PostgreSQL row counts remained unchanged after the UI-only deployment:
`annotations=211`, `review_comments=13`, `model_review_revisions=12`, and
`model_review_heads=11`.

## Recovery

`scripts/restore_s6_8786.sh` restores the frozen S6 v2 source on loopback 8786.
Before stopping the UX listener, it verifies the pinned production PID/build and
that port 8786 belongs to the UX smoke root.
