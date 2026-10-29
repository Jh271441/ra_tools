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
