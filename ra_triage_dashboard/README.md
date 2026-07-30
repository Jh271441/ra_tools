# RA Triage Workbench

一个独立于 `ra_auto_triage` 的 issue triage / 标注 / 模型结果对比看板。

## 当前 MVP

- 默认工作集是 `trail_label_baseline_20260729.xlsx` 中 `dataset=0508` 的 **1071 条**；GT 只来自该快照，不因 Trail 查询或模型导入而改变。
- 首页为单张大 BEV review canvas，点击后打开 Ares Capture BEV / Camera 统一时序预览；`←/↑` 上一帧、`→/↓` 下一帧，`B/C` 切换 BEV / Camera。以后可直接把主 canvas 的资产替换成 Camera 合成图或视频。
- 左侧全局工具栏采用 240px / 64px 折叠布局并记住用户选择；判错复核、模型 Runs、单 case 推理和数据导入分别使用 `/review`、`/runs`、`/inference`、`/import` 独立页面，支持硬刷新和浏览器前进/后退。只有 BEV / Camera 媒体预览保留弹层。
- 服务启动时会从配置的 Trail view 只读拉取张扬的 `ra_stuck_auto_result` 和 `ra_stuck_auto_result_info`，生成默认比较 run；同内容回刷复用已有快照，字段结果变化才新增历史 run。
- 可导入 issue / GT 与模型输出（JSON、CSV、XLSX）；模型文件按 SHA-256 创建不可变 model run。独立 Runs 管理页面可切换 Review run、设为默认、同步 Trail 并查看覆盖率。
- 人工标注为追加式历史，最新一条为当前标注，不覆盖旧 review；「模型为什么判错」是主输入，「模型缺失信息」收进紧凑的结构化多选下拉，并自动汇总为 routing、绕行空间、灯态、双闪、时序等错误聚类。
- 页面可提交单 case 推理：模型名、base URL、API key 临时输入，调用 `ra_auto_triage` 的受控 worker。
- 推理 worker 固定 `RA_TOOLS_ENABLED=false` 和 `BAG_CACHE_READ_ONLY=true`，不会创建 model-triage batch 或写 Trail。

## 数据边界

代码与可变数据分开：

- 代码：`/volume/home/workspace/ra_tools/ra_triage_dashboard`
- 可变数据：`/volume/home/workspace/ra_triage_dashboard_data`
- Ares 输入资产：`/volume/home/workspace/ra_auto_triage/bags/ares_capture_bev`（只读）
- Camera 输入资产：`/volume/home/workspace/ra_auto_triage/bags/camera`（只读）
- 0508 GT 快照：`/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx`（只读）
- 模型 / Trail 读取逻辑：`/volume/home/workspace/ra_auto_triage`（只读调用）

API key 仅存在于 HTTP 请求和 worker stdin 的内存中；不会写入 SQLite、任务配置、命令行参数、环境变量或 worker 日志。页面提交后立即清空输入框。

## 用户身份与后续 SSO

当前直接 IP 部署没有可信的 SSO ingress，后端默认不信任任何客户端身份 header。页面会尝试从访问者本机 LCA `/lcainfo` 响应中**只提取** `LocalUserAccount`，用作页面显示和默认标注人；不会上传、返回或保存 LCA 响应中的 token。该用户名在 UI 中明确标记为「未验证」，不能用于权限判断。

套内网域名并接入 SSO 代理后，应由 ingress 先清除客户端同名 header，再注入唯一身份 header，并确保服务只能从该代理访问。完成这些网络约束后才启用：

```bash
export DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=true
export DASHBOARD_IDENTITY_HEADER=X-SSO-User
```

可信代理身份会覆盖前端提交的 `author` / `requested_by`。在完成上述约束前保持默认 `false`。

## 结果导入契约

支持 `.json`、`.csv`、`.xlsx`、`.xlsm`。

Issue / GT 文件最少需要：

```text
issue_id
```

可选列：`trip_id`、`gt_label` / `ra_merge_result` / `期望输出`、`title`、`scenario`、`summary`、`trail_url`。

模型结果文件最少需要：

```text
issue_id, model_label
```

`model_label` 可替换为张扬写入 Trail 的 `ra_stuck_auto_result`；可选 `ra_stuck_auto_result_info`（JSON）、`model_reason` / `reason`、`model_confidence` / `confidence`、`trip_id`。原生 `run_batch.py` 结果包可直接上传：

```json
{ "experiment": { ... }, "results": [ ... ] }
```

GT 导入默认不会覆盖已有 GT，只有在 UI 勾选明确覆盖时才会改写。

如果 Trail 当前 view 没有把这两个字段展示出来，页面不会伪造空结果，会明确提示并保留 CSV/JSON/XLSX 上传入口。可通过 `DASHBOARD_TRAIL_VIEW_ID` 指向已添加字段的 Trail view，然后点击「同步 Trail 字段」反复回刷。

## cloud_server 启动

```bash
cd /volume/home/workspace/ra_tools/ra_triage_dashboard
bash scripts/run_cloud_server.sh
```

当前试运行监听 `0.0.0.0:8785`，可从内网直接访问 `http://172.16.145.60:8785`。因为这是明文 HTTP，单 case 推理只应使用临时、低权限 key；生产多人使用应迁到 HTTPS + SSO 认证代理。

页面路由可直接访问：

- `http://172.16.145.60:8785/review`
- `http://172.16.145.60:8785/runs`
- `http://172.16.145.60:8785/inference`
- `http://172.16.145.60:8785/import?kind=issues`

如需收回直接暴露，可把启动参数改为 `--host 127.0.0.1`，再使用 SSH 隧道：

```bash
ssh -L 8785:127.0.0.1:8785 cloud_server
```

再打开 `http://127.0.0.1:8785`。在没有服务托管器的 cloud_server 上，可先使用受控 tmux 会话。

## SQLite 到 PostgreSQL

MVP 使用 SQLite（WAL 模式）便于在 cloud_server 快速验证。它适合单机少并发验证，不是团队正式存储。

`migrations/postgres/001_initial.sql` 提供了与当前表一致的 PostgreSQL schema；已存在的旧 MVP schema 可先执行 `002_review_baseline_fields.sql`。所有人工标注、模型结果与任务记录都保留历史行，因此迁移时是一次数据复制，不需要把旧记录扁平化或覆盖。

接入正式 PostgreSQL 后应同步完成：

1. 用 Alembic/SQLAlchemy 替换当前 SQLite storage adapter。
2. 接入 SSO / 反向代理，将 `requested_by` 替换为可信身份。
3. 为导入、推理和 Trail 回写（若后续开放）添加 RBAC 与审计。
