# RA Triage Workbench

一个独立于 `ra_auto_triage` 的 issue triage / 标注 / 模型结果对比看板。

## 当前 MVP（v1.3）

- 默认工作集是 `trail_label_baseline_20260729.xlsx` 中 `dataset=0508` 的 **1071 条**；GT 只来自该快照，不因 Trail 查询或模型导入而改变。
- 首页为单张大 BEV review canvas，点击后打开 Ares Capture BEV / Camera 统一时序预览；`←/↑` 上一帧、`→/↓` 下一帧，`B/C` 切换 BEV / Camera。以后可直接把主 canvas 的资产替换成 Camera 合成图或视频。
- 左侧全局工具栏采用 240px / 64px 折叠布局并记住用户选择；判错复核、模型 Runs、单 case 推理和数据导入分别使用 `/review`、`/runs`、`/inference`、`/import` 独立页面，支持硬刷新和浏览器前进/后退。只有 BEV / Camera 媒体预览保留弹层。
- Trail 操作分成「检查字段」和「创建 Run」两步，收在数据导入页的默认折叠区；两步都不写回 Trail，快照只创建或复用本地不可变 Run，且不会修改团队默认 Run。启动时若启用 Trail 检查，也只执行第一步。
- 可导入 issue / GT 与批量模型输出（JSON、CSV、XLSX）；模型文件按 SHA-256 创建不可变 Model Run。Runs 页面只保留模型、人员、批次、覆盖率、错误数与时间，可搜索和切换当前 Review Run。
- 人工标注为追加式历史，最新一条为当前标注，不覆盖旧 review；「模型为什么判错」是主输入，「模型缺失信息」收进紧凑的结构化多选下拉，并自动汇总为 routing、绕行空间、灯态、双闪、时序等错误聚类。每个 review 版本可粘贴或选择最多 4 张补充截图；场景 Tags 为可选的规范化多选项。
- 页面可提交单 case 推理：模型名、base URL、API key 临时输入，调用 `ra_auto_triage` 的受控 worker；每次调用只产生一个可审计的 Inference Job，不会自动加入 Model Run 或 Review 统计。
- 推理 worker 固定 `RA_TOOLS_ENABLED=false` 和 `BAG_CACHE_READ_ONLY=true`，不会创建 model-triage batch 或写 Trail。

## 对象生命周期与人员归属

批量评测、Trail 快照和单 case 调试是三种不同对象：

```text
JSON / CSV / XLSX 批量结果 ──> 不可变 Model Run ──> Review 与统计
Trail 只读字段检查 ──> 显式创建/复用不可变 Trail Run ──> Review 与统计
单 case 模型调用 ──> Inference Job ──> 任务历史（不会自动晋升为 Run）
```

- **Model Run** 是一组模型输出的不可变快照。Review 每次选择一个 Run 与 0508 GT 对比；切换当前 Run 不会修改 GT、人工复核或团队默认 Run。
- **Trail Run** 也是 Model Run，只是来源为某个 Trail view 的只读字段快照。相同规范化内容复用已有 Run，任意结果变化才创建新 Run。
- **Inference Job** 是一次单 issue 调试调用，保存请求人、非密钥配置、状态和结果历史，但不写入 `model_predictions`。共享列表/API 不返回模型 base URL 或服务器日志路径；需要批量比较时，应整理为标准结果文件并显式导入新的不可变 Run。

页面默认展示团队全部数据，不按当前登录人裁剪；人员字段各自表达不同含义：

- `创建人`：谁在页面上传批量结果或创建 Trail 快照。
- `实验作者`：结果包中声明的 `experiment.author` 等元数据；它来自文件内容，不等同于可信 SSO 身份。
- `复核人`：人工 review 最新标注的作者，可在 Review 页面筛选。
- `请求人`：谁发起单 case Inference Job，可在任务历史中筛选。

Runs 的「人员」统一显示/筛选创建人；旧 Run 没有创建人时回退到结果包实验作者，搜索框仍可检索两者。Review 提供复核人筛选，单 case 任务历史提供请求人及任务状态筛选。两者都不存在时显示为未记录。

当前 cloud_server 上的 `Qwen3.5-9B-finetuned/base` Run 覆盖 **348 / 1071**，是结果文件本身的 `lowconf348` / `runtime_overrides.limit=348` 输入子集，不是 SSO 或页面按用户过滤得到的子集。

## 数据边界

代码与可变数据分开：

- 代码：`/volume/home/workspace/ra_tools/ra_triage_dashboard`
- 可变数据：`/volume/home/workspace/ra_triage_dashboard_data`
- Review 截图：`/volume/home/workspace/ra_triage_dashboard_data/review_attachments`
- Ares 输入资产：`/volume/home/workspace/ra_auto_triage/bags/ares_capture_bev`（只读）
- Camera 输入资产：`/volume/home/workspace/ra_auto_triage/bags/camera`（只读）
- 0508 GT 快照：`/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx`（只读）
- 模型 / Trail 读取逻辑：`/volume/home/workspace/ra_auto_triage`（只读调用）

API key 仅存在于 HTTP 请求和 worker stdin 的内存中；不会写入 SQLite、任务配置、命令行参数、环境变量或 worker 日志。页面提交后立即清空输入框。

Review 截图绑定到单条追加式 annotation：前端粘贴后先本地预览，保存时才上传；后端在受限后台线程中解码并重新编码为 PNG/JPEG/WebP，去除原始元数据。每次最多 4 张、单张 8 MB、总计 24 MB，单图不超过 4000 万像素；HTTP 请求上限为 26 MB，缺少 `Content-Length` 或固定同源请求标记会在 multipart 解析前拒绝，应用级截图配额为 20 GB，并保留至少 256 MB 磁盘空间。API 只返回附件 ID、尺寸、类型和不含服务器路径的读取 URL。备份 SQLite 时必须同时备份 `review_attachments/`，否则历史记录仍在但图片文件无法恢复。

场景 Tags 可以不选。新页面只提供固定 key：`left_turn`、`right_turn`、`straight`、`traffic_light`、`queue`、`temporary_stop`、`occlusion`、`vulnerable_road_user`、`passable_space`、`swag`、`gt_boundary`；常见旧中文值会映射到对应 key。为兼容旧 JSON 客户端，长度和字符合法的历史自由 tag 仍可保存并按原样展示，但新 UI 不再产生这类值。

## 用户身份与后续 SSO

当前直接 IP 部署没有可信的 SSO ingress，后端默认不信任任何客户端身份 header。页面会尝试从访问者本机 LCA `/lcainfo` 响应中**只提取** `LocalUserAccount`，用作页面显示和默认标注人；不会上传、返回或保存 LCA 响应中的 token。该用户名在 UI 中明确标记为「未验证」，不能用于权限判断。

当前数据和 Review 截图都属于看板团队共享内容：任何能访问直接 IP 的用户都可以读取，不能在截图中粘贴超出该协作范围的敏感信息。正式多人使用必须通过 HTTPS + SSO ingress 限制访问，并在 ingress 再配置请求体大小、速率和审计策略。

直接 IP / 本机 LCA 下填写的创建人、复核人或请求人可以作为协作线索保存，但会同时记录为未验证来源；不能据此授权「设为团队默认」等共享操作。结果文件中的实验作者同样只是声明信息。当前后端只有可信代理 SSO 用户可以设置团队默认 Run。

套内网域名并接入 SSO 代理后，应由 ingress 先清除客户端同名 header，再注入唯一身份 header，并确保服务只能从该代理访问。完成这些网络约束后才启用：

```bash
export DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=true
export DASHBOARD_IDENTITY_HEADER=X-SSO-User
export DASHBOARD_TEAM_DEFAULT_MANAGERS=alice,bob
```

可信代理身份会覆盖前端提交的 Run `created_by`、标注 `author` 和任务 `requested_by`，并记录身份来源及 `verified=true`。团队默认 Run 还需要用户名出现在 `DASHBOARD_TEAM_DEFAULT_MANAGERS`；空名单表示无人可修改，不能把“已登录”直接当成管理员权限。在完成上述约束前保持代理身份开关为默认 `false`；Runs、复核和任务列表仍展示所有人的数据，只是不会把未验证姓名当作权限依据。同名记录同时含可信与未验证来源时，筛选项显示为「混合身份」，不会把整组误标为 SSO。

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

Trail 只消费 `ra_stuck_auto_result` 和 `ra_stuck_auto_result_info`。可通过 `DASHBOARD_TRAIL_VIEW_ID` 指向包含这两个字段的 view：

1. 点击「检查字段可见性」，只读检查字段、完整性和可用覆盖数，不创建 Run。
2. 检查通过后点击「创建只读 Trail 快照」，创建或复用本地不可变 Run。

只有全部 baseline issue 分片完整返回时才允许创建快照；任一分片失败、返回不完整、结果字段不可见或没有三分类标准标签，都不会创建 Run。查询完整不代表预测必须全量：模型字段可只有部分 issue 有有效预测，页面会明确显示实际覆盖数；`nan`、`<NA>` 或未知字符串不会被误计为可用标签。Trail 检查和快照均不写回 Trail、不修改 GT 或人工复核，也不改变团队默认 Run。如果 view 没有展示字段，页面会明确提示并保留 CSV/JSON/XLSX 上传入口。

## cloud_server 启动

```bash
cd /volume/home/workspace/ra_tools/ra_triage_dashboard
bash scripts/bootstrap_cloud_server_env.sh
bash scripts/run_cloud_server.sh
```

启动脚本固定使用 `/volume/home/workspace/ra_triage_dashboard_venv`，不再依赖 cloud_server 的全局 Python 包；其中 `python-multipart>=0.0.18`、`Pillow>=10.3` 是截图上传的安全最低版本。当前试运行监听 `0.0.0.0:8785`，可从内网直接访问 `http://172.16.145.60:8785`。因为这是明文 HTTP，单 case 推理只应使用临时、低权限 key；生产多人使用应迁到 HTTPS + SSO 认证代理。

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

`migrations/postgres/001_initial.sql` 提供了与当前表一致的 PostgreSQL schema。已有旧 MVP schema 按需依次执行：

1. `002_review_baseline_fields.sql`：补齐 baseline 与 review 字段。
2. `003_identity_attribution.sql`：为 annotations、model_runs 和 inference_jobs 增加身份来源与可信状态，并为复核人、Run 创建人和任务请求人建立索引。
3. `004_review_attachments.sql`：增加 annotation 级截图元数据；二进制文件仍保存在独立附件目录。

`003_identity_attribution.sql` 对旧行使用 `legacy` / `verified=false`，不会把历史自由填写姓名升级成可信 SSO。所有人工标注、模型结果、任务记录与附件元数据都保留历史行，因此迁移时是一次数据复制，不需要把旧记录扁平化或覆盖；附件二进制需另行迁移。上述 SQL 仍只是 PostgreSQL 目标 schema 与迁移准备；当前运行 adapter 仍是 SQLite。

接入正式 PostgreSQL 后应同步完成：

1. 用 Alembic/SQLAlchemy 替换当前 SQLite storage adapter。
2. 接入 SSO / 反向代理，将创建人、复核人和请求人统一绑定可信身份。
3. 为导入、团队默认变更、推理和 Trail 回写（若后续开放）添加 RBAC 与审计。
