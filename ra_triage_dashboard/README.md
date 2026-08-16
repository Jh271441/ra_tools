# RA Triage Workbench

一个独立于 `ra_auto_triage` 的 issue triage / 标注 / 模型结果对比看板。

## 当前产品快照

- 默认工作集成员固定为 `trail_label_baseline_20260729.xlsx` 中 `dataset=0508` 的 **1071 条**。同一只读快照还注册了 `dataset=0206` 的 **1326 条**，另有 0626 抽检 **300 条**；三者可在顶栏独立或组合选择，默认仍仅选择 0508。运行时通过固定只读 Trail view 1000 的 `ra_merge_result` 完整校验并覆盖有效 GT。模型导入、Trail 模型字段快照和 AutoTriage 结果仍不能修改 GT。

### 多数据集 Multi-Baseline

同时挂载多个稳定成员集合的 GT 工作集（0508、0206、0626 抽检），顶栏 **多选数据集**，选中集合按 **union** 驱动图库 / 指标 / 原因分析 / 均分 / Runs 覆盖统计。Trail GT overlay 会逐数据集完整校验并独立原子应用；失败时保留该数据集上次成功快照。

| 项 | 说明 |
|----|------|
| 配置 | `config/baselines.json`（可用 `DASHBOARD_BASELINES_FILE` 覆盖） |
| 默认选择 | 仅 `0508`（与现网一致） |
| Query | `?baselines=0508,0206,0626`（短 id，不接受任意 scope 字符串） |
| 0206 媒体 | planning_2k Ares Capture 产物增量物化到 `release0206_1326_planning_2k_20260813`；媒体缺失不阻塞 GT 看板 |
| 0626 媒体 | bag 源 `frames_v2_0626` + animation jobs；Camera 可空 |
| Batch 推理 | **不**改服务端固定 `bags/ares_animation` 策略（与 review 媒体解耦） |
| 生产隔离 | 新版本先在独立 worktree、临时 SQLite 与 8786 端口验证，再快进生产代码并重启 8785 |

实现入口：`app/baseline_registry.py`、`app/media_registry.py`、DB `baseline_scopes` IN 过滤、顶栏 `#baselineFilter`。
- 首页是服务端筛选的紧凑 Issue 缩略图队列（宽屏五列、随可用宽度降列），默认每页 20 条并可切换 10 / 20 / 50 / 100；页码和单页数量写入 URL，接口单页最多返回 100 条。判错复核与原因聚类统一显示“当前页 / 总页数”和显式跳转输入框、按钮；只有按回车或点击跳转按钮才执行，输入框失焦不会误跳页。BEV 缩略图按源文件版本生成 640×360 缓存并懒加载，不把 1071 张原图一次送进浏览器。点击 Issue 后才进入 URL 可恢复的详情态，加载大图、媒体、模型输出和人工 Review；详情支持返回列表及跨页上一/下一 Issue，并在具备 trip 与事件时间戳时提供同域 Ares Studio ±10 秒跳转链接。Issue 详情第二行通过紧凑下拉框切换 `BEV 图片 / Camera 图片 / Ares Studio 视频`，相邻的同尺寸按钮展开完整预览；有视频时详情默认展示视频首帧，没有视频时再展示 BEV / Camera 图片。Gallery 卡片的“媒体预览”和详情媒体共用一个近乎占满浏览器视口的三模式弹窗，首页仅在点击预览时按需读取该 Issue 的完整资产。详情页媒体快捷键采用页面级监听：焦点不在输入、选择、按钮或链接时，`B/C/V`、空格、左右方向键和 `F` 无需聚焦播放器即可生效；打开弹窗后由弹窗接管。三种媒体都默认适配可视范围，并支持 1:1 原始像素、按钮/键盘/Ctrl/⌘+滚轮缩放、放大后指针拖拽平移以及全屏；进入或退出全屏不会重置缩放比例。BEV 视频使用 Workbench 自有的紧凑控制条，支持播放/暂停、0.5× / 1× / 1.5× / 2×、回到 t0、进度拖动、可配置 0.1 / 0.5 / 1 / 5 秒左右跳转和键盘控制；默认左右跳转 1 秒，元数据帧步长作为“1 帧”选项，切换到图片时暂停但保留播放位置。
- 首页的“模型判断结果”是下拉筛选：选择模型 Run 后可切换 `全部`、红色 `MISMATCH`、绿色 `MATCH` 和灰色 `NONE（未预测）`；卡片右上角同步显示状态。旧 `failure=1` / `failure_only=true` 仍兼容为 `MISMATCH`，新 Review URL 使用 `comparison=all|mismatch|match|none`。
- 管理员“均分当前筛选”只覆盖当前 Review 队列，并保留每次分配的历史审计。任务负责人下拉框的人员与数量严格按当前 baseline、Model Run、判断结果、GT、Review 状态等筛选重新统计；其他数据集或旧 split 的负责人不会混入当前计数，移除本轮人员也不会破坏其历史分配记录。
- 左侧工具栏只接受用户手动折叠并记住偏好，不再根据分辨率、DPR 或窗口宽度自动改变。判错复核、原因聚类、模型 Runs / 导入、Batch 预测、系统状态分别使用 `/review`、`/review-analysis`、`/runs`、`/batch-prediction`、`/system-status` 独立路由，管理员另有 `/users` 用户管理路由；均支持硬刷新和浏览器前进/后退。系统状态页只读展示应用运行时间与版本、数据库连接/持久卷、最近备份/计划、容量、全部已注册 GT 数据集及各自媒体覆盖、模型网关，不提供重启或写入操作；任一已注册数据集未就绪都会让总体状态降级。`/import` 会 307 跳转到 `/runs?import=...`，`/inference` 仅作为旧链接兼容入口。
- 顶栏支持深色 / 浅色主题切换，默认仍为深色；用户选择保存在浏览器 `localStorage`，并在主样式加载前应用，避免刷新时先闪出错误主题。浅色模式覆盖页面框架、表单、卡片、下拉框和弹窗；Ares、BEV 与 Camera 媒体画布继续使用深色舞台，以保持原始画面和轨迹叠加层的对比度。
- Trail 操作分成「检查字段」和「创建 Run」两步，收在 Runs 页的默认折叠区；当前模型字段快照明确只针对 registry 的默认数据集（现为 0508/1071），不跟随顶栏多选切换。两步都不写回 Trail，快照只创建或复用本地不可变 Run，且不会修改团队默认 Run。启动时若启用 Trail 检查，也只执行第一步。
- 权威 GT 同步与模型字段快照是两条独立链路。服务端默认每 30 分钟依次完整读取所有已注册数据集在 Trail view 1000 的 `ra_merge_result`，顶栏也可按当前选中的一个或多个数据集点击「同步」；手动请求会立即返回 `202`，耗时的 Trail 完整校验在后台执行，页面通过共享状态轮询自动显示完成或失败，避免代理长请求超时。每个数据集都必须与自己的完整 issue 集合完全一致且每条都能归一化为三分类才会独立原子应用。各数据集的来源更新时间、Manual 检查时间、应用时间和变更数会分别持久化；一个数据集失败不会阻断其他数据集，失败或部分返回仍保留该数据集上次成功快照。应用 GT 后，Issue GT Review 状态、筛选、比例与混淆矩阵按最新 GT 读时重算，不修改 Review 历史。
- 页面只允许导入批量模型输出（JSON、CSV、XLSX），Issue / GT 上传入口已移除，避免误污染任何 GT 数据集；后端旧 `/api/import/issues` 仅保留兼容客户端，不由页面调用。Runs 页上方用三个自然高度 Tab 统一组织模型文件、AutoTriage 快照和 Trail 快照，页面标题始终固定为 `MODEL RUN REGISTRY / 模型结果 Runs`，不会随来源 Tab 改名；每条 Run 都显示来源徽标及原始 records 链接、文件名或 Trail view。新上传的模型结果原文件按 SHA-256 归档到 dashboard data 的 `uploads/`，Run 行可直接在页面内预览 CSV/JSON/XLSX 或下载；历史 Run 若没有归档文件，会优先用已保存的脱敏预测行重建可复核副本，并明确标注“Run 重建”。Run 行提供带二次确认的删除按钮：只删除该 Run 的模型输出和来源归档，不删除任何 GT 数据集、Issue 或人工 review；团队默认 Run 需先切换后才能删除。也可按 AutoTriage Batch ID / records 链接经固定只读内网接口拉取结果，或检查 Trail 字段后创建只读快照。所有模型结果都按规范化内容 SHA-256 创建或复用不可变 Model Run，不覆盖 GT、不切换团队默认 Run；AutoTriage 拉取会显式比较声明数、完成数、结果数和唯一 Issue 数，并标记部分覆盖。
- 人工标注为追加式历史，最新一条为当前标注，不覆盖旧 review。每条 Review 版本明确绑定创建时选择的 `model_run_id`；切换 Model Run 后，详情编辑表单、历史筛选、列表、原因聚类和统计只读取该 Run 的最新版本，不会把不同 Run 的人工结论混在一起。迁移前的旧记录使用空 Run 标识：选中任意 Run 时不会作为兼容 fallback 混入，只有不选择 Run 的全局历史视图才会读取它们。保存时前端提交编辑开始时看到的版本 ID；若同一 Issue、同一 Run 已被其他人先保存，服务端返回 `409`，后提交者需要刷新后再保存，避免静默覆盖。详情右侧分为两个区域：`Issue 标签` 将场景拆成「环境 / 自车意图」，将触发判定拆成「误触发 / 应该触发」，并把脱困方式拆成「正确触发 / 无需协助」；同时提供 `is_excluded`（应该排除、非模型需要解决的场景）布尔开关。`模型结果 Review` 使用“期望输出”替代人工选择复核状态：误触发 Tags 自动推出 `误触发`，RA/正确触发 Tags 推出 `正确触发`，无需协助 Tags 推出 `无需协助`；真卡但只填“应该触发”时仍需补充驶离结论。唯一推断项会在仍可操作的下拉框内标记“自动推断”；选择其他项会立即显示选择冲突并禁止保存，改回推断项或调整 Tags 后恢复。期望输出留空对应状态「待补充」(`pending`)，与 baseline GT 相同对应「与 GT 一致」(`reviewed`)，不同对应「GT 需复核」(`needs_gt_review`)；详情内的“推算规则”入口解释这两步。多类输出 Tags 冲突时同样显示冲突并禁止保存，服务端也会拒绝；历史 Review 若尚未保存期望输出，分析和 GT 更新表会只读复用同一 Tag 推断，无法唯一推断或冲突时 fail closed 为「待补充」，不会回写历史记录。每个新版本必须记录复核人及其可信状态，右侧 Review 历史把期望输出、状态、复核人、Run 和时间紧凑展示；详情左右外框在桌面端随较高一侧等高。每个版本可粘贴或选择最多 4 张补充截图。
- 页面每约 1.8 秒只读检查一次共享数据 revision；只有 Issue、Review、Run、预测或 Batch 状态确实变化时才刷新当前页面。多人同时 Review 时，正在编辑的表单和待上传截图不会被后台刷新覆盖，而会在保存后合并最新数据。API 响应包含 `Server-Timing` 与 `X-Request-Duration-Ms`，超过 500 ms 的 API 请求写入服务慢请求日志。
- 判错复核首页与原因聚类页共用「Issue GT Review状态」三项筛选：待补充、与 GT 一致、GT 需复核；首页的 Gallery、URL、分页、预测当前筛选和均分任务使用同一筛选范围。原因聚类页用紧凑三段比例条展示当前筛选范围内三种状态的数量和占比；宽屏时它与压缩后的 GT × 模型预测混淆矩阵左右并排，窄屏再恢复上下排列。三段状态条与图例在 hover 或键盘聚焦时联动，混淆矩阵当前格也会同步强调对应 GT 行和模型列并弱化无关格；两处仅高亮，不会隐式改变筛选。页面只消费每个 Issue 最新一版 Review：稳定的 `missing_evidence[]` 是主聚类，Review 结构化 Tags 按「场景 / 触发判定 / 如何脱困」分别筛选，原因卡片标题保持顶部、图表主体在卡片剩余空间垂直居中；下拉筛选选择后立即刷新，搜索输入短暂防抖后立即刷新，不再需要额外点击“应用”；自由文本只作为明细中的解释，不再生成并展示旧的关键词主题卡片。自定义缺失信息按共享目录的正式标题展示，不泄露 `custom:` 或哈希 key。检索只匹配最新人工 Review 的原因、复核人、标签、Issue GT Review状态与缺失信息，不检索模型说明或 Issue 场景文本。选择 Model Run 后，“模型预测”可按三分类标签筛选，另可按红色 `MISMATCH`、绿色 `MATCH`、灰色 `NONE（未预测）` 或全部切片，混淆矩阵与 Case 明细使用同一状态；明细行同时展示 GT、模型结论和人工期望输出。当前筛选结果可导出 UTF-8 CSV 或明细 XLSX；“导出 GT 更新表”额外生成张扬批量回刷工具“期望输出模式”可直接导入的两列表，只包含按“期望输出与 GT 不同”规则判定为需复核的 Issue，不信任历史手选状态。筛选、聚类和分页都写入 `/review-analysis` URL，可硬刷新并用浏览器前进/后退恢复。
- Issue 详情先渲染本地模型、媒体和 Review；随后在 Voyager / Ares Studio 链接之后后台按需补齐 Trail 2410 视图中的只读 `ra_id` 对应的 `RA 录屏`，以及有 `ra_event` 时的 `RA Event` 入口。Trail 请求的延迟、超时或不可用不会阻塞 Issue 首屏，入口会在元数据返回后增量出现。`RA Event` 会直接打开与 Trail 一致的事件表弹窗，支持按事件名/值筛选，并保留 Trail Issue 外链；录屏 URL 由服务端使用 canonical `ra_id` 构造，浏览器不根据时间戳猜任务 ID；Trail 不可用或字段缺失时两个入口自动隐藏。该元数据查询只允许 `ra_id`、`ra_event`、`car_id`、`trip_id` 和 RA 起止时间等字段，独立于模型结果同步，不创建 Run、不写回 Trail。
- 原因聚类 `/review-analysis` 默认每页 20 条，可切换 10 / 20 / 50 / 100；筛选后的明细按 `issue_id` 升序稳定排序，页码和单页数量写入 URL，刷新或前进/后退不会改变顺序。
- 判错复核首页的检索框旁提供「多 Issue」精确查询弹窗。输入支持逗号、中文标点、空格、换行和 Voyager Issue 链接；系统会去重、显示无法识别的 token，并将已确认列表写入 `issue_ids` URL 参数。应用精确列表后会清空普通关键词检索；清空输入并点击查询即可恢复当前 baseline 的默认队列。该筛选只改变读取范围，不创建 Run、不修改 GT。
- 首页可把当前单个 Issue 或不超过 50 条的完整筛选结果预填到 Batch 页面；若前端只加载到部分结果或超过上限，会明确阻止而不是静默截断。Batch 页直接选择服务端 Provider，模型列表隐藏仅用于服务端解析的 `Auto` 别名，并保留 Profile 已验证项和网关当前在线的 Qwen3 生成模型，排除 Embedding；实验模型有明确标记且创建任务前需再次确认。默认 Camera 输入与 `stuck_triage_auto_opt_api` 对齐为 -19s 至 +19s 的单前视 9 帧，Ares Animation 可切换且只使用服务端固定的 API 默认 manifest/时间点，浏览器不能提交路径或 Ares Capture 配置。
- 每个 Batch 固化请求人、模型验证层级、完整 Prompt 正文与 SHA-256、Prompt 基线版本/是否编辑、Camera 帧偏移、RA Events / RA-SWAG Options 和输入 Profile；任务历史可按人员、状态、模型、Prompt 精确版本（mode + SHA）和输入筛选，已下线模型与旧 Prompt 也保留在筛选项中。批次名默认按 `当前用户_YYYYMMDD_HHmmss` 生成（不再带实习生 `_i` 标识），Issue IDs 使用紧凑单行输入但仍支持逗号/空格分隔。Prompt 只允许当前三分类构建器提供的变量，必须保留三个标准标签，并拒绝会输出「无法判断」等第四类的旧模板；Camera 偏移严格递增、包含 0、最多 18 帧。worker 会重新校验 Prompt/Input 快照并重建配置 Hash，预测与后续发布必须一致。
- 网关 API key 只从服务用户持有的 `0600` 普通文件读取，经一次性 stdin 交给预测 worker，读取后立即从请求对象移除；不接受浏览器或父进程环境变量中的 key，也不会把 key 交给 AutoTriage publish worker。Batch 页只展示服务端登记的 Provider 列表，Kylin 与 TokenService 都可在已登记对应 key 文件时选择；模型目录、Provider、请求地址和凭证会随 Batch 固化但不会把 key 写入浏览器或 SQLite。TokenService 的在线 Qwen3 模型默认按实验模型处理，创建前需要确认；自定义 Provider 必须先在 cloud_server 服务端登记。轨迹摘要与 Ares Capture 在 Batch 输入中强制关闭，Ares Animation 只能选择固定的服务端 API 默认策略。
- Batch 采用两阶段写入：预测阶段只在 dashboard 自己的 `batch_bags/` 缓存中下载/复用 Camera 与 gateway bag，绝不修改 `ra_auto_triage/bags`；Ares Animation 只读服务端既有 manifest，并继续禁止 Trail 写和 AutoTriage 写。可信 SSO 用户显式点击「推送 AutoTriage」后，才用 cloud_server 固定服务身份创建生产 Batch、推送成功结果并关联 `records/{batch_id}?tab=results`。重复点击已有 Batch 的任务只返回原链接，不再次建批。
- Batch 预测任务先持久化为 `queued`，单 worker 按创建时间顺序执行；runner 忙碌时新任务保留排队而不是返回 409 并标记失败。服务重启只终止原先的 `running` 任务，尚未开始的 `queued` 任务会在启动后自动续跑。

### Trail 模型字段灰度验证记录（2026-08-17）

- 8786 灰度实例使用隔离 SQLite 与 `DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false`，因此网页 Trail Attribute Update 仍然 fail-closed，不会因为字段配置缺失而产生批量写入。
- 在写入开关关闭的前提下，使用 `ra_auto_triage.utils.trail_api.TrailInterface.update_issue_with_changes` 对单个受控 Issue `cn32171803` 做了实际 API smoke write/readback；写入字段为 `ra_stuck_auto_result=误触发` 与包含 `model_run_id=6d4f4a17-4a7e-420e-a38b-39a632b6a248`、`review_id=1`、`should_exclude=true` 的 `ra_stuck_auto_result_info`，随后通过本地 `ra_api.issue_api.TrailInterface.query_by_issue_id_list` 读回完全一致。
- 这次验证证明 Trail API 的字段写入与读回链路可用，但不代表 Dashboard 可以安全开启批量回刷：View 2410 的字段可见性检查仍返回空字段，因此必须先在 Trail 侧把两个目标字段加入该 View，并在 8786 重新预览、逐条核对后才允许打开 writer。8785 生产实例及其数据库未被本次 smoke 修改。

## 对象生命周期与人员归属

模型文件、Trail 快照和 AutoTriage 拉取是三条明确的对象链；网页 Batch 预测作为第四种 Run 来源保留：

```text
JSON / CSV / XLSX 批量结果 ──> 不可变 Model Run ──> Review 与统计
Trail 只读字段检查 ──> 显式创建/复用不可变 Trail Run ──> Review 与统计
AutoTriage Batch 只读拉取 ──> 不可变 autotriage_snapshot Run ──> Review 与统计
Issue 列表 ──> Batch Prediction Job ──> 不可变 manual_batch Run
                                      └─> 显式推送 ──> AutoTriage Batch 链接
最新人工 Review ──> 稳定缺失信息聚类 + 结构化 Tags 筛选 ──> 返回单 Issue 复核
```

- **Model Run** 是一组模型输出的不可变快照。Review 每次选择一个 Run 与当前顶栏选中的 GT 数据集 union 对比；切换当前 Run 不会修改 GT、人工复核或团队默认 Run。没有团队默认 Run 时页面保持“未选择模型 Run”，不会把最新 Run 隐式当默认；隐式团队默认或切换数据集时若当前 Run 对新数据集覆盖为 0，也会回到无 overlay，显式深链接仍允许查看 `NONE` 分区。选择单数据集 Run 时页面自动切换到其命中的 GT 数据集。
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

某个 Model Run 可以只覆盖任一 GT 数据集的输入子集；Run 注册表必须按当前所选数据集 union 显示覆盖数，未覆盖的 Issue 仍保留并显示 `NONE（未预测）`，不能误解为按 SSO 用户裁剪。

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
- 产品媒体 layout（只读，与 `ra_auto_triage/bags` 工作区分离）：
  `/volume/home/workspace/ra_triage_dashboard_data/media_layouts/release0508_1071_20260729`
  - BEV 图：`…/bev/<run_id>/manifest.jsonl`（`ARES_CAPTURE_MANIFEST`）
  - BEV 视频：`…/video`（`ARES_CAPTURE_VIDEO_ROOT`）
  - Camera 默认通道 102：`…/camera/102`（`CAMERA_CACHE_ROOT`）
  - 切换数据集：改 `DASHBOARD_MEDIA_LAYOUT`（layout id 或后续 alias）或覆盖上述三个变量；见 layout 内 `layout.json`
  - 0626 的 materialized capture layout：
    `/volume/home/workspace/ra_triage_dashboard_data/media_layouts/release0626_300_spotcheck_20260807`；根目录保留聚合 `manifest.jsonl` 和 `issues/`，由 baseline `layout_id` 独立索引
  - 0206 的 planning_2k capture layout：
    `/volume/home/workspace/ra_triage_dashboard_data/media_layouts/release0206_1326_planning_2k_20260813`；允许先注册 GT、再按完整 manifest 增量物化媒体
  - 从带聚合软链接的 bags 刷新：使用 `rsync -aL` 物化到新的版本化 layout，禁止 `--delete`；完成 manifest、PNG、MP4、meta 和媒体规格校验后再切换 baseline `layout_id`
- 0508 GT 种子/回滚快照：`/volume/home/workspace/ra_auto_triage/data/trail_label_baseline_20260729.xlsx`（只读）；当前权威 overlay 持久化在 Dashboard 数据库
- 模型 / Trail 逻辑：`/volume/home/workspace/ra_auto_triage`（代码与 bags 采集工作区只读；Batch 新下载只写 dashboard 独立缓存）

模型 endpoint 是服务端固定配置，API key 只存在于上述受限文件和预测 worker 的一次性 stdin，不进入浏览器 HTTP 请求、dashboard 数据库、argv、子进程环境或公共 API。Batch Run 只保存脱敏后的模型、Prompt、输入策略、目录 SHA-256 和配置 SHA-256；上传 JSON / CSV / XLSX 时，metadata、原始行和扩展字段中的 credential / endpoint key 也会在入库前递归脱敏，公共读取再执行一次同样的防护。模型结果原文件只通过同源 Run source endpoint 提供 inline 预览或 attachment 下载，不直接暴露服务器路径；遗留 Run 不会凭空补造归档文件。

AutoTriage 拉取同样是服务端固定来源，默认
`DASHBOARD_AUTOTRIAGE_API_BASE_URL=http://10.190.57.183:8000`。浏览器提供的
records 链接只用于提取数字 Batch ID，后端不会跟随其中的 hostname；客户端禁用
代理和重定向，拉取只产生本地不可变 Run，不调用平台写接口。

当前网关对外契约是内网 HTTP；2026-07-30 实测 HTTPS 入口的证书已过期，无法在保持证书校验的前提下切换。因此 key 的网络传输目前依赖受控内网边界，仍是已知运营风险。证书续期后应把 catalog / chat URL 一并切换到 HTTPS；代码会继续校验固定 hostname、禁用代理和重定向，不能用关闭证书校验替代修复。

Review 截图绑定到单条追加式 annotation：前端粘贴后先本地预览，保存时才上传；后端在受限后台线程中解码并重新编码为 PNG/JPEG/WebP，去除原始元数据。每次最多 4 张、单张 8 MB、总计 24 MB，单图不超过 4000 万像素；HTTP 请求上限为 26 MB，缺少 `Content-Length` 或固定同源请求标记会在 multipart 解析前拒绝，应用级截图配额为 20 GB，并保留至少 256 MB 磁盘空间。API 只返回附件 ID、尺寸、类型和不含服务器路径的读取 URL。备份 SQLite 时必须同时备份 `review_attachments/`，否则历史记录仍在但图片文件无法恢复。

Issue 标签可以不选，前端按三层语义分组：`场景` 包括 `environment`（环境，含施工/变更区域、道闸、园区出入口、掉头、其他）和 `self_intent`（自车意图，含 `intent_straight`、`intent_left_turn`、`intent_right_turn`、`intent_u_turn`）；`触发判定` 保留 `误触发`（`traffic_light`、`queue`、`yielding`、`u_turn`、`park_in`、`park_out`、`scene_false_other`）和 `应该触发`（`obstacle_not_avoided`、`close_distance`、`perception_fp`、`scene_true_other`）；`如何驶离` 仍包括正确触发与无需协助两组。场景和缺失信息使用共享的固定目录，以绝对定位弹出多选，不因选项展开而撑高 Review 面板；当前 Review UI 不提供新建、编辑或删除标签的入口，历史自定义 key 仍可读。缺失信息默认不选中，`is_excluded` 与 Review 版本一起追加保存。

## 用户身份、部署模式与 Kylin SSO

`DASHBOARD_DEPLOYMENT_MODE` 是裸 IP 行为的单一切换开关：

- `development`（默认）：保持历史兼容，裸 IP 可读写。页面可从访问者本机 LCA `/lcainfo` **只提取** `LocalUserAccount` 作为显示名和默认标注人；不会上传、返回或保存 LCA token。该身份明确标为「未验证」，不能用于管理权限或 AutoTriage writer。
- `production`：所有写接口都要求服务端验证通过的 Kylin ticket（推荐），或「可信 ingress marker + 代理注入 SSO 用户」；裸 IP 没有有效会话时自动成为只读预览。

默认主流程复用 Kylin 写入当前域的 `_kylin_ticket` 与 `_kylin_username`。后端用 `app_id=2103794` 调用公司 `check_user_ticket`，并要求返回用户名与 cookie 用户名严格一致；原始 ticket 不写日志，短缓存只使用 ticket 的 SHA-256。校验只发生在 `/api/session` 与写操作，不阻塞图库、Issue 详情或媒体请求。登录跳转由 Kylin ingress 负责，`/auth/logout` 清理本站 cookie 后跳转到公司 SSO logout，并强制用 `jumpto` 回到当前应用的 `/manual/review`，不使用该 `app_id` 的默认首页。

```bash
export DASHBOARD_KYLIN_SSO_ENABLED=true
export DASHBOARD_KYLIN_SSO_APP_ID=2103794
export DASHBOARD_KYLIN_SSO_CHECK_URL=https://mis.diditaxi.com.cn/auth/sso/api/check_user_ticket
export DASHBOARD_KYLIN_SSO_LOGOUT_URL=https://mis.diditaxi.com.cn/auth/ldap/logout
export DASHBOARD_KYLIN_SSO_RETURN_URL=https://auto-triage.intra.xiaojukeji.com/manual/review
export DASHBOARD_KYLIN_SSO_TIMEOUT_SECONDS=1.5
export DASHBOARD_KYLIN_SSO_CACHE_SECONDS=300
export DASHBOARD_DEPLOYMENT_MODE=production
```

不要使用 `Host`、`X-Forwarded-For`、LCA 用户名或未验证的 `_kylin_username` 授权。若改用 Header 模式，直连 8785 的客户端能伪造 Header，因此 Kylin 必须覆盖用户名 Header，并同时注入仅网关与服务端知道的随机 ingress marker。marker 保存在 cloud_server 的 0600 文件中，不能写入代码、环境脚本、数据库或日志。

生产模式下的写请求还必须携带页面自动添加的 `X-RA-Triage-Request` 同源标记。该非简单请求头会让跨站脚本先触发 CORS 预检，并阻止普通跨站表单借用已登录 SSO 会话发起写操作；Kylin 应原样转发该 header，但不能用它替代 SSO 身份或 ingress marker。

AutoTriage 推送默认关闭（`DASHBOARD_AUTOTRIAGE_PUSH_ENABLED=false`），即使打开开关也必须通过后端验证的 SSO 身份；自定义请求头和浏览器提交姓名只用于请求完整性/展示，不能授权生产写入。套好内网域名、清除客户端伪造 header 并由 ingress 注入可信身份后，再显式打开该开关。Batch 预测本身不依赖此开关。

当前数据和 Review 截图都属于看板团队共享内容：任何能访问域名或直接 IP 的用户仍可读取，不能在截图中粘贴超出该协作范围的敏感信息。正式多人使用应通过 HTTPS + SSO ingress 限制域名访问，并在 ingress 配置请求体大小、速率和审计策略；若还要求裸 IP 完全不可读，需要另加网络 ACL，应用的 production flag 只保证裸 IP 不可写。

直接 IP / 本机 LCA 下填写的创建人、复核人或请求人可以作为协作线索保存，但会同时记录为未验证来源；不能据此授权「设为团队默认」等共享操作。结果文件中的实验作者同样只是声明信息。当前后端只有服务端验证通过的 SSO 用户可以设置团队默认 Run。

Header + marker 是 Kylin ticket 校验不可用时的备选方式，配置如下：

```bash
umask 077
openssl rand -hex 32 > /volume/home/workspace/ra_triage_dashboard_data/kylin_ingress_token
chmod 600 /volume/home/workspace/ra_triage_dashboard_data/kylin_ingress_token

export DASHBOARD_DEPLOYMENT_MODE=production
export DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS=true
export DASHBOARD_IDENTITY_HEADER=X-SSO-User
export DASHBOARD_TRUSTED_INGRESS_HEADER=X-RA-Triage-Ingress
export DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE=/volume/home/workspace/ra_triage_dashboard_data/kylin_ingress_token
export DASHBOARD_SSO_WRITE_USERS=alice,bob
export DASHBOARD_TEAM_DEFAULT_MANAGERS=alice,bob
```

Kylin 必须把 SSO 用户写入 `X-SSO-User`，把该文件中的值写入 `X-RA-Triage-Ingress`，且两个 header 都必须覆盖而非追加客户端值；不要把 marker 返回给浏览器。若实际用户名 header 或变量名不同，只改 `DASHBOARD_IDENTITY_HEADER`，代码无需修改。生产模式会在启动时校验 marker 文件为当前服务用户所有、普通文件、权限 0600、内容至少 32 字符；配置不安全时拒绝启动。

`DASHBOARD_SSO_WRITE_USERS` 与 `DASHBOARD_TEAM_DEFAULT_MANAGERS` 只在权限表为空时执行一次初始化。此后 PostgreSQL/SQLite 中的权限表是运行时权威来源：未列出的 SSO 用户与裸 IP 访问均为只读，`writer` 可执行普通 Review、Run 与 Tag 选择操作，`admin` 额外拥有独立的 `/users` 用户管理页。Kylin Portal 的「SSO 白名单」属于网关访问策略，不能直接等同于本应用写白名单。

只有管理员能读取或修改 `/api/access-users`；前端隐藏入口不是权限边界。管理员可添加可写用户、提升管理员或移除写权限，服务端禁止降级或移除最后一个管理员。场景 Tag 固定使用内置目录，Review 中可以选择，但不提供新增、删除或 Tag 管理入口。

验证通过的 Kylin ticket 或可信代理身份会覆盖前端提交的 Run `created_by`、标注 `author` 和任务 `requested_by`，并记录身份来源及 `verified=true`。团队默认 Run 与用户管理都要求持久权限表中的 `admin` 角色，不能把“已登录”直接当成管理员权限。同名记录同时含可信与未验证来源时，筛选项显示为「混合身份」，不会把整组误标为 SSO。

切换步骤：先保持 `development`，通过域名登录后用 `/manual/api/session` 验证 `source=kylin_ticket`、`verified=true`，再把 cloud_server 切到 `production`。如果 Kylin cookie 没有转发到后端，再启用 Header + marker 备选方案。回退只需恢复 `DASHBOARD_DEPLOYMENT_MODE=development` 并重启；这会恢复裸 IP 可写，因此只用于明确的开发/故障排查窗口。

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

Runs 行的 CSV/JSON/XLSX「预览」调用同源 `GET /api/model-runs/{run_id}/source-preview?page=1&page_size=100`，页面内全屏分页查看完整数据（单页最多 200 行），并对单元格做长度限制和敏感字段脱敏；「下载」调用 `GET /api/model-runs/{run_id}/source?download=1`。早期未归档但仍保留预测行的 Run 会生成 `reconstructed-model-run-v1` 复核副本并显式标记，不冒充原始文件。

GT 导入默认不会覆盖已有 GT，只有在 UI 勾选明确覆盖时才会改写。

AutoTriage 快照导入只接受数字 Batch ID 或能提取该 ID 的 records 链接。后端
重新拉取 Batch detail 与 results，只接受三个标准标签，并把平台用户、模型、
Prompt 版本/Hash 和覆盖情况保存为来源元数据；平台返回的 GT 只保留在脱敏原始
行中，不会更新 Workbench baseline。

Trail 只消费 `ra_stuck_auto_result` 和 `ra_stuck_auto_result_info`。可通过 `DASHBOARD_TRAIL_VIEW_ID` 指向包含这两个字段的 view：

1. 点击「检查字段可见性」，只读检查字段、完整性和可用覆盖数，不创建 Run。
2. 检查通过后点击「创建只读 Trail 快照」，创建或复用本地不可变 Run。

只有默认数据集的全部 Issue 分片完整返回时才允许创建快照；任一分片失败、返回不完整、结果字段不可见或没有三分类标准标签，都不会创建 Run。查询完整不代表预测必须全量：模型字段可只有部分 Issue 有有效预测，页面会明确显示实际覆盖数；`nan`、`<NA>` 或未知字符串不会被误计为可用标签。Trail 检查和快照均不写回 Trail、不修改 GT 或人工复核，也不改变团队默认 Run。如果 view 没有展示字段，页面会明确提示并保留 CSV/JSON/XLSX 上传入口。

「Trail 属性更新」是按 Model Run 隔离的“预览 → 明确提交”工作流：它只聚合当前 Run 最新 Review 中勾选“应该排除”的 Issue，并按 Issue ID 稳定排序。目标字段固定为 `ra_stuck_auto_result`（三分类模型 label）和 `ra_stuck_auto_result_info`（JSON 结果详情）；详情字段采用 `deep_merge`，保留已有内容，并追加 `model_result` 与 `ra_triage_dashboard` 审计命名空间（Run、Review、复核人、时间和排除标记）。每次预览生成 SHA-256 摘要，提交时服务端会重新读取目标字段并校验摘要，避免旧页面覆盖新数据。

默认 `DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false`，因此即使页面有提交按钮，字段未暴露或写入开关未开启时也只能预览/下载，绝不会回退写入旧的 `ra_result`/`ra_info`。只有目标 view 同时返回两个精确字段、所有 label 符合三分类、请求来自已验证 SSO 写入用户，并且提交摘要未过期时，按钮才会解锁；写入通过 `ra_auto_triage/utils/trail_api.py` 的受控 `multi_update` 客户端，按小块执行且不记录 token 或完整 payload。

使用方式：

1. 在左侧打开「Trail 属性更新」，选择一个 Model Run；数据集范围自动使用顶栏当前选择。
2. 点击「生成预览」，确认案例、Review、字段能力和目标 Patch。
3. 字段检查通过且具备写入权限时，点击「提交到 Trail」；否则下载/复制 JSON 交给后续受控流程。

接口：`GET /api/trail-attribute-update/preview?model_run_id=<run-id>&baselines=0508` 和 `POST /api/trail-attribute-update/commit`（body 必须包含 `confirm=true`、`model_run_id`、`payload_sha256`）。预览接口只返回所选 Run 的 Review，不会把其他 Run 的标注混入；无 Run、未知 Run 或空范围会返回明确错误/空草稿。提交接口会重新生成预览并拒绝过期摘要。

相关配置：

- `DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED=false`：Trail 属性写入总开关，生产默认关闭。
- `DASHBOARD_TRAIL_ATTRIBUTE_WRITE_CHUNK_SIZE=10`：单次 `multi_update` 的最大条数，服务端上限 50。
- `DASHBOARD_TRAIL_ATTRIBUTE_RESULT_FIELD=ra_stuck_auto_result`、`DASHBOARD_TRAIL_ATTRIBUTE_INFO_FIELD=ra_stuck_auto_result_info`：字段名只允许安全标识符；除非 Trail schema 已明确迁移，不要改成旧字段。

权威 GT 同步固定读取 `DASHBOARD_GT_SYNC_VIEW_ID=1000` 的 `ra_merge_result`，默认覆盖 baseline registry 中的全部数据集，不接受浏览器提交 host、view 或 scope；浏览器只能从服务端已配置的数据集里选择手动刷新范围。相关配置：

- `DASHBOARD_GT_SYNC_ENABLED=true`：启用启动后的后台轮询。
- `DASHBOARD_GT_SYNC_BASELINE_IDS=*`：同步全部已注册数据集；也可用逗号分隔的短 ID 限定范围。旧的单值 `DASHBOARD_GT_SYNC_BASELINE_ID` 仅作兼容回退。
- `DASHBOARD_GT_SYNC_INTERVAL_SECONDS=1800`：每轮完成后的轮询间隔，最小 60 秒。
- `DASHBOARD_GT_SYNC_STARTUP_DELAY_SECONDS=3`：服务启动后首次同步延迟。
- `DASHBOARD_GT_SYNC_CHUNK_SIZE=160`：Trail 分片大小。

`GET /api/gt-sync-status` 返回各数据集持久化同步状态，可用 `baselines=0508,0626` 选择子集；`POST /api/gt-sync` 的 `baselines` 只能选择服务端允许的数据集，先原子占用全局同步槽并返回 `202 accepted/running`，随后在响应后台执行完整检查与安全应用。重复点击不会并发访问 Trail，而会返回已有任务正在运行。顶部 GT 徽标展示最近一次完整校验时间，因此手动校验即使更新 0 条也会更新时间；hover/focus 徽标可查看本次数据集、校验/变更数量、触发人、Trail GT 源更新时间和最近实际写入时间。`gt_sync_state` 保存来源/检查/应用时间和统计，`gt_sync_labels` 按 baseline scope 保存完整权威 overlay；baseline 启动加载会先合并各自 overlay，旧 Excel 不会把已同步 GT 回滚。同步只更新 Dashboard 自己的 `issues.gt_label`，绝不写 Trail。

Issue 详情的外部 RA 链接可通过以下只读配置控制：

- `DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED=true`：是否在详情渲染后后台查询当前 Issue 的 Trail 元数据；不会阻塞 Issue 详情或模型 Run 同步，关闭后仅隐藏可选 RA 入口。
- `DASHBOARD_TRAIL_DETAIL_METADATA_CACHE_SECONDS=300`：单 Issue 元数据缓存时长。
- `DASHBOARD_RA_RECORDING_BASE_URL`：RA 录屏任务 URL 前缀，默认是 `https://s3-gzpu-inter.didistatic.com/voyager-fe/operation-platform/ra/dashboard/index.html#/tasks`；服务端在末尾拼接 URL 编码后的 `ra_id` 和 `?returnUrl=`。

## cloud_server 启动

### 并发与有界 I/O 契约

Dashboard 的 HTTP 路由使用 FastAPI 异步处理，但现有数据库适配器、SSO 解析、
Excel/CSV 解析及 Ares 文件索引均为同步实现。路由层必须通过 `asyncio.to_thread`
执行这些同步操作，不得在事件循环中直接调用数据库、文件系统或隐藏同步 I/O 的身份/
目录辅助函数。`tests/test_architecture_hardening.py` 对这些边界做静态回归检查；后续新增
路由时应同步扩展该约束，而不是仅依赖人工 Code Review。

模块边界同样采用显式契约：`app/main.py` 和 `app/routers/` 禁止 `import *`，
`app/runtime.py` 只负责进程级单例与启动状态，轻量请求限制集中在
`app/contracts.py`，JSON/CSV/XLSX 解析集中在无运行时单例依赖的
`app/import_parsing.py`。这样导入一个解析器不会隐式初始化数据库、媒体索引或模型客户端，
路由缺失依赖也会在启动/测试阶段暴露，而不是等到特定请求到达后才出现 `NameError`。

模型结果上传按块读取，并在超过 64 MiB 时只额外读取一个哨兵字节后立即拒绝，避免把
无限请求体一次性载入内存。XLSX/XLSM 在交给 openpyxl 前还会检查 ZIP 文件项总数、
解压后总大小和异常压缩比，避免小体积压缩包触发无界解压或内存占用。SSO 入口诊断采用固定上限的观测缓存，避免不同来源持续写入
导致进程内存无界增长。`/health` 只返回启动或最近一次显式刷新得到的 Ares 索引快照，
不扫描网络存储；需要主动刷新和诊断介质状态时使用 `/api/status`。

灰度发布必须先在 8786 使用独立代码目录和独立 SQLite 数据目录验证，不能连接正式
PostgreSQL，因为应用启动及迁移流程可能产生写入。8786 通过完整测试、健康检查、页面与
媒体抽样后，才允许保持正式数据目录和数据库配置不变切换 8785。

```bash
cd /volume/home/workspace/ra_tools/ra_triage_dashboard
bash scripts/bootstrap_cloud_server_env.sh
bash scripts/run_cloud_server.sh
```

启动脚本默认使用 `/volume/home/workspace/ra_triage_dashboard_venv`，并监听 `0.0.0.0:8785`；可通过 `DASHBOARD_VENV_DIR`、`DASHBOARD_HOST`、`DASHBOARD_PORT` 和 `DASHBOARD_DATA_DIR` 覆盖，便于隔离 staging。该 venv 继承 cloud_server 已验证的 RA / Trail 依赖栈，并在环境内覆盖截图入口所需的安全版本；Batch worker 会先加载 Voyager 环境，再用同一 Python 调用 `ra_auto_triage`。当前试运行可从内网直接访问 `http://172.16.145.60:8785`。直接 IP 是明文 HTTP 且无可信 SSO，只适合受控内网试用；正式多人使用应迁到 HTTPS + SSO 认证代理。

### 子路径 / Kylin 反代

默认 `DASHBOARD_BASE_PATH` 为空，根路径和直连 IP 行为保持不变。域名模式使用：

```bash
export DASHBOARD_BASE_PATH=/manual
bash scripts/run_cloud_server.sh
```

当前中经云线下 Kylin（`10.78.128.20`）必须按以下契约转发：

```text
域名: auto-triage.intra.xiaojukeji.com
浏览器路径: /manual/*
上游: 172.16.145.60:8785/*
规则: 必须 strip /manual 前缀后再转发
健康检查: 网关侧 GET /manual/health；上游侧 GET /health
```

后端路由仍是 `/`、`/static`、`/api`、`/review` 等根路径；浏览器位于 `/manual` 时，Shell、前端导航/API 请求和返回的同源资源 URL 使用 `/manual/...`。同一个配置了 `/manual` 的进程若从裸 IP 根路径访问，前端会自动回退到无前缀路径，因此直连预览不受影响。不要把域名根路径的 `/static` 或 `/api` 指向本看板，否则会占用 AutoTriage 主站路径。正式独立域名仍推荐挂根路径并保持 `DASHBOARD_BASE_PATH` 为空。

配置只允许空值或 `/manual`、`/tools/triage` 这类路径段；`/` 等价于空值，尾斜杠会去除，全 URL、空格、`..` 和重复斜杠会拒绝启动。前端只在浏览器当前路径位于已配置前缀下时启用该前缀；否则按根路径运行。

页面路由可直接访问：

- `http://172.16.145.60:8785/review`
- `http://172.16.145.60:8785/review-analysis`
- `http://172.16.145.60:8785/runs`
- `http://172.16.145.60:8785/batch-prediction`
- `http://172.16.145.60:8785/system-status`
- `http://172.16.145.60:8785/runs?import=model`

Review 首页筛选参数可写入 URL：

```text
/review
  ?run=<model_run_id>
  &comparison=all|mismatch|match|none
  &failure=1                 # 旧链接，等价于 comparison=mismatch
  &q=<search>
  &gt=<三分类标签>
  &model_label=<三分类标签>
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
  &model_label=<三分类标签>
  &evidence=<stable_missing_evidence_key>
  &scene_tag=<stable_scene_tag_key>
  &trigger_tag=<stable_trigger_tag_key>
  &egress_tag=<stable_egress_tag_key>
  &q=<search>
  &page=<positive_integer>
```

`run=none` 明确表示查看全部最新 Review 且不叠加模型输出，此时 `comparison` 只能为
`all`。`NONE` 表示所选 Run 对该 baseline Issue 没有有效三分类预测。旧
`failure=1` 链接仍会兼容解析为 `comparison=mismatch`。旧版 `annotation`、`tag` 与
`theme` 参数只作为兼容输入解析；当前页面只发出 `model_label`、三个结构化 Tag
筛选参数和稳定缺失信息 key。原因分析 API 的生产聚合不再计算旧的自由文本关键词主题，
避免把并不存在的主题误呈现为业务字段。

原因聚类数据接口为 `GET /api/review-reason-analysis`；同一组筛选参数可传给
`GET /api/review-reason-analysis/export?format=csv|xlsx|trail_xlsx` 导出全部命中行
（不受页面分页限制）。页面将其命名为“导出 GT 更新表”；兼容格式名 `trail_xlsx` 只输出
`issue_id`、`期望输出` 两列，且仅保留按有效期望输出与 GT 不同规则判定为
`needs_gt_review` 的行。有效期望输出优先读取已保存值，历史空值则从结构化 Tags 唯一推断；
缺失或冲突时不导出（不信任历史手选状态），可直接导入
`/ra/model_triage/batch_trail_update` 的“填写期望输出”模式。导出会防护电子表格
公式注入，CSV 带 UTF-8 BOM 便于直接用 Excel 打开。

旧 `/import?kind=issues|model` 仍可访问，但统一跳转到仅支持模型结果的 Runs 导入区；页面不会提供 Issue / GT 上传控件。后端 `/api/import/issues` 仍为兼容旧客户端保留，不能用于修改 0508 baseline 的页面流程。

如需收回直接暴露，可把启动参数改为 `--host 127.0.0.1`，再使用 SSH 隧道：

```bash
ssh -L 8785:127.0.0.1:8785 cloud_server
```

再打开 `http://127.0.0.1:8785`。在没有服务托管器的 cloud_server 上，可先使用受控 tmux 会话。

## SQLite 到 PostgreSQL

运行时同时支持 SQLite（本地/回滚）与 PostgreSQL（正式多人环境）。PostgreSQL 使用 `psycopg_pool` 连接池，默认最大 10 个连接；`/health` 的 `storage` 会明确返回 `sqlite-mvp` 或 `postgresql`。数据库连接优先从 `DASHBOARD_DATABASE_URL` 读取，也可通过服务用户持有的 `0600` 普通文件 `DASHBOARD_DATABASE_URL_FILE` 读取，避免把凭证放进 tmux 命令、源码或日志。

`migrations/postgres/001_initial.sql` 提供完整 schema，应用启动时会按文件名顺序记录并执行尚未应用的 migration：

1. `002_review_baseline_fields.sql`：补齐 baseline 与 review 字段。
2. `003_identity_attribution.sql`：为 annotations、model_runs 和 inference_jobs 增加身份来源与可信状态，并为复核人、Run 创建人和任务请求人建立索引。
3. `004_review_attachments.sql`：增加 annotation 级截图元数据；二进制文件仍保存在独立附件目录。
4. `005_batch_prediction_jobs.sql`：增加 Batch Prediction Job / Item、不可变 Model Run 关联和 AutoTriage 推送审计字段。
5. `006_batch_model_selection.sql`：为既有 Batch Job 增加 requested / resolved 模型 ID、模型来源和目录指纹。
6. `007_batch_prompt_input.sql`：增加模型验证层级、完整 Prompt 快照/Hash、输入 Profile 和输入配置 JSON 及筛选索引。
7. `008_change_revision.sql`：增加跨页面共享 revision 及事务内更新 trigger，为轻量多人同步提供依据。
8. `009_runtime_adapter.sql`：补齐 Provider、持久 FIFO 队列序号及团队默认 Run 的并发唯一约束。
9. `010_review_tag_catalog.sql`：固化 Review 场景 Tags 目录。
10. `011_access_users.sql`：增加运行时用户权限表。
11. `012_review_exclusion.sql`：增加 Issue 级排除标记。
12. `013_missing_evidence_catalog.sql`：增加共享缺失信息目录。
13. `014_missing_evidence_management.sql`：为共享缺失信息增加可软删除的 active 标记，保留历史标签可读性。
14. `015_review_tag_management.sql`：为共享场景标签增加说明、分组和可软删除字段。
15. `016_issue_work_assignments.sql`：增加 Issue 均分后的持久化分配记录。
16. `017_review_run_binding.sql`：为 Review annotation 增加 `model_run_id` 及 Issue/Run 复合索引；旧记录保持空 Run 标识，保存接口通过版本 ID 做乐观并发校验。
17. `018_gt_sync.sql`：增加权威 GT 完整快照 overlay 与同步状态；不为状态检查增加共享 revision，只有实际 GT 变化才触发重型页面刷新。

`003_identity_attribution.sql` 对旧行使用 `legacy` / `verified=false`，不会把历史自由填写姓名升级成可信 SSO。所有人工标注、模型结果、任务记录与附件元数据都保留历史行；附件二进制仍留在同一受限 `review_attachments/` 目录，PostgreSQL 保存其元数据。

cloud_server 的一次性切换流程：

1. 运行 `scripts/bootstrap_cloud_server_env.sh` 安装包含 psycopg 的专用运行环境。
2. 运行 `scripts/bootstrap_cloud_postgres.sh` 安装/启动本机 PostgreSQL 14，创建仅 Unix socket peer 访问的专用数据库，并写入尚未生效的 `0600` `postgres_url.pending`。
3. 停止 Dashboard 写入后运行 `scripts/migrate_sqlite_to_postgres.py --source ... --backup ... --target-url-file ...`。工具会先生成只读 SQLite 备份，拒绝非空 PostgreSQL 目标，在单事务中复制数据并逐表核对行数与 SHA-256。
4. 校验通过后把 `postgres_url.pending` 原子改名为 `postgres_url`。停止 Dashboard 写入，运行 `scripts/migrate_cloud_postgres_data.sh`，把 PostgreSQL 物理数据从容器 overlay 迁移到 `/volume/postgresql/14/main`；脚本会先创建可恢复的 custom-format 逻辑备份、离线复制、逐表核对行数，并在失败时自动恢复原配置，旧物理目录不会删除。
5. 运行 `scripts/install_cloud_postgres_backup_cron.sh` 安装每日 02:15 的备份任务。备份保存在 `/volume/home/workspace/ra_triage_dashboard_data/postgres_backups/`，每份都经过 `pg_restore --list` 校验并附带 SHA-256，默认保留最近 14 份；安装脚本会写入不含路径或凭证的计划状态标记供系统状态页读取。用 `scripts/verify_cloud_postgres_backup.sh` 将最新备份恢复进一次性数据库并逐表对比实时库行数。容器重建后重新运行 bootstrap 和 cron 安装脚本；bootstrap 会自动重新挂接已有的持久数据目录。
6. 重启 Dashboard；`run_cloud_server.sh` 会拒绝使用 overlay 上的 PostgreSQL 数据。确认 `/health`、实际 `SHOW data_directory`、1071 baseline、Runs、Review、附件、Batch 历史及最新备份可恢复后再结束维护窗口。

数据库引擎切换回滚只需移走/改名 URL 文件并重启服务，原 SQLite 与附件目录未被迁移工具修改。物理目录迁移失败会自动回滚；成功后旧目录只作为切换时刻的短期回滚副本，之后新增写入应从 PostgreSQL 逻辑备份恢复。正式启用可信 SSO 后，仍需为团队默认变更、推理与未来 Trail 写入补充 RBAC。
