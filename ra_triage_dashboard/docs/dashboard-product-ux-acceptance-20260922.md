# Dashboard product UX acceptance

Recorded: 2026-09-22 (Asia/Shanghai)

## Runtime

- Branch: `codex/dashboard-product-ux`
- Deployed UX source: `12ef95ed765f314db11eff84968469eab17bb927`
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
| Full cloud suite | PASS: 580 passed, 1 skipped in 61.58 seconds on source `12ef95e`, using schema `ux_suite_12ef95e` inside the dedicated UX suite database. |
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

## Recovery

`scripts/restore_s6_8786.sh` restores the frozen S6 v2 source on loopback 8786.
Before stopping the UX listener, it verifies the pinned production PID/build and
that port 8786 belongs to the UX smoke root.
