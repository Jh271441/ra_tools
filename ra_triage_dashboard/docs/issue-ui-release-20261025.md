# Issue 界面发布 · 2026-10-25

2026-10-25 01:36:45 CST 已发布 `252a86b73daa05130600e69968eee867d6ec6526`，静态缓存648。
包含743px图库两列/手机单列、紧凑裁决摘要、Issue排除取消Run依赖，以及场景描述默认折叠。个人标注卡片不变。

837 passed / 5 skipped；隔离SQLite灰度18789通过。生产PostgreSQL健康，schema56，身份、writer、通知配置保持原值。实际静态资源逐字节匹配候选。未调整调度、模型、媒体队列或任务分配。

发布记录：`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T173440Z-252a86b73daa/result.json`。
回滚版本：`bdee0b525001b411712b97afcdc3b27e99967e18`。既有canonical checkout及8786实例保留。

验收：Codex内置浏览器登录态生产页面。743px图库由5列变为2列；1440px中文深色裁决摘要和排除页；390/320px英文浅色排除页，无页面横向溢出（scrollWidth379/309）。排除页没有Run选择器，1009数据集显示26个本地候选。没有提交标注、裁决或Trail写入。

场景描述展开/折叠、键盘及语言切换已在发布前隔离数据验收；本次线上抽查cn36854187无描述，正确不显示入口，未将其计作线上展开态验收。完整发布前矩阵见reports/issue_exclusion_ui_20261025、scene_description_20261025、gallery_responsive_20261025。

线上截图：`reports/issue_ui_release_20261025/`。浏览器响应式测试，不是真机；测试后恢复原中文深色及默认视口。

原manual-te-progress中的保存保留视频/短文案修改未包含在本次发布。
