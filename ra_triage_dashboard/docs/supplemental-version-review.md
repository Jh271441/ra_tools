# 版本数据的独立差异复核任务

2026-10-30：用户明确要求将既有 1009 TE/RD 差异任务原地切换为联合复核。
这类显式任务通过 `filter_json.supplemental_review=true` 标识，保留自己的冻结
成员、原任务 ID、负责人、GT 引用、配置历史和独立提交进度。

任务分配的版本分组保留该标识的同 Run 独立任务；普通源任务仍按原规则合并，
canonical 版本任务不重复计入。原每日版本任务的创建、追加和所有权策略不变。

任务入口先核验冻结成员均属于声明的版本数据集，再使用 `version-YYYYMMDD`
公开数据集 ID，避免原来源 scope 未注册为公开 ID 时遗漏部分成员。空成员或越界
成员失败关闭。原 Issue scope、RD 标签和 GT 不被修改。

本机标准库测试 12 项覆盖分组、严格布尔标识、冻结跨来源成员、空/越界范围；
发布仍执行完整云端测试与隔离灰度。界面复用现有联合复核与任务分配组件。

## 旧查询链接兼容（2026-10-30）

旧联合复核链接曾把全部冻结成员的来源 ID 与未注册的
`manual_sidecar_version_YYYYMMDD` 混合传入 `baselines`，后者被正常的白名单
解析丢弃，导致同一个 20 条任务只查到旧来源中的 10 条。

共享 baseline 解析器现在仅在以下条件全部满足时恢复公开版本选择器：
请求绑定一个显式 supplemental 任务；全部非空冻结成员属于声明的已注册版本；
请求的完整 token 集合恰好等于该任务成员的全部来源 ID/scope 集合。
正常来源子集、额外数据集、未知 scope、普通任务不会被改写。任务、负责人、
搜索、比较关系等仍按原条件取交集；分页不会改变总数。POST 筛选也显式传递
任务 ID。列表、Issue ID 队列、负责人统计和导出共用此解析。

The shared baseline resolver upgrades only an exact complete legacy provenance
selection for a validated supplemental task to its registered public version ID.
All nonempty frozen members must belong to that version dataset. Deliberate source
subsets, extra datasets, unknown scopes and ordinary tasks retain existing behavior.
Task membership and business filters still intersect the result. Ten rows per page
must retain a total of twenty, including across ID queues, facets and CSV export.
