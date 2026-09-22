# Dashboard product UX acceptance

Recorded: 2026-09-22 (Asia/Shanghai)

## Runtime

- Branch: `codex/dashboard-product-ux`
- UX smoke database: `manual_dashboard_product_ux_20260922`, cloned logically from S6 v2.
- UX smoke source: `21d001e0cd6253e78d9eb6ebe48f44accb05e253` (product code; final branch also contains report/docs commits).
- 8786 health: `ok=true`, base path `/manual-s6`; writers, sync, Batch, AutoTriage and D-Chat disabled.
- Production 8785 was not touched.

## Checks

| Check | Result |
| --- | --- |
| Sidebar groups | PASS: Case 标注, 判错复核, 模型评测, 系统管理; Campaign/Collection ordinary nav removed. |
| Product routes | PASS: `/labeling-experiments`, `/labeling-summary`, `/multi-run-evaluation`; old `/campaigns` purpose and `/run-collections` aliases remain parseable. |
| User terminology | PASS: ordinary multi-run page uses 多 Run 评测 / 评测项目, with internal IDs/hashes behind technical details. |
| Review task separation | PASS: Review workspace has a task drawer; shared label is a read-only layer and no model-review completion is used for shared labels. |
| Labeling flow | PASS: existing S4 purpose=labeling API is reused; UX guide presents dataset/range, people, overlap, preview and create steps. |
| Read-only behavior | PASS: existing verified-admin gating remains; evaluation write controls are hidden or disabled for anonymous sessions. |
| Frontend contracts | PASS: 68 frontend contract tests and 4 base-path tests. |
| JavaScript syntax | PASS: routing, campaigns, run-collections and work-split modules. |
| Cloud suite | PASS: 578 passed, 1 skipped in 56.03 seconds on disposable UX suite DB. |
| Browser | HTTP/DOM PASS through localhost tunnel: UX route markers, multi-run page, experiment link and review task drawer present. CUA kernel timed out, so no screenshot was captured. |

The UX worktree does not add a migration. The final cloud pytest and visual/DOM smoke result will be appended after the exact UX source is running on 8786.

## Final HTTP/DOM smoke

`/manual-s6/health` returned `ok=true` with the UX source. HTML at `/manual-s6/multi-run-evaluation` contained `runCollectionsPage`, `runCollectionsNavButton`, `labelingExperimentsNavButton`, `reviewTaskDrawer` and the multi-run route. Production 8785 stayed unchanged.

## Information-architecture correction

The first UX pass introduced an extra Model evaluation group and exposed the project manager as a primary navigation item. That was reverted after review. The final sidebar follows the stable product hierarchy: Case 标注 (with 实验分配 and 标注汇总), 判错复核 (including 任务分配、原因聚类、问题排除、模型结果、Run 对比、批次预测), 意图标注 unchanged, and the existing system section. The multi-run path is now a user-facing Run 对比 flow/alias; internal Collection/Workset/Revision terms remain in technical details and old deep links remain compatible.
