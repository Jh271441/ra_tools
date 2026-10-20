# Run Review 撤销与原因分析

Review 历史里的删除图标对新的 Run 复核执行逻辑撤销。只有已验证 writer 可以撤销自己的版本，管理员可以撤销他人的版本；迁移的历史证据仍只读。

`POST /api/cases/{issue_id}/model-reviews/{annotation_id}/revoke` 要求 `expected_head_id`。服务端锁定 Issue，核对当前 Run/Campaign/reference/复核人命名空间，再写 `model_review_revocations`。重复撤销幂等，旧版本并发冲突返回 409。原复核、附件、联合提交及 Case 标签保留；有效历史与原因分析排除已撤销版本。撤销 head 后恢复同命名空间上一有效版本，无剩余则清除 head，并重算联合任务的模型进度。标签确认及标签汇总不随 Run 撤销丢失。

原因分析包含单人分配的现代联合复核任务。精确任务筛选只取该 Campaign/reference 下的有效 head，不回退到任务外复核。无任务或 Run 筛选时保留汇总语义。原因分析任务筛选显示任务名称，仍受当前数据集和 Run 约束，空选项时提示切换范围。判错复核的任务入口则跨数据集加载当前账号的进行中任务；选择任务复用任务卡片导航，清除旧筛选并锁定任务数据集与 Run。

Case 标注原因和 Run 判错原因属于不同域。前者在标注汇总，后者在原因聚类；本修复不复制两者。标注汇总“未提供场景描述”指 Issue 元信息缺失；“与 GT 不一致”指标签与当前 GT 的差异。

## Schema 054 与发布

新增审计表并以同列同类型替换 `review_records` 的模型分支，排除撤销记录。SQLite 启动时刷新视图；PostgreSQL 使用 054 migration。旧版本仍能读新视图，撤销不改变原始 revision 或 labels，因此应用回退保留 schema 054 和当前数据，不恢复旧快照覆盖用户新提交。

本迁移不属于通用 additive allowlist。发布使用独立工作树和精确已推送 SHA，通过现有 deploy_cloud helper 执行完整测试、独立灰度、停写、最新逻辑备份、checksum、临时库恢复与全表计数验证后再应用。只允许本次审阅的 054 文件；保留生产环境、旧代码恢复目录及已有端口服务，不修改通用发布器白名单。生产验收只读，不撤销真实用户数据。
