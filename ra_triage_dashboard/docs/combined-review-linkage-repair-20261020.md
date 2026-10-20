# 联合复核任务关联修复

修复基于实测生产提交 `e9e03cfbd4d8a37c729d6f07e38ffaa61dd779e0`。
代码在隔离工作树修改；未修改运行中的 release，未发布，未对生产执行关联写入。

## 根因及行为

- 详情的 `review_assignment` 缺少 `purpose`。单人任务 `mode=single` 无法通过前端
  `reviewWorkSplitBinding()` 的判断，最终把 `campaign_id` 清空。
- 详情预取缓存只按 Issue 索引，可能跨 Run / Campaign 复用旧分配上下文。
- 标注任务列表和查询只支持旧的 `task_kind=labeling`，联合复核的共享 Case vote
  本身又不存储在该任务的 `label_cases.task_id` 下。

新行为：

1. 详情返回 purpose；联合提交要求显式 URL 任务、本人分配、Run、workflow 和加载的
   context 完全匹配。任务上下文不一致报错，任务外浏览不会自动归入当前最新分配。
2. 详情缓存按包含 Run / Campaign 的完整请求路径索引。迟到 context 和保存响应
   不覆盖用户已切换到的 Issue / Run / Campaign。
3. `GET /api/labeling/tasks?include_combined=true` 供标注汇总使用。默认的 Case 标注
   任务入口保持原有任务集合，联合任务的明细链接回到对应联合复核页。
4. 联合任务通过冻结 `campaign_issue_members` 确定范围，通过
   `combined_review_progress.case_label_revision_id` 读取已提交/确认的原始标签版本。
   仅计算仍在该 Issue 分配名单中的复核人，不吸收普通任务外提交或尚未在任务中确认的
   后续标签。全部标注继续使用原有共享标签投影，不重复制造 Case vote。
5. 汇总支持跨数据集任务；范围、人员分母及结果均受所选数据集约束。
   静态缓存版本为 `manual-triage-568`。

## 生产只读核查

Campaign：`campaign-1c98e45bd1e04b638d77214b002a5abf`

Run：`adec910f-e04b-4707-92c5-498e03fe53cb`

- `jasperchen`、`liangxianghui` 各 156 条，交叉分配 0。
- 312 条来自 `release0821_1242_20260908` 的 62 条及
  `manual_sidecar_0821-review-extra` 的 250 条；仅选 0821 主数据集时应显示 62 条。
- `cn35638967` 在 2026-10-20 10:54:09 +08:00 分配给 `jasperchen`。
- 原始提交 `5f7b3c11-6a30-4350-bf9e-65256721d0fe` 创建于
  2026-10-20 11:03:50 +08:00，campaign 为空，标签版本 2337、模型复核版本 2154。
- 修复候选对真实数据库的只读查询可发现此联合任务，完整范围为 312，
  两人分母各 156；当前仍为 0 完成。本次没有执行生产修复。

## 可审计、幂等的关联工具

`scripts/repair_combined_review_association.py` 默认 dry-run，不初始化或迁移数据库。
以对应环境的私有数据库 URL 文件作为输入，凭据不放在 argv 中。

```bash
python ra_triage_dashboard/scripts/repair_combined_review_association.py \
  --database-url-file /path/to/private/postgres_url \
  --submission-id 5f7b3c11-6a30-4350-bf9e-65256721d0fe \
  --campaign-id campaign-1c98e45bd1e04b638d77214b002a5abf \
  --label-revision-id 2337 \
  --model-review-revision-id 2154 \
  --actor codex \
  --reason confirmed-task-context-loss-20261020
```

此精确清单的已验证 fingerprint：
`b82c2a4e4e7a072dea57745b060079ae48e999b13127f953bdf33b406fb6eb67`。

正式执行需在相同参数上增加 `--apply --expected-fingerprint <dry-run 输出值>`，
并保存 JSON 回执。执行前重新确认运行环境/数据库身份和最新 dry-run。
此工具是定点修复，不扫描并自动认领其他任务外提交。

写入在一个事务中完成：

- 原提交、标签版本及任务外模型复核均保持不变。
- 新增目标任务中的模型复核版本，复制指定原版本内容。
- 新增 `case_action=acknowledged` 的联合提交，引用原始标签，无新增 Label vote。
- 新提交的审计来源含原 submission ID、两个版本 ID、操作人、原因和清单 fingerprint。
- 新增对应 progress 行，使用原始提交时间作为业务完成时间。
- `association-repair:<原 submission ID>` 幂等键防止重复关联或跨任务重复认领。
- 错 Run/Issue/人、错误版本、晚于原提交的分配、后续转派、失效任务、被抑制的标签、
  已存在的目标 Review / progress 均拒绝自动修复。并发冲突事务回滚后重新 dry-run。

修复后该条应计入 `jasperchen` 的 1/156 和任务的 1/312，另一人的进度不变。
这是假设执行时没有其他任务提交的预期，不是已完成生产修复的声明。

## 验证

- Dashboard 完整测试：642 passed，5 skipped（其中 PostgreSQL 集成项需专用环境）。
- 最后增加任务外绑定保护及跨数据集用例后，受影响测试：48 passed。
- 独立临时 PostgreSQL 库：4 项任务绑定/汇总、关联修复幂等及拒绝覆盖、
  两人非交叉分配回归通过；临时库已清理。
- 浏览器使用两条合成 Issue 的独立回环实例，外部写入/同步关闭，身份为测试 fixture：
  任务入口提交成功；切换到另一人 Issue 明确报错；返回本人 Issue 后再次提交；
  任务为 1/2，jasperchen 1/1，liangxianghui 0/1；联合任务出现在标注汇总下拉，
  标签和依据正确，Issue 回跳保留 Run / Campaign。浏览器控制台无 error/warn。
- 合成实例及临时 SSH 转发已停止。生产发布和上述定点写入均尚未执行。
