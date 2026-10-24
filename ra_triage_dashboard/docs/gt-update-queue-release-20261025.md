# GT 待更新入口发布 · 2026-10-25

已部署 `263c9b54095af4ded716b30ea4dd8ffd36c8f11f`，缓存650。2026-10-25 02:49:20 CST 切换生产，原版本 `252a86b73daa05130600e69968eee867d6ec6526` 保留为回退版本。

入口：「问题标注 → GT 待更新」，路由 `/manual/labeling-summary?gt_update=ready`。同一界面切换全部标注、待更新和需确认，复用汇总筛选与明细；规则见 [gt-update-queue.md](gt-update-queue.md)。

- 云端完整套件：845 passed / 5 skipped。精确SHA隔离SQLite灰度18789、生产PostgreSQL健康和策略检查通过；schema56不变。
- 发布记录：`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T184707Z-263c9b54095a/result.json`。使用版本化deploy_cloud辅助函数及同一发布锁，保留canonical本地提交/文件和已占用8786；未修改运行中的release。初次候选的完整测试发现一个旧缓存断言，已修复；初次测试失败未切换生产。
- 发布后读取生产health、shell和7个相关静态资源，SHA/cache650/字节哈希均匹配候选。身份、writer、通知和业务写入配置不变，没有重放消息，没有更新GT/标签/任务进度。
- Codex内置浏览器使用隔离夹具验证1920×1080中文深色、1440英文浅色、320英文浅色、390中文深色；无页面横向溢出。验证待更新/需确认、计数、标注人筛选、空列表、加载失败恢复、共享下拉Escape、语言切换、侧栏及后退恢复、规则弹窗。加载中语言切换保留任务由执行实际JS的行为回归覆盖。
- 生产公网内置浏览器导航两次超时，未获得登录后的生产清单数量或交互证据，不把静态/健康检查当成登录态验收。未操作Chrome或宿主鼠标，未进行真机、模拟器或iOS Safari验收。
- 本地证据：`reports/manual_gt_update_queue_20261025/`，包含fixture桌面/手机截图、verification.json、postflight.json。截图是隔离测试数据，不是生产业务数量。
