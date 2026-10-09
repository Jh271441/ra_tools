# 新版 Dashboard 上线准备 · 2026-10-09

本轮只准备、修复保护措施和演练，不切正式流量。推荐新版接替现有 `/manual` /8785，
保留8786验收实例。用户尚未对入口选择给出额外答复；此方案不是切流授权。

## 已实施

- 8786持久化目录实际核实为 `/volume/postgresql/14/main`，非overlay。
  启动器每次检查真实目录后才设置持久化标记；状态已从degraded恢复healthy。
- 独立备份计划 `45 2 * * *`（按服务端cron时区）；旧8785 `15 2 * * *`原样保留。
  每次备份数据库及review/comment附件、uploads，保留14个完整代次；校验文件和恢复
  回执同目录保存。脚本 `scripts/backup_instance.py` 从私有URL文件选择实例，禁止远程
  密码连接，不打印URL。状态页按实际库名识别备份，避免假阳性。
- 本轮使用repeatable-read导出快照创建备份；恢复到独立临时库，90张public表的行数和
  内容SHA256逐表完全相同。验证库已经删除，在线源库未改。
- 8786部署7dc602e（cache566，schema053），636 passed/5 skipped；冻结业务/API响应
  6214465字节完全一致。新增测试覆盖独立库备份识别及其他库备份不得冒充。
- 独立上线候选 `manual_launchready_20261009` 已从上述备份恢复，再核对90表；只在
  此候选中移除ux-smoke-admin ACL、禁用其mention。其余5账号角色/Intent权限与8785相同。
  原始来源、显式裁决和迁移审计保留。候选data独立复制，媒体只读共用。
- 正式配置已私有保存：production mode、关闭smoke loopback admin、真实SSO校验，
  保留当前生产外部功能开关。演练配置全部禁用外部writer、GT后台同步和通知。
- 发布候选分支codex/dashboard-release-ready合并当前master与UX；Dashboard应用代码
  与7dc602e一致，保留master网关文档及其他项目。旧版专用UI/裁决逻辑不覆盖新版本，
  逐项判断见refactor-8786-plan-20261004.md。未合入master、未发布8785。

## 数据核对

8785/8786原始annotations2306、comments85、review_attachments54、Intent revisions418、
Runs29、predictions18730逐字段一致；无需重复迁移。五个GT快照内容相同；0508有效结论
222/222与GT一致、已裁决37、已提交待完成28、冲突10。其他数据集存在真实GT差异，
不得自动改成一致。0508最近Trail观察仍为9月30日，不能称为已检查今天Trail。
issues差异仅updated_at；GT缓存差异仅同步时间。新版label revisions/任务关联的差异
属于已有领域拆分，不应被旧库覆盖。label来源没有悬空引用。

## 正式切换步骤和拒绝条件

不要直接运行默认deploy_cloud.py：它需要空闲8786，并且不负责从旧库转换新版领域数据。
本次属于已有转换库的受控接替，使用已恢复/核对的候选，不能让旧库仅升级schema后上线。

1. 复核发布分支与master最新差异，合入并钉住精确SHA；应用代码树若发生变化须重新验证。
2. 使用独立空闲回环端口启动候选，正式base path `/manual`，禁止测试身份和外部writer。
   检查启动、权限、图库、标注汇总、GT预览和媒体；权限测试不能创建真实业务记录。
3. 最终切换窗口冻结8785及8786写入，重新备份两库与可变附件，核对源记录、GT快照、
   裁决/任务及配置指纹。任何新提交或源指纹变化都中止切换，先增量转换并重新验收。
   不盲目覆盖候选，不把9月30日“冲突”前缀一次性规则变成日常规则。
4. 保存旧8785进程命令、私有env、SHA和数据库路径，停止旧进程；将正式入口绑定已验收
   候选代码+数据库+附件目录，开启既有生产所需功能（单实例运行）。候选备份计划必须
   随实际DB/data目录注册，不能只依赖验收实例备份。
5. 先保持维护/拒绝写入，验证正式域名真实SSO、成员/管理员权限、资源和API。
   无smoke admin、匿名/伪造身份拒绝写入、健康与备份正常后才开放真实写入。
6. 若开放写入前失败：停候选，恢复原8785代码/env/原DB；原DB保留未修改，可直接回退。
   开放写入之后失败：先冻结并备份新提交，制定增量回迁；不得直接回旧库造成新标注丢失。

## 私有证据

experiment root下 `production-readiness-20261009/`：
`release/release.json`、`candidate-prepared.json`、`candidate-rehearsal.json`、
`production_env.before.json`、`production_env.prepared.json`、`candidate/config/`。
环境文件可能含凭据路径，仅0600保存在服务器，禁止提交Git或贴入日志。
实际备份在验收实例data目录的postgres_backups；其receipt含90表指纹。

## 尚须最终切换时验证

真实正式域名的SSO写权限不能由匿名演练或mock单元测试替代；本轮不切路由、不提交
真实标注，也不开双份GT/通知任务。上线结论应区分“准备验收通过”和“已完成正式上线”。

## Final rehearsal evidence

Candidate startup passed in production mode on an automatically selected free
loopback port. Anonymous, forged X-SSO-User, and username-only cookie sessions
were read-only; POSTs with the valid browser-v1 marker were denied by identity
checks with403. The temporary process exited; no real annotation was submitted.

All five scopes and six batches match current8786 business projections exactly:
6076527bytes, SHA256 a67706f604222d85a17c7299981eaaea580474abeaed8bf8d8b9669abb7b3b08.
The candidate also has its own90-table restore verification and separate daily
backup schedule45 3 * * *. Production bind address is preserved from8785.

Preparation passed. Final frozen-source delta checks, merge to master and live
production-ingress SSO acceptance remain cutover gates. No traffic was switched.
