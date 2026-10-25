# 标注分配页的联合任务镜像

2026-10-26。实现完成，未部署。基于 origin/master `2a64c4d`，独立分支
`codex/combined-labeling-tasks`；不包含另一个分支上的 Review 裁决候选。

## 计划与实施结果

1. 在 `/case-labeling/new-task`（同页别名 `/labeling-experiments`）的分配配置下方，
   增加“联合复核任务”，继续保留独立标注实验记录。
2. 使用只读 `GET /api/labeling/combined-tasks` 投影现有 Campaign，不复制任务、
   分配或标注。既有页面仍管理员可见；接口与标注查询一样要求 writer/admin。
3. 卡片显示案例数、按负责人计的标注确认 / 模型复核提交 / 联合完成以及人员进度。
   Case 标注只认可该任务进度引用的确切 revision，过滤无效作者、Issue 和被抑制记录；
   任意自由标注、后来修改或共享裁决不能被当作任务提交。
4. 版本任务完整使用当前版本目标集，不把历史非目标成员加回分母。历史14条和排除案例
   均保持现状。版本选择不串到同原始 baseline scope 的其他版本。
5. 版本卡片复用 Review 分配页的版本目标入口，默认当前人员的待复核集合；
   固定任务复用 reviewAssignmentBatchHref，携带原 Run、Campaign、所选 scope 和本人分配。
   联合提交仍在现有联合复核流程完成，不开放独立标注 API 对联合任务直接写入。
6. 同步刷新仅更新列表，保留未提交的分配表单；相同数据保留链接节点、焦点和滚动，
   变更后的同任务链接恢复焦点。切换 baseline / actor 后丢弃旧请求。
   失败保留同范围旧数据并明确提示重试，空数据明确显示无任务。

没有新增迁移，没有修改数据库记录、抽样策略、目标集、人员、Run、GT 或 Trail。
缓存版本 `manual-triage-661`；新增模块同时注册 MANIFEST 和 app.js。
窄屏沿用共享组件，并在 mobile.css 修复原分配配置固定720px列导致的控件裁切。

## 验证

- 完整 Python 测试：892 passed / 6 skipped。
- 最后文案及实际路由 helper 回归：23 passed。
- touched JS syntax、Python AST、git diff --check、敏感模式扫描通过。
- Codex 内置浏览器 + 本机隔离 SQLite，真实应用/接口；没有生产写入。
  预览以现有 loopback smoke identity 启动，所有 POST/PUT/DELETE 被额外拒绝。
- 1440px 中文深色、英文浅色；390px 和320px英文浅色。
- 检查完整截图、局部截图、内容边界、主要操作44px、共享下拉和Escape关闭。
- 多版本/零完成、空列表、503失败保留已有数据、恢复、刷新保留草稿、运行时切换语言，
  以及点击进入当前版本/本人/待复核范围。
- 这是响应式浏览器验收，不是真机/软键盘测试。生产SSO及上线后验收尚未进行。

截图和测试输出：`reports/combined_labeling_tasks_20261026/`（合成数据，不代表生产计数）。
已有分配表单的非新增文案不在本次全面国际化重做范围内。
