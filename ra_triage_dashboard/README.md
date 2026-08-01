# RA Triage Workbench

一个独立于 `ra_auto_triage` 的 issue triage / 标注 / 模型结果对比看板。

## 当前 MVP（v1.7）

- 默认工作集是 `trail_label_baseline_20260729.xlsx` 中 `dataset=0508` 的 **1071 条**；GT 只来自该快照，不因 Trail 查询或模型导入而改变。
- 首页是服务端筛选的紧凑 Issue 缩略图队列（宽屏五列、随可用宽度降列），默认每页 20 条并可切换 10 / 20 / 50 / 100；页码和单页数量写入 URL，接口单页最多返回 100 条。BEV 缩略图按源文件版本生成 640×360 缓存并懒加载，不把 1071 张原图一次送进浏览器。点击 Issue 后才进入 URL 可恢复的详情态，加载大图、媒体、模型输出和人工 Review；详情支持返回列表及跨页上一/下一 Issue，并在具备 trip 与事件时间戳时提供同域 Ares Studio ±10 秒跳转链接。Issue 详情第二行通过紧凑下拉框切换 `BEV 图片 / Camera 图片 / Ares Studio 视频`，相邻的同尺寸按钮展开完整预览，有视频时默认展示视频；Gallery 卡片的“媒体预览”和详情媒体共用一个近乎占满浏览器视口的三模式弹窗，首页仅在点击预览时按需读取该 Issue 的完整资产。详情页媒体快捷键采用页面级监听：焦点不在输入、选择、按钮或链接时，`B/C/V`、空格、左右方向键和 `F` 无需聚焦播放器即可生效；打开弹窗后由弹窗接管。三种媒体都默认适配可视范围，并支持 1:1 原始像素、按钮/键盘/Ctrl/⌘+滚轮缩放、放大后指针拖拽平移以及全屏；进入或退出全屏不会重置缩放比例。BEV 视频使用 Workbench 自有的紧凑控制条，支持播放/暂停、0.5× / 1× / 1.5× / 2×、回到 t0、进度拖动、可配置 0.1 / 0.5 / 1 / 5 秒左右跳转和键盘控制；默认左右跳转 1 秒，元数据帧步长作为“1 帧”选项，切换到图片时暂停但保留播放位置。
- 首页的“模型判断结果”是下拉筛选：选择模型 Run 后可切换 `全部`、红色 `MISMATCH`、绿色 `MATCH` 和灰色 `NONE（未预测）`；卡片右上角同步显示状态。旧 `failure=1` / `failure_only=true` 仍兼容为 `MISMATCH`，新 Review URL 使用 `comparison=all|mismatch|match|none`。
- 左侧工具栏只接受用户手动折叠并记住偏好，不再根据分辨率、DPR 或窗口宽度自动改变。判错复核、原因聚类、模型 Runs / 导入、Batch 预测分别使用 `/review`、`/review-analysis`、`/runs`、`/batch-prediction` 独立路由，支持硬刷新和浏览器前进/后退。`/import` 会 307 跳转到 `/runs?import=...`，`/inference` 仅作为旧链接兼容入口。
- Trail 操作分成「检查字段」和「创建 Run」两步，收在 Runs 页的默认折叠区；两步都不写回 Trail，快照只创建或复用本地不可变 Run，且不会修改团队默认 Run。启动时若启用 Trail 检查，也只执行第一步。
- 页面只允许导入批量模型输出（JSON、CSV、XLSX），Issue / GT 上传入口已移除，避免误污染 0508 baseline；后端旧 `/api/import/issues` 仅保留兼容客户端，不由页面调用。Runs 页上方用三个自然高度 Tab 统一组织模型文件、AutoTriage 快照和 Trail 快照，页面标题始终固定为 `MODEL RUN REGISTRY / 模型结果 Runs`，不会随来源 Tab 改名；每条 Run 都显示来源徽标及原始 records 链接、文件名或 Trail view。新上传的模型结果原文件按 SHA-256 归档到 dashboard data 的 `uploads/`，Run 行可直接在页面内预览 CSV/JSON 或下载；历史 Run 若没有归档文件，会优先用已保存的脱敏预测行重建可复核副本，并明确标注“Run 重建”。Run 行提供带二次确认的删除按钮：只删除该 Run 的模型输出和来源归档，不删除 0508 GT、Issue 或人工 review；团队默认 Run 需先切换后才能删除。也可按 AutoTriage Batch ID / records 链接经固定只读内网接口拉取结果，或检查 Trail 字段后创建只读快照。所有模型结果都按规范化内容 SHA-256 创建或复用不可变 Model Run，不覆盖 GT、不切换团队默认 Run；AutoTriage 拉取会显式比较声明数、完成数、结果数和唯一 Issue 数，并标记部分覆盖。
- 人工标注为追加式历史，最新一条为当前标注，不覆盖旧 review；「模型为什么判错」是主输入，「模型缺失信息」收进紧凑的结构化多选下拉，并自动汇总为 routing、绕行空间、灯态、双闪、时序等错误聚类。每个 review 版本可粘贴或选择最多 4 张补充截图；场景 Tags 为可选的规范化多选项。
- 页面每约 1.8 秒只读检查一次共享数据 revision；只有 Issue、Review、Run、预测或 Batch 状态确实变化时才刷新当前页面。多人同时 Review 时，正在编辑的表单和待上传截图不会被后台刷新覆盖，而会在保存后合并最新数据。API 响应包含 `Server-Timing` 与 `X-Request-Duration-Ms`，超过 500 ms 的 API 请求写入服务慢请求日志。
- 原因聚类页只消费每个 Issue 最新一版 Review：稳定的 `missing_evidence[]` 是主聚类，Review 自由文本通过可解释关键词 v1 形成多标签主题，未填写和有文本但未命中主题的记录会单独计数。顶部可按场景 Tags 筛选；检索只匹配最新人工 Review 的原因、复核人、标签、状态与缺失信息，不检索模型说明或 Issue 场景文本。选择 Model Run 后，“模型判断结果”可按红色 `MISMATCH`、绿色 `MATCH`、灰色 `NONE（未预测）` 或全部切片，混淆矩阵与 Case 明细使用同一状态；明细行以 Issue ID 直接链接 Voyager，模型标签点击后按需加载并复用评测 Run 历史弹窗，不再显示冗余的空人工标签。当前筛选结果可导出 UTF-8 CSV 或 XLSX；筛选、聚类和分页都写入 `/review-analysis` URL，可硬刷新并用浏览器前进/后退恢复。
- 首页可把当前单个 Issue 或不超过 50 条的完整筛选结果预填到 Batch 页面；若前端只加载到部分结果或超过上限，会明确阻止而不是静默截断。模型目录保留 Profile 已验证项和网关当前在线的 Qwen3 生成模型，排除 Embedding；实验模型有明确标记且创建任务前需再次确认。默认 `Auto` 仍解析并分别记录 requested / resolved model ID。
- 每个 Batch 固化请求人、模型验证层级、完整 Prompt 正文与 SHA-256、Prompt 基线版本/是否编辑、Camera 帧偏移、RA Events / RA-SWAG Options 和输入 Profile；任务历史可按人员、状态、模型、Prompt 精确版本（mode + SHA）和输入筛选，已下线模型与旧 Prompt 也保留在筛选项中。批次名默认按 `当前用户_i_YYYYMMDD_HHmmss` 生成，Issue IDs 使用紧凑单行输入但仍支持逗号/空格分隔。Prompt 只允许当前三分类构建器提供的变量，必须保留三个标准标签，并拒绝会输出「无法判断」等第四类的旧模板；Camera 偏移严格递增、包含 0、最多 18 帧。worker 会重新校验 Prompt/Input 快照并重建配置 Hash，预测与后续发布必须一致。
- 网关 API key 只从服务用户持有的 `0600` 普通文件读取，经一次性 stdin 交给预测 worker，读取后立即从请求对象移除；不接受浏览器或父进程环境变量中的 key，也不会把 key 交给 AutoTriage publish worker。Batch 页只展示服务端登记的 Provider 列表，Kylin 与 TokenService 都可在已登记对应 key 文件时选择；模型目录、Provider、请求地址和凭证会随 Batch 固化但不会把 key 写入浏览器或 SQLite。TokenService 的在线 Qwen3 模型默认按实验模型处理，创建前需要确认；自定义 Provider 必须先在 cloud_server 服务端登记。Ares / BEV 和轨迹摘要在 Batch 输入中强制关闭。
- Batch 采用两阶段写入：预测阶段只在 dashboard 自己的 `batch_bags/` 缓存中下载/复用 Camera 与 gateway bag，绝不修改 `ra_auto_triage/bags`；同时强制禁用 Ares、禁止 Trail 写和 AutoTriage 写。可信 SSO 用户显式点击「推送 AutoTriage」后，才用 cloud_server 固定服务身份创建生产 Batch、推送成功结果并关联 `records/{batch_id}?tab=results`。重复点击已有 Batch 的任务只返回原链接，不再次建批。
- Batch 预测任务先持久化为 `queued`，单 worker 按创建时间顺序执行；runner 忙碌时新任务保留排队而不是返回 409 并标记失败。服务重启只终止原先的 `running` 任务，尚未开始的 `queued` 任务会在启动后自动续跑。

## 对象生命周期与人员归属

模型文件、Trail 快照和 AutoTriage 拉取是三条明确的对象链；网页 Batch 预测作为第四种 Run 来源保留：

```text
JSON / CSV / XLSX 批量结果 ──> 不可变 Model Run ──> Review 与统计
Trail 只读字段检查 ──> 显式创建/复用不可变 Trail Run ──> Review 与统计
AutoTriage Batch 只读拉取 ──> 不可变 autotriage_snapshot Run ──> Review 与统计
Issue 列表 ──> Batch Prediction Job ──> 不可变 manual_batch Run
                                      └─> 显式推送 ──> AutoTriage Batch 链接
最新人工 Review ──> 稳定缺失信息聚类 + 可解释原因主题 ──> 返回单 Issue 复核
```

- **Model Run** 是一组模型输出的不可变快照。Review 每次选择一个 Run 与 0508 GT 对比；切换当前 Run 不会修改 GT、人工复核或团队默认 Run。
- **Trail Run** 也是 Model Run，只是来源为某个 Trail view 的只读字段快照。相同规范化内容复用已有 Run，任意结果变化才创建新 Run。
- **AutoTriage Snapshot Run** 是平台 Batch detail/results 的只读内容快照。平台用户保留为来源元数据，实际在页面执行拉取的人保留为 Run 创建人；两者不混用。
- **Batch Prediction Job** 保存一批 Issue 的进度、requested / resolved 模型 ID、验证层级、Prompt/Input 快照与 Hash、结果、请求人和独立推送状态。预测成功项自动进入不可变 Run；推理失败和 AutoTriage 写入失败可以分别查看。旧 `inference_jobs` 只为历史兼容保留 GET，旧 POST 返回 `410`。

页面默认展示团队全部数据，不按当前登录人裁剪；人员字段各自表达不同含义：

- `创建人`：谁在页面上传批量结果或创建 Trail 快照。
- `实验作者`：结果包中声明的 `experiment.author` 等元数据；它来自文件内容，不等同于可信 SSO 身份。
- `复核人`：人工 review 最新标注的作者，可在 Review 页面筛选。
- `请求人`：谁发起网页 Batch，可在任务历史中筛选。
- `AutoTriage writer`：cloud_server 用来写生产平台的固定服务身份；它与直接 IP 页面提交的未验证请求人是两个字段。

Runs 的「人员」统一显示/筛选创建人；旧 Run 没有创建人时回退到结果包实验作者，搜索框仍可检索两者。Review 提供复核人筛选，单 case 任务历史提供请求人及任务状态筛选。两者都不存在时显示为未记录。

当前 cloud_server 上的 `Qwen3.5-9B-finetuned/base` Run 覆盖 **348 / 1071**，是结果文件本身的 `lowconf348` / `runtime_overrides.limit=348` 输入子集，不是 SSO 或页面按用户过滤得到的子集。

## 数据边界

代码与可变数据分开：

- 代码：`/volume/home/workspace/ra_tools/ra_triage_dashboard`
- 可变数据：`/volume/home/workspace/ra_triage_dashboard_data`
- Review 截图：`/volume/home/workspace/ra_triage_dashboard_data/review_attachments`
- Issue 缩略图缓存：`/volume/home/workspace/ra_triage_dashboard_data/case_thumbnails`（可重建）
- Batch bag 缓存：`/volume/home/workspace/ra_triage_dashboard_data/batch_bags`（可重建、与 RA 仓库隔离）
- 模型网关密钥：`/volume/home/workspace/ra_triage_dashboard_data/model_gateway_api_key`（服务用户持有的 `0600` 普通文件，不进入代码备份）
- TokenService 网关密钥：`/volume/home/workspace/ra_triage_dashboard_data/tokenservice_api_key`（同样由服务用户持有、`0600`，不进入代码备份；未配置时 Provider 只读展示）
- RA 模型 Profile：`config/model_profiles.json`（版本化兼容白名单，不含凭证）
- Ares 输入资产：`/volume/home/workspace/ra_auto_triage/bags/ares_capture_bev`（只读）
- Ares BEV 视频资产：`/volume/home/workspace/ra_auto_triage/bags/ares_capture_video_0508_1071_ra_stuck_swag_planning_2k_20260731`（只读，可用 `ARES_CAPTURE_VIDEO_ROOT` 覆盖）
- Camera 输入资产：`/volume/home/workspace/ra_auto_triage/bags/camera`（只读）
- 0508 GT 快照：`/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx`（只读）
- 模型 / Trail 逻辑：`/volume/home/workspace/ra_auto_triage`（代码与原有 bag 只读；Batch 新下载只写 dashboard 独立缓存）

模型 endpoint 是服务端固定配置，API key 只存在于上述受限文件和预测 worker 的一次性 stdin，不进入浏览器 HTTP 请求、dashboard SQLite、argv、子进程环境或公共 API。Batch Run 只保存脱敏后的模型、Prompt、输入策略、目录 SHA-256 和配置 SHA-256；上传 JSON / CSV / XLSX 时，metadata、原始行和扩展字段中的 credential / endpoint key 也会在入库前递归脱敏，公共读取再执行一次同样的防护。模型结果原文件只通过同源 Run source endpoint 提供 inline 预览或 attachment 下载，不直接暴露服务器路径；遗留 Run 不会凭空补造归档文件。

AutoTriage 拉取同样是服务端固定来源，默认
`DASHBOARD_AUTOTRIAGE_API_BASE_URL=http://10.190.57.183:8000`。浏览器提供的
records 链接只用于提取数字 Batch ID，后端不会跟随其中的 hostname；客户端禁用
代理和重定向，拉取只产生本地不可变 Run，不调用平台写接口。

当前网关对外契约是内网 HTTP；2026-07-30 实测 HTTPS 入口的证书已过期，无法在保持证书校验的前提下切换。因此 key 的网络传输目前依赖受控内网边界，仍是已知运营风险。证书续期后应把 catalog / chat URL 一并切换到 HTTPS；代码会继续校验固定 hostname、禁用代理和重定向，不能用关闭证书校验替代修复。

Review 截图绑定到单条追加式 annotation：前端粘贴后先本地预览，保存时才上传；后端在受限后台线程中解码并重新编码为 PNG/JPEG/WebP，去除原始元数据。每次最多 4 张、单张 8 MB、总计 24 MB，单图不超过 4000 万像素；HTTP 请求上限为 26 MB，缺少 `Content-Length` 或固定同源请求标记会在 multipart 解析前拒绝，应用级截图配额为 20 GB，并保留至少 256 MB 磁盘空间。API 只返回附件 ID、尺寸、类型和不含服务器路径的读取 URL。备份 SQLite 时必须同时备份 `review_attachments/`，否则历史记录仍在但图片文件无法恢复。

场景 Tags 可以不选。新页面只提供固定 key：`queue`、`yielding`、`u_turn`、`park_in`、`park_out`、`traffic_light`、`manual_trigger`、`perception_fp_cleared`、`lead_vehicle_departed`、`system_decision_change`、`obstacle_not_avoided`、`close_distance`；常见旧中文值仍会按兼容规则保存并按原样展示。缺失信息默认预选 `routing_direction`，Review 内可新建 `custom:<文本>` 作为本条记录的结构化补充字段。

## 用户身份与后续 SSO

当前直接 IP 部署没有可信的 SSO ingress，后端默认不信任任何客户端身份 header。页面会尝试从访问者本机 LCA `/lcainfo` 响应中**只提取** `LocalUserAccount`，用作页面显示和默认标注人；不会上传、返回或保存 LCA 响应中的 token。该用户名在 UI 中明确标记为「未验证」，不能用于权限判断，也不会成为 AutoTriage writer。

AutoTriage 推送默认关闭（`DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false`），即使打开开关也必须通过后端验证的 SSO 身份；自定义请求头和浏览器提交姓名只用于请求完整性/展示，不能授权生产写入。套好内网域名、清除客户端伪造 header 并由 ingress 注入可信身份后，再显式打开该开关。Batch 预测本身不依赖此开关。

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

Runs 行的 CSV/JSON「预览」调用同源 `GET /api/model-runs/{run_id}/source-preview?page=1&page_size=100`，页面内全屏分页查看完整数据（单页最多 200 行），并对单元格做长度限制和敏感字段脱敏；「下载」调用 `GET /api/model-runs/{run_id}/source?download=1`。早期未归档但仍保留预测行的 Run 会生成 `reconstructed-model-run-v1` 复核副本并显式标记，不冒充原始文件。

GT 导入默认不会覆盖已有 GT，只有在 UI 勾选明确覆盖时才会改写。

AutoTriage 快照导入只接受数字 Batch ID 或能提取该 ID 的 records 链接。后端
重新拉取 Batch detail 与 results，只接受三个标准标签，并把平台用户、模型、
Prompt 版本/Hash 和覆盖情况保存为来源元数据；平台返回的 GT 只保留在脱敏原始
行中，不会更新 Workbench baseline。

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

启动脚本默认使用 `/volume/home/workspace/ra_triage_dashboard_venv`，并监听 `0.0.0.0:8785`；可通过 `DASHBOARD_VENV_DIR`、`DASHBOARD_HOST`、`DASHBOARD_PORT` 和 `DASHBOARD_DATA_DIR` 覆盖，便于隔离 staging。该 venv 继承 cloud_server 已验证的 RA / Trail 依赖栈，并在环境内覆盖截图入口所需的安全版本；Batch worker 会先加载 Voyager 环境，再用同一 Python 调用 `ra_auto_triage`。当前试运行可从内网直接访问 `http://172.16.145.60:8785`。直接 IP 是明文 HTTP 且无可信 SSO，只适合受控内网试用；正式多人使用应迁到 HTTPS + SSO 认证代理。

页面路由可直接访问：

- `http://172.16.145.60:8785/review`
- `http://172.16.145.60:8785/review-analysis`
- `http://172.16.145.60:8785/runs`
- `http://172.16.145.60:8785/batch-prediction`
- `http://172.16.145.60:8785/runs?import=model`

Review 首页筛选参数可写入 URL：

```text
/review
  ?run=<model_run_id>
  &comparison=all|mismatch|match|none
  &failure=1                 # 旧链接，等价于 comparison=mismatch
  &q=<search>
  &gt=<三分类标签>
  &annotation=<三分类标签>
  &reviewer=<author>
  &evidence=<stable_missing_evidence_key>
  &page=<positive_integer>
```

原因聚类页 URL 契约：

```text
/review-analysis
  ?run=<model_run_id>|none
  &comparison=all|mismatch|match|none
  &reviewer=<author>
  &status=pending|reviewed|needs_gt_review
  &gt=<三分类标签>
  &annotation=<三分类标签>
  &evidence=<stable_missing_evidence_key>
  &theme=<stable_reason_theme_key>
  &tag=<stable_scenario_tag_key>
  &q=<search>
  &page=<positive_integer>
```

`run=none` 明确表示查看全部最新 Review 且不叠加模型输出，此时 `comparison` 只能为
`all`。`NONE` 表示所选 Run 对该 baseline Issue 没有有效三分类预测。旧
`failure=1` 链接仍会兼容解析为 `comparison=mismatch`。第一版原因主题是透明、确定性的
多标签关键词规则，API 会返回主题说明与命中词；
后续若加入 embedding / LLM 语义聚类，应使用新的方法版本并保留这一可复现基线，不能静默改变
历史人工标注或现有主题 key。

原因聚类数据接口为 `GET /api/review-reason-analysis`；同一组筛选参数可传给
`GET /api/review-reason-analysis/export?format=csv|xlsx` 导出全部命中行（不受页面
50 条分页限制）。导出会防护电子表格公式注入，CSV 带 UTF-8 BOM 便于直接用 Excel 打开。

旧 `/import?kind=issues|model` 仍可访问，但统一跳转到仅支持模型结果的 Runs 导入区；页面不会提供 Issue / GT 上传控件。后端 `/api/import/issues` 仍为兼容旧客户端保留，不能用于修改 0508 baseline 的页面流程。

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
4. `005_batch_prediction_jobs.sql`：增加 Batch Prediction Job / Item、不可变 Model Run 关联和 AutoTriage 推送审计字段。
5. `006_batch_model_selection.sql`：为既有 Batch Job 增加 requested / resolved 模型 ID、模型来源和目录指纹。
6. `007_batch_prompt_input.sql`：增加模型验证层级、完整 Prompt 快照/Hash、输入 Profile 和输入配置 JSON 及筛选索引。
7. `008_change_revision.sql`：增加跨页面共享 revision 及事务内更新 trigger，为轻量多人同步提供依据。

`003_identity_attribution.sql` 对旧行使用 `legacy` / `verified=false`，不会把历史自由填写姓名升级成可信 SSO。所有人工标注、模型结果、任务记录与附件元数据都保留历史行，因此迁移时是一次数据复制，不需要把旧记录扁平化或覆盖；附件二进制需另行迁移。上述 SQL 仍只是 PostgreSQL 目标 schema 与迁移准备；当前运行 adapter 仍是 SQLite。

接入正式 PostgreSQL 后应同步完成：

1. 用 Alembic/SQLAlchemy 替换当前 SQLite storage adapter。
2. 接入 SSO / 反向代理，将创建人、复核人和请求人统一绑定可信身份。
3. 为导入、团队默认变更、推理和 Trail 回写（若后续开放）添加 RBAC 与审计。
