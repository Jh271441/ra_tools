# Trail 历史可视化与管理员恢复启用

2026-10-25 04:14:32 CST 发布成功。用户明确授权开启恢复，限制管理员并保留预览确认和冲突检查，同时精简文字、增加可视化表达。

- 生产 SHA：`8b48e2353245e3b7cabba242f9ee114533ff6014`；cache655；schema57 不变。
- 上一版／应用回退 SHA：`961376d3f7ae19068c2c26286891f80290729405`，上一版恢复开关关闭。
- `DASHBOARD_TRAIL_ROLLBACK_ENABLED=true` 已核对运行进程配置，重启配置保存在该 release 的受限配置文件中。原有身份、writer、GT 同步和通知策略不变。
- 服务端仍要求已验证管理员身份、现有写入授权、同源标记、有效预览和明确 `confirm: true`；提交前重新读取并检查冲突，写后回读。前端隐藏按钮不替代鉴权。
- 3 条 legacy 历史仍无完整快照，不能恢复。只有有完整快照且核验成功的 Issue 可进入恢复预览。本次没有执行真实 Trail 恢复或历史重放。

页面变化：列表以成功比例条和状态标记辅助扫描；详情以“修改前 → 修改后”状态对比、执行时间线和三步恢复流程表示变化。长理由、操作标识、覆盖范围及说明按需展开。恢复预览中的理由差异默认展开；更改原因或选择项立即使旧预览失效。字段缺失、null、false 继续保持区别，旧记录不虚构前后值。

验证：

- 本地相关测试 71 通过、1 PostgreSQL 用例跳过。新增 writer/reader 对三个恢复相关端点均被拒绝、未验证身份被拒绝，以及管理员不能省略确认的回归用例。
- 精确发布版本云端完整测试：864 passed、6 skipped，137.89 秒。隔离 SQLite 灰度通过，灰度恢复开关关闭。
- 生产开关开启后，无凭据调用 verify、restore-preview、restore-commit 均返回 403；只读列表的 `can_restore=false`，legacy 详情均不可恢复。
- 生产健康／整体状态 healthy；4 个实际静态资源与候选文件 SHA-256 一致，页面 cache655 已核对。
- 本机隔离 Chromium 覆盖 320、390、1440px × 中英文 × 深浅主题；无页面／表单横向溢出或 JS 错误。另验证展开的手机时间线、展开状态与草稿跨语言保留、预览确认失效、精确详情深链和 legacy 禁用。
- 浏览器使用本地测试数据与模拟 Trail 传输；未进行真实恢复、真机软键盘／触摸或生产 SSO 管理员正向写入验收。

发布使用 `scripts/release_trail_history_visual_20261025.py`，复用版本化 deploy_cloud 门禁。旧 canonical checkout、本地文件和占用中的 8786 保留，灰度使用 18789。无 schema 迁移和业务数据改写。

发布记录：`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T201157Z-8b48e2353245/result.json`。生产代码在该目录的 `candidate/ra_triage_dashboard`。原 schema57 备份及演练记录仍在首次迁移的独立 migrations 目录中。
