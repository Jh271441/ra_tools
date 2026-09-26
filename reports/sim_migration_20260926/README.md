# 仿真看板迁移验收 — 2026-09-26

目标直连：http://172.16.145.60:8787/sim/overview
周报检查状态：http://172.16.145.60:8787/sim/weekly/

## 部署

- 独立目录 `/volume/home/services/ra-sim`，端口 8787；API 仅 127.0.0.1:8788。
- 独立 PostgreSQL 14 数据目录与 Unix socket、Redis socket、FastAPI、RQ Worker、Nginx、周报调度。
- 系统 Supervisor 管理子服务组 `ra_sim_3e7557fc36`；原始目标运行于容器，不使用不可用的 systemd 或 Docker-in-Docker。
- 旧站 backend/worker/frontend 三个容器已停止；数据库与 Redis 保留以备回滚。旧站 API 返回 502，新站正常，无旧机转发。
- 数据来自旧站实际运行代码快照（7b8b29a + 未提交修改），不是直接复用目标机器旧 checkout。

## 一致性

迁移前后：数据库版本 24、issues 22059、scenarios 22264、results 22082；配置展示 12 个 release。全部版本 comparison JSON 一致。

当前 release0828：有效 case 1506，复现数 1369，复现率 90.9%，P 83.94%，R 81.77%。其质量门禁失败及数易线上人口缺失是原有状态，迁移未将其隐藏或改为通过。这些指标不代表新周报已按 09/03–09/10 完成筛选。

源端最终数据库备份 SHA256：
`22edd44c2d7a79cb0ff22d74c76aced01274bf431e640a105e168b79d0c5244d`

源端最终 reports/config 包 SHA256：
`759f6206e4cd38a408ab53dd010d377a8857195fa75a9467bf6631c9aa240db9`

目标备份位于部署目录 `backups/`，包含源初始、最终和替换前的目标数据库备份。

## 浏览器验收

独立 Chromium 直连目标，在旧应用容器停止后完成：

- 总览图表加载；无 JS 异常或 HTTP 错误。
- release0828 筛选显示 1506；release0821 筛选显示 1126。
- 点击 case 表格进入明细，包含 source/仿真信号及 scenario。
- `/sim/issues` 直接打开与刷新，点击总览和浏览器后退均正确。
- 点击刷新，job `c4f19c69614148f88afd3056ae671d19` 完成（约 21 秒）。刷新来源为真实 report artifacts，不是新采集的上游结果。
- 服务状态 overall=ok，数据库、Redis、队列正常，Worker=1，待处理与失败队列均为 0；mock 在生产关闭。

截图：`overview.png`、`filtered.png`、`case-detail.png`、`status.png`、`weekly.png`。

## 通用命令验收

- deploy.py 已在另一目录和端口完成全量部署、SQL 恢复、健康检查、启动恢复注册。
- migrate.py 已在两套隔离演练目录之间完成停止源写入、备份传输、目标部署、数据验证和禁用源应用自启动。
- 演练使用同一物理目标机的独立目录/端口，SSH 传输链路经过控制机；未声称验证所有机器架构。
- 演练服务已停止，启动配置退役，数据暂保留作回退检查。
- 正式服务组整体停止/启动后，六个子进程自动恢复，页面和 API 检查通过；未执行整机重启。
- 正式部署占用约 495 MB；目标数据盘仍为 99% 使用率（约 108 GB 可用），需持续关注其余业务增长。
- 18 个后端回归测试通过；5 个周期/调度测试和 1 个配置校验测试通过。

## 周报尚未验收的部分

服务器调度为 Asia/Shanghai 每周一 09:00，最多 3 次尝试，间隔 6 小时；支持重启补跑与状态迁移。

用户给出的 release0828 / release0904 周期已写入待核实配置。当前数易看板链接、确切日期字段/边界及权威周期来源未提供，因此 `verified=false`；release0904 也没有已核实的完整周期仿真 job。系统只发布“待核实/待周期”状态，不发布猜测复现率，不自动提交新仿真。

一周/两周周期选择已经通过测试，但真实 case ID 集合与数易对账、上游最新仿真结果查询和正式周报发布仍待补齐业务依据后完成。

## 2026-09-26 域名入口修复

域名 `https://auto-triage.intra.xiaojukeji.com/sim/overview` 经 Kylin SSO。

1. HTTPS 终止在网关；后端原先把 `/sim` 重定向为 http + 8787。已设置 `absolute_redirect off`，使用相对 Location。
2. 15:45 后端日志确认网关剥离 `/sim`，实际收到 `GET /overview`，按默认静态目录查找而 404。已补充 overview/issues/status/assets/weekly/favicon 显式前缀兼容和 `/api/` 转发；保留原 `/sim/` 路由。
3. 修复后对剥离前缀的页面、JS/CSS、API、周报与 favicon 检查 200，并与原路径响应比较。未改变网关鉴权或路由注册。
4. 当前工具未能连接用户已有登录浏览器；匿名域名请求仍按预期进入 SSO，登录后的用户浏览器刷新需再次确认。
