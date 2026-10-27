# RA Event Escape 焦点修复

2026-10-27 16:44:37 CST 已发布，提交 `5183e670c62d2c34085a0d47a42374ab66cef2f0`，cache682。合入最新生产57daf94，保留「下一个待完成」功能及此前汇总裁决。

- 整合后112项相关测试通过；云端完整1021 passed / 7 skipped，隔离SQLite灰度及生产持久PostgreSQL健康/访问写入策略核对通过。生产运行SHA与5份静态资源和目标提交完全一致。无迁移或业务写入。
- 发布记录 `/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261027T084044Z-5183e670c62d/result.json`。线上IAB连接超时，不声称登录态生产视觉验收通过；下列浏览器证明为本地合成预览。
- 保留策略清理旧fe214ca发布的未使用candidate/rollback副本；Git历史与小型发布日志保留。

- 原因：原生 dialog 关闭时恢复 RA Event 入口焦点，而原有 Escape 处理仅覆盖输入框/弹窗，没有释放入口的焦点高亮。
- `bindRaEventDialogFocus` 在关闭后的 animation frame 中只释放当前 RA Event 入口焦点；已转到输入框或打开其他弹窗时不抢焦点。弹窗关闭后入口单独获得焦点时，Escape 也可退出。保留原生 dialog cancel、Tab 焦点样式、现有 T 开关与所有业务操作。
- 共享入口绑定同时用于 Review/问题标注；无 CSS、文案、API、GT、媒体或任务变更。
- 本地106项相关测试通过；新增 Node 行为测试覆盖重复绑定、close 事件、残留焦点、其他弹窗、输入框、IME及组合键。JS语法及 diff检查通过。
- Codex内置浏览器，独立临时SQLite合成 cn1，实际验证 T→Escape、点击→Escape、T→T、入口获得焦点→Escape，焦点均释放到 BODY，弹窗数归零。1440中文深色、390/320英文浅色视口无页面横向溢出，截图已视觉检查；非真机，无真实视频或生产写入测试。问题标注页本轮未单独浏览器复验。
- 截图：`/tmp/ra-event-escape-desktop.jpg`、`/tmp/ra-event-escape-390.jpg`、`/tmp/ra-event-escape-320.jpg`。预览使用当前工作树，旧8787预览保持不变。
