# 保存成功提示

2026-10-27 19:51:03 CST 已发布 `231b50b3ac3c3ae22f7a48e944b8df64e65db754`，cache683。

- 联合复核成功统一显示「联合复核已保存 / Combined review saved」；单独标注显示「标注已保存 / Label saved」。不再向用户暴露“原子提交”“Case vote”，新增和确认已有标注使用相同提示。
- 只改展示文案，沿用 uiText；请求、事务、任务确认、刷新导航及后台图片保存不变。无布局、数据或迁移变更。
- 本地95项相关测试、云端完整1022项通过/7项跳过，隔离SQLite灰度及生产持久PostgreSQL健康/访问写入策略核验通过。生产SHA、3个静态资源、缓存号和中英文提示均与提交一致。
- 发布记录：`/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261027T114709Z-231b50b3ac3c/result.json`。未提交生产测试标注，也不声称完成新的登录态浏览器提交或视觉验收。
- 按保留策略清理旧57daf94的未使用candidate/rollback副本；Git历史和发布日志保留。
