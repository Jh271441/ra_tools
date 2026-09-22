# Dashboard product UX acceptance

Recorded: 2026-09-22 (Asia/Shanghai)

## Runtime

- Branch: `codex/dashboard-product-ux`
- Deployed UX source: `571526c494603924fc0c7aad93598872ea47ac8a`
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
| Removed navigation | PASS: no independent 模型评测 group and no `runCollectionsNavButton` are present in the rendered DOM. |
| Product routes | PASS: `/case-labeling`, `/labeling-experiments`, `/labeling-summary`, `/review-assignments`, and `/run-comparison` render their intended pages. |
| Legacy route | PASS: `/run-collections?baseline=0508` renders the existing Run 对比 page and activates `runComparisonNavButton`; the query string remains intact. |
| Review task separation | PASS: the Review workspace retains its task drawer; shared labels remain separate from model review completion. |
| Read-only boundary | PASS: existing verified-admin gating remains. The temporary loopback smoke identity is verified, mapped to the explicit UX ACL row, and is not available to production or remote clients. |
| Frontend contracts | PASS: 68 frontend contract tests, 4 base-path tests, and 13 identity/access tests. |
| Syntax | PASS: shell launch/restore scripts and the changed JavaScript files parse successfully. |
| Full cloud suite | PASS: 579 passed, 1 skipped in 61.84 seconds on source `571526c`, using schema `ux_suite_571526c` inside the dedicated UX suite database. |
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

## Recovery

`scripts/restore_s6_8786.sh` restores the frozen S6 v2 source on loopback 8786.
Before stopping the UX listener, it verifies the pinned production PID/build and
that port 8786 belongs to the UX smoke root.
