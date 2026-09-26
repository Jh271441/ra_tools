# RA 仿真看板独立部署

所有机器地址通过目标 JSON 的 `ssh` 配置。浏览器直接访问目标的 `http://<目标地址>:<port>/sim/overview`，无旧机器反向代理。

## 环境与数据

原生 Linux 模式：Python ≥ 3.10、uv、PostgreSQL 工具、Nginx、Redis、Supervisor；系统 Supervisor 已运行，部署用户可通过 sudo 注册单个服务。目录必须可写、路径暂不支持空格。数据库使用独立 data directory 和私有 Unix socket；Redis 同样不开放 TCP。只开放 HTTP 端口，API 绑定 loopback。首次上线前检查用户网络和目标上游访问，HTTP 入口面向已有内网访问边界。

`root` 持久化数据库、队列、备份、日志、运行配置；`source` 保存应用、版本配置及 reports。迁移不需要复制 bags。保留足够的空间容纳应用、两份数据库和备份增长。镜像不存在时使用原生模式，不依赖 Docker-in-Docker。

部署需要可信源包（包含 ra_sim_repro_dashboard、reports、scripts、ra_api、tests），前端先执行 `npm ci && npm run build -- --base=/sim/`。`.env`、私钥和令牌不得打入源包。`secrets.json` 是仅包含应用所需环境变量的字符串字典，权限 600，禁止提交。

## 一键部署

复制 `target.example.json`，修改 `ssh`、`root`、`pg_bin`、`port`、`api_port`：

```bash
python3 ops/sim_deploy/deploy.py --target target.json \
  --bundle source.tar.gz --secrets /private/path/secrets.json --dump database.sql
```

命令同步文件、创建虚拟环境、初始化独立 PG/Redis、恢复数据、启动服务、检查接口，并注册系统 Supervisor 开机启动。已有部署目录会拒绝覆盖；升级用新目录和新端口预部署，验证后迁移，避免隐式破坏数据。底层 `manage.py prepare/status/check` 可重复执行。

需要周报时增加 `--weekly weekly.json`，迁移已有调度时增加 `--schedule-state weekly-schedule-state.json`。不传周报配置就不启动调度。

## 管理与迁移

在目标机器：

```bash
python3 /部署目录/manage.py --config /部署目录/target.json status
python3 /部署目录/manage.py --config /部署目录/target.json check
python3 /部署目录/manage.py --config /部署目录/target.json backup
```

原生部署之间：

```bash
python3 ops/sim_deploy/migrate.py --source source-target.json --target new-target.json
```

迁移检查队列与刷新状态，停止源站入口/写入/调度，备份并传输源码及数据库，在新目标部署和验证。目标尚未尝试启动前失败会恢复源站；目标一旦尝试启动，失败时源站保持冻结，必须先确认并停止目标写入再回滚，避免双写。成功后源站保持停止并禁用应用自启动，保留回退数据。首次从旧 Compose 服务迁入采用相同步骤，但需手动停止指定 Compose 应用容器并执行 pg_dump。

迁移同时携带周报配置、执行状态和最近有效报告。当前迁移命令在停写后传输全量，不提供增量预同步；对于大数据库，必须先演练耗时。周报 period.manifest 用相对于 source 的路径，不能绑定旧机器绝对路径。新地址需通知使用者；域名切换不在脚本中隐式执行。

恢复到已有数据库必须显式使用 `restore --dump <可信SQL备份> --replace`，命令先备份原库再替换；失败后服务保持停止，检查并用备份恢复。新版本 pg_dump 的匹配 restrict/unrestrict 包装会被验证并移除以兼容旧 psql，其他 SQL 错误仍使事务失败。建议迁移使用相同 PostgreSQL 主版本；本次 16→14 已通过实际 schema/data 恢复及接口一致性验收，不代表支持任意降级。

源站退役后回滚不能直接启动旧库：先冻结新站写入，备份新库并处理新增数据，再恢复旧入口。仅应用回退且 schema 相容时可保留当前数据库。

## 周报

独立服务器进程 `scheduler.py`，Asia/Shanghai 每周一 09:00。重启后补跑当周到期任务；每周最多 3 次，失败间隔 6 小时。状态保存在 root，切换机器时迁移。业务进程在 Supervisor 下恢复；配置更新后可手动运行 weekly.py 重试，不需要等待下一周。

查看 `/sim/weekly/`。`status.json` 是本次状态；`latest.json` 仅在完整覆盖和质量门禁通过后更新。未完成、缺凭据或未确认的筛选条件均不会覆盖有效报告。

`weekly.example.json` 的两个周期来自用户示例，**verified=false**：日期字段和右端边界尚待与实际数易页面核对。上线有效指标前必须补充：

- 数易 reference 链接、query_attrs、版本匹配方式、时间字段和精确区间；
- 每个实际周期的 release、case_start、case_end_exclusive、cycle_end、证据；
- 该版本 binary 对应的已核实 job_ids 和完整 manifest；
- ORION_TOKEN 及 Trail 所需签名环境变量。

程序不会按 release 名字推算周期，不会自动发起仿真。复现判定沿用现有 road-behavior 口径：自动触发正/负样本应重触发，人工场景应不触发；业务 P/R 是另外的指标。数易 case 集合全部映射到场景且仿真成功、DPE 齐全、无冲突、质量门禁通过后才发布。历史一周/两周例子的周期选择通过单元测试，真实数易对账仍需数据依据。

## 验收

1. 比较源/目标的版本配置、数据库记录数、所有版本指标。
2. 浏览器直连目标，点击版本过滤、case 明细、刷新，等待任务完成；深层链接刷新正常。
3. 保存首页、过滤、明细、服务状态截图，并检查 JS/HTTP 错误。
4. 停止源站应用服务后重做目标检查；再重启目标服务验证持久化。
5. 对周报执行历史周期回放和 case ID 集合对账。

测试：`python3 -m unittest discover -s ops/sim_deploy -p "test_*.py"`；后端在 backend 目录 `PYTHONPATH=. python -m pytest tests -q`。

部署健康检查会验证相对重定向、保留/剥离 `/sim` 的页面和 API，以及构建 JS/CSS 的响应类型及内容一致性；不能只检查首页 200。
