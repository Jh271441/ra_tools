# Dashboard product UX plan

## Scope

This branch starts at frozen S6 `f1f31e7` and keeps S1-S6 data/API contracts intact. It changes navigation, copy, routing aliases and progressive disclosure only; no schema migration is added.

## U1 information architecture

- Case 标注 group: Case workspace, labeling experiments, labeling summary.
- 判错复核 group: Review workspace, reason analysis, issue exclusion.
- 模型评测 group: Runs, pairwise comparison, multi-run evaluation, batch prediction.
- System group: status and access.
- `/labeling-experiments`, `/labeling-summary`, `/multi-run-evaluation` are product routes. `/campaigns?purpose=labeling`, `/campaigns?purpose=model_review`, and `/run-collections` remain compatible aliases.

## U2/U3 domain separation

Existing S4 Campaign APIs are reused. Labeling purpose is presented as 标注实验 and its existing analysis becomes 标注汇总. Model-review purpose is represented as 复核任务; the Review workspace retains Run/task filters and shared-label read-only projection.

## U4 multi-run evaluation

The existing Run Collections implementation is presented as 多 Run 评测 / 评测项目. A five-step guide and technical-details disclosure keep the main flow focused on Run selection, Case range, reference version, comparison Run, and results. Pairwise remains in its original page with a collapsed project manager.

## U5 compatibility and gating

Base-path routing, historical query keys, read-only controls, hidden/grid CSS behavior and legacy links remain covered by the frontend contract tests. UX smoke runs against a logical clone of S6 v2 on loopback 8786 with writers, sync, Batch, AutoTriage and D-Chat disabled.
