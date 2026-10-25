# Manual 未提交改动整理（2026-10-26）

## 范围与 Git 边界

整理分支 `codex/manual-git-refactor` 基于 `origin/master` 的 `2a64c4d`。
原工作区 master 为 `b389943`，与远端分叉；使用独立工作树导入
`ra_triage_dashboard/` 的改动，保留原工作区和其他子项目的未提交内容。
本次没有部署、数据库迁移、数据复制或流量切换。

提交按以下职责分组：

1. SSO：受信任 Dashboard 返回域名与默认 App ID 的对应关系。
2. Batch：资源限额、运行环境透传、旧 RA 运行时兼容、导出代码来源校验。
3. 迁移工具：盘点、快照、备份副本、媒体校验、只读预览与恢复，以及共享哈希实现。

本地将 PostgreSQL 迁移数量固定为 53 的测试修改未导入；主线已经按
`postgres_migrations_dir` 中的 SQL 文件数量校验，继续沿用主线实现。
本机 reports 中的图片、运行报告和数据清单没有加入提交。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `app/batch_prediction_runner.py` | 构造允许的 worker 环境、传递密钥 stdin、超时和输出处理 |
| `app/batch_resources.py` | 可选的 Linux 共享 scratch 锁、内存/磁盘采样及进程组终止 |
| `app/batch_prediction_worker.py` | 预测与发布流程；保留 `repo_commit()` 兼容入口 |
| `app/worker_code_provenance.py` | 独立校验固定摘要、清单结构、源码文件内容和模块集合 |
| `scripts/migration_files.py` | 以 4 MiB 块计算文件/流 SHA-256，无运行时或数据库初始化 |

代码清单读取上限为 2 MiB；无效 JSON、非对象清单及过大清单均以校验错误拒绝。
未配置 `RA_CODE_MANIFEST_SHA256` 时继续读取 Git HEAD。直接执行 worker 脚本与
按包导入使用相同的校验模块。

迁移工具统一使用流式哈希。数据库 dump、媒体清单和 intent 样本不再通过
`read_bytes()` 一次载入内存。归档内附件直接对流计算摘要，不解压到临时目录。

## 运行配置

资源保护默认关闭。启用 `DASHBOARD_BATCH_RESOURCE_GUARD=true` 时必须显式配置
`DASHBOARD_BATCH_RSS_BYTES`、`DASHBOARD_BATCH_ADDRESS_SPACE_BYTES`、
`DASHBOARD_BATCH_SCRATCH_BYTES`、`DASHBOARD_BATCH_MIN_FREE_BYTES` 和
`DASHBOARD_BATCH_MAX_WORKERS`。数值须为正整数，并发数最多 4。
RSS 与 scratch 为采样停止阈值；address space 由 shell `ulimit -v` 限制每个进程。
该能力依赖 Linux `/proc`，不作为 macOS 运行保障。

`DASHBOARD_BATCH_PYTHON_BIN` 可单独选择 worker Python；
`VOYAGER_SETUP_SCRIPT` 和固定的 `RA_CODE_MANIFEST_SHA256` 通过服务端允许列表传递。
无关环境变量不会进入子进程，模型密钥仍仅通过 stdin 传递。

返回 URL 仅接受既有的两个受信任 HTTPS 域名：
`auto-triage.intra.xiaojukeji.com` 对应 App ID `2103794`，
`ra-model.intra.xiaojukeji.com` 对应 `2103860`。
显式 `DASHBOARD_KYLIN_SSO_APP_ID` 仍优先；现有路径、端口、用户信息和 fragment
约束保持有效。这是配置校验规则，不代表本次验证了线上 SSO。

## 迁移工具交付约束

脚本路径和命令行保持兼容。部署单独脚本时，需要将 `migration_files.py` 一并放在
同目录；备份链还需要既有的 `backup_instance.py` 和 `migration_backup_replica.py`。
优先使用完整的版本化 `scripts/` 目录，避免遗漏依赖文件。

这些工具保留原来准备环境的固定存储根、OFS 挂载身份、影子数据库和预览端口限制。
`schedule_migration_backup.py` 仍针对准备环境的 `manual_shadow_20261018`；
不能直接作为任意生产实例的通用备份调度器。
源码纳入 Git 不表示授权执行这些运维入口。真实恢复、挂载、容量、SSO 和线上
备份完整性需要在相应运行环境另行验证。

## 验证记录

- macOS / Python 3.9 全套回归：935 passed、14 skipped；在补充最后一批边界测试前执行。
- 补充边界测试并格式化后的定向回归：64 passed、7 skipped；7 项为 Linux 专属测试。
- 临时 Linux / Python 3.11 容器：21 passed，覆盖资源限制、worker 队列、代码来源和旧运行时兼容；Linux 专属测试均执行。
- 30 个修改或新增 Python 文件通过 AST 检查；12 个迁移/恢复 CLI 通过 `--help` 导入检查，未执行运维操作。
- worker 直接脚本导入、shell 语法和 Git 空白检查通过。

PostgreSQL 集成测试因没有配置临时数据库而跳过；本次没有验证真实数据库恢复和
生产挂载。没有修改前端静态文件，因此没有改变缓存版本，也没有将本次工作描述为
浏览器、移动端或线上验收。
