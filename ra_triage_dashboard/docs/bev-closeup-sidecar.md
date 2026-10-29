# 局部 BEV 视频旁路

## 范围和发布契约

2026-10-29 的冻结账本保留 5473 个成员：已发布 4461（0821 主集1242+补标250，1009=1480，1016=1489），等待197、业务排除815。等待和排除单独留账，只有已发布且权威锚点齐备的成员进入视频队列。历史成员不缩为复核子集。每小时读取平台的本地版本登记，追加1009及更新版本的已发布成员；不查询或写入 Trail。

独立工作目录：`/volume/home/workspace/ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029`。固定 Capture 运行时提交为 `3b822ffb31cc9b51562ef8ea6d1280b49ee2d772`；`runtime-provenance.json` 记录来源。启动脚本先加载仓库支持的 Voyager 环境；一次仅一个 coordinator、一个 Capture worker，批次3条复用浏览器，持有 `worker.lock`。cgroup 内存使用率须低于85%且余量至少6GiB、磁盘至少10GiB才开新批次。

冻结 recipe `ego30-forward4-1080p-10fps-v1`：distance30、目标自车前4m、自车完整可见，1920×1080、10FPS、40秒400帧，t0为20秒。源数据窗口左右各额外1秒，输出帧时间不变。固定个人布局的原始和渲染 SHA 分别为 `52272f85a2475d4637891947469fe8034b2d0272fccf22e96cd144c9169fea64`、`613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575`；只在当前页面覆盖视角，不保存共享布局。

每帧先暂停、提交时间、失焦，再验证实际时间误差≤1ms且非编辑状态、场景可用、时间轴加载消失。发布前核对全部400条时间观察，ffprobe帧数/编码/时长、ffmpeg完整解码和framemd5，生成首中尾QA帧和独立t0海报。三版本各10条pilot全部通过机器校验且已有真实三版本画面验收记录后，自动继续其余全量。

优先使用既有媒体manifest的trip/anchor。没有既有媒体时，权威版本登记的event时间显式标记 `version_registry_event`；锚点冲突不录制，缺失不伪造、不用旧帧补洞。

## 播放与状态

局部视频发布到实际 `DASHBOARD_MEDIA_LAYOUT_ROOT/bev_closeup`，目前为 `/volume/home/workspace/ra_triage_dashboard_data/media_layouts/bev_closeup`。逐Issue小型receipt索引与内容对象独立于原媒体，无全目录扫描。API只暴露根目录约束下的 `bev-closeup-video`、`bev-closeup-poster`。receipt必须为指定recipe、scope和完整验证成功。与原视频trip/anchor/40秒/t0一致时才附加独立源；没有原视频时可单独展示局部源。

播放器沿用共享视频源下拉、当前位置/倍速、重试、全屏和清理生命周期。局部源保留自己的t0海报；语言切换只改变展示。`/daily-cron` 独立显示局部视频状态、分版本验证/目标/失败/锚点待解决，过期心跳明确显示，不将局部失败算进原双视频或主推理。

## 观察与恢复

从 Mac/T3650 使用 host-ops 的 `hop.sh cloud_server`。每次同时检查实际进程启动时间/命令/cwd/start_ticks、`progress.json`、`queue.sqlite3`、当前批次 `process.json`/`capture.log`/`meta.json`及验证回执。旧PID、旧failure或一次观察网络超时不足以证明退出。正常推进保持安静；独立10分钟heartbeat排查实质异常，不重复启动采集器。

`recovery.py --root <ROOT> --publish-root <MEDIA_ROOT>/bev_closeup` 默认输出恢复计划；`--apply` 需先取得同一worker锁、确认所有记录的进程/子树及准确脚本均已退出。只处理running claim，优先完整验证并发布已经生成的产物，再按原最多3次策略恢复不完整条目；原证据和每次恢复记录保留。终态失败不会被盲目重置。锁或活跃进程阻止恢复时，继续观察实际进程。验证工具异常保留证据，不放宽质量门槛。SSO需要通过save_auth刷新，必要时请用户完成交互。

本任务不改变生产GT、标注、模型Run、Trail、凭据、原媒体清理策略。规划约束dump及其 `1016-0821` 监测继续独立运行。回溯完成须逐成员复核receipt、文件SHA、完整时间/解码、分版本覆盖/缺口/失败及来源原因，完成审计后增量旁路仍继续等待新增成员。

### 2026-10-29 浏览器停滞恢复

首次批次的1009 `cn36854187` 已完整通过校验；0821 `cn35635843` 在377帧后失去页面renderer，Python/浏览器根仍存活，10分钟无日志或帧写入。保留 `manual-stall-evidence.json` 和原始377帧后，只清理精确start_ticks的Capture子树。coordinator已增加600秒无实际日志/帧/meta写入保护：自身心跳不计为录制活动，触发后保留证据并关闭所属子树、验证完成产物、退避重试。未被批次实际访问的后续Issue不扣重试次数。恢复探针可用 `--once --batch-size 1`，正常全量仍为3条一批和单worker；逐帧120秒门槛、布局、时序与解码契约不变。

### 上线与启动验收（2026-10-29 19:51 CST）

播放器及独立进度页面已发布 `26e3a65a875604bc039d535f9ab24e34af16f51a` / cache714，回执为 `releases/20261029T112402Z-26e3a65a8756/result.json`。统一门禁1132通过、7跳过，隔离灰度、精确SHA、PostgreSQL持久化、schema58和原身份/写入策略核验通过。本地真实共享模块的Chromium验收覆盖320/390/1440、中英文、深浅主题的12组合，三源切换保位/倍速、独立海报、语言刷新、共享下拉及Escape/外部关闭、边界、全屏切源、失败重试与进度状态；这是桌面浏览器视口测试，不是真机或生产登录后的视觉验收。

独立collector的恢复与范围映射修复来自 `a26d10e14daf8e3896d25e6acb7dd0fa1781feab`，只更新任务自己的code目录，不额外重启生产UI。历史1009三个已登记数据集双次扫描共205成员，按同Issue/同版本扩展媒体scope，原trip/anchor、视频SHA和冻结目标成员不变。批次结束后持锁激活的记录在 `updates/scope-alias-v1/activation.json`。三版本5个真实case的局部源与视频Range206已核验，1009历史入口可展示三源。

该时点全量仍在录制：6/4461已验证（3条旧验收样例复用、3条新增），并非采集完成。新进程35527启动于19:49:50、Capture35563，cwd分别为任务根/runtime；PID仅为历史证据，每次须重新核验。新批次包括原停滞case，源网络失败保留退避、不归为原始数据缺失。每10分钟heartbeat `bev` 已启用，每小时增量登记继续；原规划dump的 `1016-0821` heartbeat独立保留。
