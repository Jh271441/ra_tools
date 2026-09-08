# Dashboard 统一发布

在 cloud_server 执行（从 Mac / T3650 使用 host-router 的 SSH 路径）：

```bash
cd /volume/home/workspace/ra_tools
git fetch origin master
# 先从目标提交取出发布器；不提前修改运行中的生产代码目录。
git show origin/master:ra_triage_dashboard/scripts/deploy_cloud.py > /tmp/ra-dashboard-deploy.py
python3 /tmp/ra-dashboard-deploy.py --sha <完整40位提交SHA> --check
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
6. 再次确认生产进程及配置未变化，快进代码，优雅停止原进程，用保留的运行配置启动 8785。
7. 验证精确 SHA、PostgreSQL 持久化、数据库及整体健康，并比较身份/业务写入策略。
8. 保存 `result.json`、测试日志和运行日志。仅最近两次成功发布保留代码副本；更旧副本仅在无改动、无运行引用、忽略文件只有缓存时清理。其独立灰度数据随副本清理，记录与日志保留。

`--check` 只进行预检（会 fetch 并使用发布锁），不会创建工作树或重启服务。
运行配置以同用户 0600 文件保存；凭据仅保留文件路径，不复制凭据值。
不支持从环境传入明文数据库 URL、API key 或 token。

## 失败与范围

测试或灰度失败不会切换生产，现场保留供检查。生产切换后验证失败时，尝试从原运行 SHA 的独立目录恢复并记录回退结果；不会重置 master 或修改 Git 历史。回退后先核对服务和记录，将生产主目录与实际运行版本重新协调，再进行下一次发布。

数据库迁移、依赖文件和 PostgreSQL 引导/迁移脚本变更会在预检时停止，需要单独规划兼容性、环境更新和恢复。不会自动改数据库或升级共享 Python 环境。

纯文档变更只需同步 Git，无需调用部署器。界面行为变化仍应补充相应浏览器验证；通用 API 冒烟不替代页面交互测试。

失败发布、手工建立的旧 worktree、Bot 及其它服务不属于自动清理范围。
独有文件和进程引用会阻止清理，`result.json` 记录本次清理路径。
