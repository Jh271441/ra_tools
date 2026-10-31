# 局部 BEV 视频旁路

## Daily 三种媒体接入（2026-10-31）

`/manual/daily-cron` 保持“推理回刷 / 平台与媒体”两条链。媒体内增加第三项局部 BEV，与 Camera、BEV 共用所选版本或旧日期批次的目标分母，分别验收和发布。顶部主数及“三媒体验证”节点使用同批发布回执交集，既有 `verified` 双媒体字段保留，新增 `triple_verified`，不改变其他调用方或 Camera 的原发布后1小时清理策略。

只读适配器 `CloseupCohort` 读取现有任务的小型 SQLite 队列与播放器使用的根目录受限 receipt。按 Issue / trip / 权威锚点 / scope / 冻结 recipe 匹配，复用既有完整时序、解码验收，不重扫 MP4、不读 Bag、不投任务。Camera、BEV 当前显示的是原双媒体发布回执已确认的覆盖，不把执行中计数作为独立 verified。局部视频可以独立多于双媒体，而三项交集仍可能更少。

`queued` 只显示为待队列处理；历史 `running` 没有运行证据时显示待核实/验收。已 verified 的 job 缺少当前 scope 的发布回执时计入身份/范围待核实，不算录制失败，不自动重录或扩 scope。无目录或不可读回执显示未知；缺少 trip/anchor 不从旧 job 借值。完整历史回溯保留在折叠区，不缩小其冻结范围。

继续复用现有小时发现及离线执行队列，不重启旧 Capture。本地预览服务只接收 GET，真实只读快照有冻结时间标记，其他应用 bootstrap 接口为隔离空响应。用户看过实际页面后已授权部署，并要求2026-10-31 19:00 CST开始自动验证；实际激活必须有下述服务器control和activation回执。

### 局部 BEV 与原 BEV 相同的恢复流程（2026-10-31 修正）

实时图、旧日期图和帮助图统一显示 `局部 BEV · Orion → 失败子集 Orion 重试1次 → 仍失败或验收不通过 → 本地最多2次 → 验收发布`，拓扑生成函数与原 BEV 共用。Orion 初次或重试成功均进入验收；各项验收后独立发布。local 的2个并发名额须与原 BEV 全局共用，不新增第二组名额。本地恢复保持局部配方，不调用普通 BEV 的默认布局。源消息损坏、固定窗口源缺口保留证据待处理，不能以重复录制代替修复。

页面只读展示历史及新登记的Orion重试和本地执行回执。本地执行器调用Ares Animation离线链，保持原资源门禁、规划源读取共享锁及400帧/时序/精确地图/完整解码发布门禁；发布producer为 `ares_animation_local`。登记、启动、原生完成和实际发布分别统计。

`config/bev_closeup/layout.json` 保存实际录制使用的原始冻结布局，2666627字节，SHA256 `613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575`。同目录 `recovery-policy.json` 与原BEV策略逐字节一致：Orion retry1 / local2 / global workers2 / deadline2400s；`manifest.json` 记录来源、SHA和视频参数，激活由服务器control决定。布局为30m视距、自车前4m，1920×1080、10FPS、400帧、t0=20秒。

`CloseupRetries` 校验任务登记的配方/layout、每次源清单 SHA 和终态分项合计，再将第二次 Orion 尝试按同 Issue/trip/锚点/scope 投影到本批目标。混合成功/失败用已存原生失败 Task 的 Job/Issue/锚点逐条核对；历史第三次额外尝试只观察，不重置自动预算。缺失证据保持未知，不根据旧 queue.running 推断正在运行。

`CloseupFallback` 有界读取恢复登记、源清单及终态状态，校验冻结 recipe/layout 与源清单 SHA，按同 Issue/trip/anchor/scope 求交。分别展示登记子集、真正有执行证据的案例、本地恢复发布、源异常/缺口及证据时间。登记12条不等于已执行12条；旧 PID 和非终态字符串不证明当前运行；本地“成功”必须来自播放器认可的当前 scope 发布回执。丢失、越界、超限或身份不符的恢复证据显示不可用，不泄露私有路径和 SDK 日志。

### 服务器执行与幂等恢复

`scripts/bev_closeup/orion_controller.py` 沿用任务自己的worker.lock、SQLite、小时增量发现和4路有界下载。原生终态且所有completed已验收或确定性失败/下载3次耗尽后，批次标记terminal并保留unresolved；未到退避期限的下载及128条批次外尚未处理的成功项仍保持active。旧失败不再阻挡下一批初次提交。未来Daily初次及单次重试的Orion并发上限1000，历史3000任务登记不改。

`offline_daily.py` 按Issue/trip/anchor计算历史预算。已发布、实证源损坏/固定源缺口、历史第三次尝试均不重投；提交网络请求前持久化intent，未知提交结果必须只读对账。初次和重试都走官方run-orion预检。验收失败可进入同一有界恢复流程，不能发布原生FAILED结果。

`media_wrapper.py` 在原个人媒体controller的main及终身controller.lock内调用局部local准入。claim放进原daily/versions全局扫描命名空间，两种BEV共用2名额。`local_attempt.py` 使用原策略2400秒、8GiB进程组PSS、40GiB自有临时文件上限、10GiB磁盘余量；Planning源worker仍512MiB文件/4GiB地址/120秒/单worker/共享锁。rendered只表示等待发布；只有局部主控制器持worker.lock通过原pipeline完整门禁后才记verified。

`activate_daily.py` 从精确发布Git SHA安装任务独立release，校验冻结pipeline/source worker/template/layout，离线启动空白Chromium检查依赖，保留原个人媒体launch环境和guard。核对两个控制器的PID/start_ticks/cwd/命令/锁，原Orion在STOP批次边界退出、原媒体仅空闲无子进程时切换；失败保留回执并恢复自身改动。生产Dashboard另走官方deploy_cloud流程。

任务根 `daily-sidecar/control.json` 的enabled、not_before、代码及布局SHA共同门控：2026-10-31 19:00 CST之前只继续本地小时发现，新增局部提交/下载/本地执行均等待；原媒体流程照常。`ensure_daily.py` 核验独立guard锁及真实worker锁/进程后恢复自己拥有的控制器，原每5分钟增量cron不变。`daily-sidecar/activation.json`、controller-launch、实际job/claim/验收及发布回执才是激活/执行证据。

Closeup BEV uses the original BEV recovery topology: one Orion retry for the failed subset, then at most two local attempts for persistent failures or invalid output. Local work shares the original two global slots inside the original controller's lifetime lock. The frozen layout and matching recovery policy are saved under `config/bev_closeup/`. Server control gates execution until the authorized start time; registration and native completion never substitute for verified publication.

Daily media includes Camera, BEV and closeup BEV within the existing media lane. Coverage is scoped to the same targets, with a separately verified receipt intersection. Missing identity/scope evidence stays unconfirmed. Tracks publish independently; the historical backfill and existing cleanup policy remain intact. Deployment and activation need their own exact-SHA receipts; video acceptance follows actual execution.

下方均为各次实际运行的历史记录，不能据其旧 PID 或计数判断当前状态。

## 当前运行：Orion Ares Animation（2026-10-30 10:13 CST）

用户明确纠正后，全量生产已切换为个人 Orion CPU mapper。旧在线 Capture 在批次边界退出，98条已验证视频、原始证据和冻结账本保留，根目录 STOP 禁止旧路径重启。跨0821/1009/1016/1023四版本canary Job 48919603全部通过400帧、0ms时间误差、精确trip地图、完整解码及真实首中尾画面验收。

剩余4557条已提交 Job **48920861**，并发上限3000，prod_gen4 / high / jasperchen。10:11实查2758 running、1799 unassigned；这是历史观察，后续必须读取真实Job状态。总目标4656（含小时增量），99条verified含旧98和新1023 canary。回溯和最终来源审计尚未完成。

独立控制器为任务根 `orion/controller.py`，同一worker.lock互斥、4路下载验证与原子发布。启动登记 `orion/controller-launch.json`，任务账本 `orion/jobs.json`，批次 `orion/runs/20261030T021040Z`。控制器PID16213/start_ticks3627924366仅为本次历史证据，不可作为日后存活结论。

Current production uses personal Orion Ares Animation workers (limit 3000); the legacy online Capture is stopped. All four canaries passed. Full Job 48920861 has 4557 tasks; collection and final coverage audit remain in progress.

## 范围和发布契约

2026-10-29 的冻结账本保留 5473 个成员：已发布 4461（0821 主集1242+补标250，1009=1480，1016=1489），等待197、业务排除815。等待和排除单独留账，只有已发布且权威锚点齐备的成员进入视频队列。历史成员不缩为复核子集。每小时读取平台的本地版本登记，追加1009及更新版本的已发布成员；不查询或写入 Trail。

独立工作目录：`/volume/home/workspace/ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029`。使用已发布 Release `ares_animation/releases/bd9f187.json`、运行时 `ares-animation-2136c0c27e7e333e`，官方 `run-orion --submit` 先预检再提交，输入SHA/Job/Task回执幂等登记。Orion mapper上限3000；单个本地下载控制器持有 `worker.lock`，内存低于85%且余量至少6GiB才继续下载/校验。旧Capture单worker约束只属于下方历史路径。

冻结 recipe `ego30-forward4-1080p-10fps-v1`：distance30、目标自车前4m、自车完整可见，1920×1080、10FPS、40秒400帧，t0为20秒。源数据窗口左右各额外1秒，输出帧时间不变。固定个人布局的原始和渲染 SHA 分别为 `52272f85a2475d4637891947469fe8034b2d0272fccf22e96cd144c9169fea64`、`613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575`；只在当前页面覆盖视角，不保存共享布局。

离线Animation使用官方消息/渲染/截图同步、精确trip地图（禁止latest或邻近fallback）。保留原生report，逐帧校验400条时间/索引/hash、误差≤1ms，校验布局/Release/runtime指纹和离线网络门禁。发布前核对ffprobe帧数/编码/时长、ffmpeg完整解码和framemd5，生成首中尾QA帧与独立t0海报。不得伪造在线Capture的暂停/加载/编辑观察字段；原成功Capture保留原生meta并明确来源。

优先使用既有媒体manifest的trip/anchor。没有既有媒体时，权威版本登记的event时间显式标记 `version_registry_event`；锚点冲突不录制，缺失不伪造、不用旧帧补洞。

## 播放与状态

局部视频发布到实际 `DASHBOARD_MEDIA_LAYOUT_ROOT/bev_closeup`，目前为 `/volume/home/workspace/ra_triage_dashboard_data/media_layouts/bev_closeup`。逐Issue小型receipt索引与内容对象独立于原媒体，无全目录扫描。API只暴露根目录约束下的 `bev-closeup-video`、`bev-closeup-poster`。receipt必须为指定recipe、scope和完整验证成功。与原视频trip/anchor/40秒/t0一致时才附加独立源；没有原视频时可单独展示局部源。

播放器沿用共享视频源下拉、当前位置/倍速、重试、全屏和清理生命周期。局部源保留自己的t0海报；语言切换只改变展示。`/daily-cron` 独立显示局部视频状态、分版本验证/目标/失败/锚点待解决，过期心跳明确显示，不将局部失败算进原双视频或主推理。

判错复核、问题标注及媒体弹窗支持 `Shift+V` 直接切换到当前 Issue 的局部 BEV 视频，沿用共享视频源切换并保留播放位置和倍速。输入、输入法组合、打开的选择器和其他弹窗内不触发；没有局部源时显示提示。中英文帮助和快捷键指南同步展示该入口。

Press `Shift+V` to select the current Issue's closeup BEV video in Review, Issue Labeling or the media dialog. It uses the shared source switch and retains playback position and speed. Typing, IME composition, open selectors and other dialogs do not trigger the shortcut; an unavailable closeup source shows a localized message.

## 观察与恢复

从 Mac/T3650 使用 host-ops 的 `hop.sh cloud_server`。每次核对实际控制器启动时间/命令/cwd/start_ticks及worker.lock、`progress.json`、`queue.sqlite3`、`orion/jobs.json`、原生Orion Job/Task、当前run的status/submit/download/verification与原子receipt。旧PID或一次网络观察超时不足以证明退出；不得重复提交。

正常推进保持安静。独立10分钟heartbeat排查失败分类和下载/校验/发布异常；输入SHA和launch回执绑定已提交Job，提交结果不明时只读核对，禁止盲重放。下载瞬态失败最多3次退避，确定性验证失败保留证据待修复；任务失败不得盲重置。恢复控制器前先核对真实进程、原任务与同一worker锁。旧 `recovery.py --apply` 只适用于历史Capture claim，不能重置Orion running。Orion离线路径不依赖Ares SSO，不能回退在线Capture。

本任务不改变生产GT、标注、模型Run、Trail、凭据、原媒体清理策略。规划约束dump及其 `1016-0821` 监测继续独立运行。回溯完成须逐成员复核receipt、文件SHA、完整时间/解码、分版本覆盖/缺口/失败及来源原因，完成审计后增量旁路仍继续等待新增成员。

### 2026-10-29 浏览器停滞恢复

首次批次的1009 `cn36854187` 已完整通过校验；0821 `cn35635843` 在377帧后失去页面renderer，Python/浏览器根仍存活，10分钟无日志或帧写入。保留 `manual-stall-evidence.json` 和原始377帧后，只清理精确start_ticks的Capture子树。coordinator已增加600秒无实际日志/帧/meta写入保护：自身心跳不计为录制活动，触发后保留证据并关闭所属子树、验证完成产物、退避重试。未被批次实际访问的后续Issue不扣重试次数。恢复探针可用 `--once --batch-size 1`，正常全量仍为3条一批和单worker；逐帧120秒门槛、布局、时序与解码契约不变。

### 上线与启动验收（2026-10-29 19:51 CST）

播放器及独立进度页面已发布 `26e3a65a875604bc039d535f9ab24e34af16f51a` / cache714，回执为 `releases/20261029T112402Z-26e3a65a8756/result.json`。统一门禁1132通过、7跳过，隔离灰度、精确SHA、PostgreSQL持久化、schema58和原身份/写入策略核验通过。本地真实共享模块的Chromium验收覆盖320/390/1440、中英文、深浅主题的12组合，三源切换保位/倍速、独立海报、语言刷新、共享下拉及Escape/外部关闭、边界、全屏切源、失败重试与进度状态；这是桌面浏览器视口测试，不是真机或生产登录后的视觉验收。

独立collector的恢复与范围映射修复来自 `a26d10e14daf8e3896d25e6acb7dd0fa1781feab`，只更新任务自己的code目录，不额外重启生产UI。历史1009三个已登记数据集双次扫描共205成员，按同Issue/同版本扩展媒体scope，原trip/anchor、视频SHA和冻结目标成员不变。批次结束后持锁激活的记录在 `updates/scope-alias-v1/activation.json`。三版本5个真实case的局部源与视频Range206已核验，1009历史入口可展示三源。

该时点全量仍在录制：6/4461已验证（3条旧验收样例复用、3条新增），并非采集完成。新进程35527启动于19:49:50、Capture35563，cwd分别为任务根/runtime；PID仅为历史证据，每次须重新核验。新批次包括原停滞case，源网络失败保留退避、不归为原始数据缺失。每10分钟heartbeat `bev` 已启用，每小时增量登记继续；原规划dump的 `1016-0821` heartbeat独立保留。
