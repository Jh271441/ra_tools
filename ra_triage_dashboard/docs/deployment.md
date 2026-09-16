# Dashboard 统一发布

推荐从 Mac / T3650 的 `ra_tools` checkout 执行一条命令：

```bash
python3 ra_triage_dashboard/scripts/release_dashboard.py
```

该入口会 fetch `origin/master`、解析并显示完整 SHA，从该 SHA 读取版本化
`deploy_cloud.py`，再通过 `cloud_server` SSH 别名执行。它不提交或推送本地改动；
本地发布器与 `origin/master` 不一致时会拒绝运行。普通发布不需要先单独执行
`--check`，因为正式入口在任何变更生产状态之前都会执行相同预检。

需要把耗时验证和生产切换分开时：

```bash
python3 ra_triage_dashboard/scripts/release_dashboard.py --prepare
# 使用上一步输出的 release_id；期间 origin/master 和生产进程/配置必须保持不变。
python3 ra_triage_dashboard/scripts/release_dashboard.py --promote <release_id>
```

`--prepare` 创建精确 SHA 的 candidate/rollback worktree、运行完整测试和隔离灰度，
但不停止或修改生产。`--promote` 会重新执行全部预检，并核对生产 SHA、PID、环境、
身份/写入策略、migration 数量以及两个 worktree；任何一项变化都会拒绝复用。

如需只看预检，可运行：

```bash
python3 ra_triage_dashboard/scripts/release_dashboard.py --check
```

cloud_server 上的等价手工后备入口为：

```bash
cd /volume/home/workspace/ra_tools
git fetch origin master
# 先从目标提交取出发布器；不提前修改运行中的生产代码目录。
git show <完整40位提交SHA>:ra_triage_dashboard/scripts/deploy_cloud.py > /tmp/ra-dashboard-deploy.py
python3 /tmp/ra-dashboard-deploy.py --sha <完整40位提交SHA>
```

目标必须是当前 origin/master，生产分支必须为干净的 master，并且可快进。
发布器运行在已配置的 cloud_server，使用现有 Dashboard 专用 Python 环境。
发布锁阻止这个入口的并发运行；其他手工部署也应迁移到此入口。

## 自动执行

1. 核对现有 tmux 进程、运行 SHA、配置和 8786 端口。
2. 为目标版本和原运行版本建立独立 worktree，记录在
   `/volume/home/workspace/ra_triage_dashboard_deploy/releases/<时间-SHA>/`。
3. 用目标版本运行完整 pytest 套件（包含 unittest 测试）。
4. 启动 8786：独立 SQLite，关闭 Trail 启动同步、两个 Trail 写入开关、Batch、AutoTriage 发布和 DChat 通知。媒体仅复用读取路径。
5. 验证精确 SHA、SQLite 隔离、写入开关和页面/API，然后停止灰度。
6. 再次确认生产进程及配置未变化，保存恢复配置并优雅停止原进程，再快进代码并用保留的运行配置启动 8785。
7. 验证精确 SHA、PostgreSQL 持久化、数据库及整体健康，并比较身份/业务写入策略。
8. 保存 `result.json`、测试日志和运行日志。仅最近两次成功发布保留代码副本；更旧副本仅在无改动、无运行引用、忽略文件只有缓存时清理。其独立灰度数据随副本清理，记录与日志保留。

`--check` 只进行预检（会 fetch 并使用发布锁），不会创建工作树或重启服务。
`--prepare` 和 `--promote` 每阶段分别获取发布锁；阶段间即使生产被重启、配置变化、
目标分支前进或 migration 数变化，promotion 也会失败关闭。未使用阶段参数时，发布器
依次执行 prepare 和 promote，获得相同门禁但只需一个用户入口。
拆分执行 migration 发布时，两个阶段必须显式传入相同的 migration 授权参数；准备记录
不会变成未来 promotion 的长期授权。
运行配置以同用户 0600 文件保存；凭据仅保留文件路径，不复制凭据值。
不支持从环境传入明文数据库 URL、API key 或 token。

纯增量 PostgreSQL migration 可以显式使用 `--allow-additive-migrations`。
默认模式仍拒绝任何 migration；该显式模式也只接受新增加的 `.sql` 文件，
且语句限于事务包裹的 `ADD COLUMN IF NOT EXISTS`、`CREATE TABLE IF NOT EXISTS`
和 `CREATE INDEX IF NOT EXISTS`。完整测试与隔离灰度通过后，发布器停止生产写入，
创建新鲜逻辑备份，执行 checksum/archive/disposable restore/全表计数校验，再应用
migration 并核对 migration 数量，最后才快进和启动新版本。应用启动失败时会恢复旧
应用版本；由于只允许向后兼容的增量 schema，不执行自动数据库回滚。

本次意图变道三分类使用约束扩展而不是纯增量列，必须显式使用
`--allow-schema-migrations`。该模式只接受新增 migration 文件，且发布器只放行
已审阅的两个 Intent 变道约束名；同样执行新鲜逻辑备份、checksum、临时恢复和全表
计数校验。默认发布和 `--allow-additive-migrations` 都不会放行此类 migration。

## 失败与范围

测试或灰度失败不会切换生产，现场保留供检查。生产切换后验证失败时，尝试从原运行 SHA 的独立目录恢复并记录回退结果；不会重置 master 或修改 Git 历史。回退后先核对服务和记录，将生产主目录与实际运行版本重新协调，再进行下一次发布。

依赖文件、PostgreSQL 引导/迁移脚本和非增量数据库变更会在预检时停止，需要单独规划兼容性、环境更新和恢复。不会自动升级共享 Python 环境。

纯文档变更只需同步 Git，无需调用部署器。界面行为变化仍应补充相应浏览器验证；通用 API 冒烟不替代页面交互测试。

失败发布、手工建立的旧 worktree、Bot 及其它服务不属于自动清理范围。
独有文件和进程引用会阻止清理，`result.json` 记录本次清理路径。
