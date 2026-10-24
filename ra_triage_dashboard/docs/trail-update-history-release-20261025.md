# Trail 更新记录发布验收

2026-10-25 03:56:58 CST 发布成功。用户明确授权 Trail 更新记录及入口调整一起上线。

- 生产运行 SHA：`961376d3f7ae19068c2c26286891f80290729405`；cache654；PostgreSQL schema57。
- 上一版／应用回退 SHA：`20e86effd5d24df9142c50ca102a5080a3dc194d`。当前主干的标注汇总 GT 比例图、既有 Issue UI、Cron 功能保留。
- 入口：系统管理 → Trail 更新记录，`/manual/trail-update-history`。问题排除两种提交方式成功后，弹窗与页面均提供本次操作详情链接。
- `DASHBOARD_TRAIL_ROLLBACK_ENABLED=false`。原有身份、Trail 排除写入、Batch、GT 同步及通知策略保持不变。没有回放操作、执行真实 Trail 恢复或发送测试通知。
- 现有 3 条旧历史导入为 legacy，逐条确认不能恢复。完整前后快照从本版本接入后的两条工作台写入路径开始积累；外部来源未接入。

## 迁移与恢复保障

生产旧 canonical checkout 的本地文件与既有 8786 实例均保留。精确版本发布器在独立 worktree 和 18789 上完成灰度，复用 deploy_cloud 锁、测试、进程、健康和应用回退门禁。

停止 Dashboard 后创建新鲜逻辑备份并备份附件，执行校验、临时恢复和内容指纹比对；在恢复库先演练 migration057，再应用到生产。97 张原有业务表的内容指纹在演练与生产应用前后均一致，schema/change-revision 元数据除外。6 个审计不可变／版本推进触发器验证启用。

- 迁移文件 SHA-256：`54008df2790bc6910495524f0ae622da3e448248c9fe910b5a4195281a677e3a`。
- 备份 SHA-256：`3bf6e6522bc5b64cc7f20efa76754642983803e4330d74fc9f11392ed528a1c2`。
- 永久备份及演练回执：`/volume/home/workspace/ra_triage_dashboard_deploy/migrations/20261024T195327Z-961376d3f7ae/`。
- 发布回执：`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T195327Z-961376d3f7ae/result.json`。
- 生产代码：同一 release 目录下 `candidate/ra_triage_dashboard`。

新表兼容旧应用；应用回退不删除新表，也不使用旧备份覆盖后来写入的数据。

## 验证

- 精确发布 SHA 的云端完整测试：862 passed、6 skipped，133.91 秒；隔离灰度通过。
- 生产 `/health`、数据库、整体状态均 healthy；实际 SHA、schema57、恢复开关关闭已核对。
- 实际提供的入口 JS、历史页 JS、提交 JS、历史 CSS 和 mobile.css 共 5 个资源与候选代码 SHA-256 一致；页面 shell 确认 cache654、系统管理菜单归属和 2 个本次记录入口。
- 整合最新主干后重新执行隔离 Chromium 检查：320、390、1440px × 中英文 × 深浅主题，历史页和提交入口均通过；精确深链、成功弹窗保留入口、失败隐藏、新提交清除旧链接通过。测试提交响应使用替身，未写真实 Trail。
- 本次公网 IAB 页面导航超时，未完成生产 SSO 登录态浏览器验收。没有将后台资源核验或本地响应式检查称为真机、Safari 或公网登录态验收。

本文件为发布后的文档记录，不需要再次重启服务。
