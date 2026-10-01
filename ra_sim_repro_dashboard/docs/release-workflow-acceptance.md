# 当前业务版本与 Issue 工作流：实施及验收记录

2026-09-30。状态：实现、预发布验收和正式发布完成。生产默认手动仿真。最新进展：用户要求取消串行Job后，0904已重提为Job47032991，并发上限1000，3089条实际任务参数与批准计划核验一致；旧Job47022753已取消。

## 已落实的业务规则

- Asia/Shanghai；每周一切换至上周四结束的实际 release 周期。
- 周四至周日不提前切换。新版本跑两周／没有新结束记录时保留上一完整版本。
- 周期按实际 Issue 分布与后继版本的开始记录识别，不用 release 名字日期减固定七天。
- 允许不同版本在切换日短暂并行，仍按 release 和周期查询；同一 release 的重叠周期配置拒绝。
- 当前业务版本与已有仿真结果分开；未仿真／待匹配记录保持空值，不冒充 FN。
- Issue 页只显示 `ra_type=2`；`ra_type=3` 另用于召回人口，人工“误触发”按原公式排除。
- 每个 Issue 原路测构建号保留；预估目标构建明确显示，多个 Scenario 不重复计入 Issue 人口。

## 已核实的真实数据

2026-09-30 使用既有 Trail app-21 客户端完整分页查询 view 2410，业务筛选与用户提供条件一致，准召人口使用 `[2,3]`。

| Release | 观察时间 | 自动 | 人工 | 总计 | 状态 |
|---|---|---:|---:|---:|---|
| 0904 | 09/10–09/24 | 2613 | 601 | 3214 | 本周已结束版本 |
| 0918 | 09/24–09/30 | 954 | 302 | 1256 | 仍在运行，未臆造结束日 |

0904 评测可用三组人口：3089（positive_auto 2232、negative_auto 361、positive_manual 496），另外125条依既有口径排除。线上 P≈86.08%，R≈81.82%。

0904 的路测构建 `.555` / `.567` / `.568` 分别对应1429 / 370 / 1415条。通过 Orion BinaryAccessor 按实际构建号匹配，最新 `.568` 的 binary 是 `1804023`，commit `8d383c9334ce1357f2f15fd2810fe93a9f70335a`。0918 `.578` binary 是 `1810741`。

旧 Scenario label `ra_repro_full_20260916_20260904` 在线查询1159个场景，真实labels已核对。Scenario API 没有 issue_id / disengage_info_id，当前使用唯一 `#<issue数字ID>` 来源label关联；冲突拒绝。

现有人口中1150个可评测Issue已有场景，缺1939个。新场景计划转换全部通过：前20秒／后10秒／warmup3秒，trip边界无告警，label `ra_repro_cycle_20260924_0904`。

## 本地实现

- 独立周期解析、每周观测周期目录、签名完整分页查询、原子人口快照、周期 Issue API。
- 默认配置已包含0904已结束周期和0918运行状态。未来周期目录从实际切换数据补充；长尾／非周四切换留待核对。
- 新增快照、设置和仿真批次表，旧表结构保留。
- 15分钟同步；每周周期目录最多3次补查，失败按小时退避；模式和任务回执持久化。
- 手动预览／排队／提交；自动模式必须通过真实预检并启用后台调度。转回手动仍跟踪既有Job。
- 同一人口／目标binary／场景版本／运行配置使用hash去重；评论、名称、label的普通更新不重复提交。
- 独立 `scripts/ra_release_orion_driver.py`：真实Orion模板与binary核验、baseline或显式独立回放、单Job并发1、DPE、禁用cache、完整结果覆盖、质量门禁。
- 提交前持久化；模糊回执不盲重试，支持读取驱动回执恢复job_id。
- 完成后按Issue汇总准召和行为复现率；一个Issue多个Scenario按any-trigger聚合，避免人口膨胀。
- 新列表跟随当前版本，支持历史周期、搜索、真实label筛选和分页；历史仿真列表按需加载。

## 已完成验收

- 本轮后端／驱动／场景身份与既有结果门禁合并78项检查通过。
- 前端TypeScript／Vite构建通过。
- 原生Orion只读单场景预检通过：binary1804023、模板45142569、prod_gen4、runtime prod-76541、baseline参数。
- 内置浏览器使用真实数据验收当前版本、取数范围、原路测构建、未匹配空结果、真实label搜索、长文本布局与缺场景提交门禁。
- 隔离PostgreSQL数据库 `ra_sim_cycle_acceptance_20260930` 从生产副本创建：新增3表、3214条真实人口正常入库；原有22084条结果和旧汇总指标保持一致。
- SQLite与PostgreSQL均会阻止1939个缺场景的完整仿真提交。

## 场景补建与真实链路验收

- 用户明确批准创建1939条缺失场景后执行，最终1939成功、0失败；在线新label数量1939，与旧label1159合计3098。可评测计划3089，其余9个历史场景属于当前口径排除项。
- 首次上传发现pandas将带下划线trip_id自动数值化，服务拒绝这些请求。已修复为JSON原始字符串保真，逐条源身份比对后重跑；新增3项身份保真回归测试。
- 原生单场景验收Job `47016349` 已完成；DPE、缓存、输出完整性和配置门禁通过。
- 内置浏览器完成计划预览、关联已有Job、结果回填、自动再同步防重、切回手动保留结果。验收库始终只有1个批次，未将单场景结果发布到全量周期。
- 新周期的自动模式支持准备缺失场景与提交任务；不满足人口、GT、场景或binary门槛时保留待处理状态。

## 正式发布与核对

- 服务目录：`/volume/home/services/ra-sim`；source、runtime及数据库均已备份。
- 数据库备份：`backups/database-20260930T041021503819Z.sql`。
- 程序与runtime回退包：`backups/release-cycle-20260930/`。
- API、worker、web、PG、Redis、weekly启动正常；页面、资源及API检查通过。
- 当前指针0904；自动Issue2613、人工人口601、场景3098、可提交全量任务3089；默认manual，生产批次列表为空。
- 当前0904完整仿真指标保持待完成，历史0828等结果继续用于历史对比；版本、总览和Issue的业务当前版本一致。
- 正式服务通过SSH回环入口在内置浏览器完成页面与计划预览截图，不改变正式入口或权限。
- 正式HTTPS域名的已登录Chrome已完成实际页面验收：使用Chrome窗口控制进入 `/sim/issues`，强制刷新后显示0904业务当前版本、2613条自动Issue、601条人工人口、3098个场景及真实Scenario labels；计划预览返回3089个场景、binary1804023，模式保持手动，未提交全量Job。
- 浏览器标签页连接接口仍在30秒超时；Chrome窗口的读取、刷新、页面操作和截图正常，因此未将该接口超时解释为SSO或服务加载超时。普通刷新曾显示旧页面，强制刷新后加载本次发布的新资源。

代码检查：61项后端/驱动/场景读取回归通过；包含既有结果门禁的合并检查78项通过。前端构建通过。

截图：`reports/release_workflow_20260930/browser-production-plan.png`、`browser-completed-canary.png`；正式SSO域名：`browser-sso-production-issues.png`、`browser-sso-production-plan.png`。

生产未提交全量Job；用户可在页面预览后手动提交、关联已有Job或明确开启自动模式。验收单场景数据、token与私有快照不提交Git。

## Issue 与仿真拆分验收（2026-09-30 第二轮）

- `/sim/issues` 保留独立单版本明细；默认跟随当前0904，历史版本可直接选择，原来的根因／触发类型／TP-FP-FN-TN筛选、场景详情与同Issue场景保留。版本选择写入URL，深链接刷新与前后退正常。
- 当前版本恢复列表与右侧详情，真实Scenario labels位于详情且可点击筛选；Issue同步仍独立每15分钟运行。
- `/sim/simulation` 独立展示手动／自动、计划、Job与结果状态，不再混入Issue表格。未提交全量时明确说明尚无仿真准召。
- 历史明细新增分页；相同更新时间按版本与场景身份稳定排序，实际0828的FN分页无重复、重复读取顺序一致。
- 35项明细分页／工作流回归、5项入口契约检查及前端构建通过。先用真实生产API进行浏览器预验收，再发布并完成已登录Chrome正式域名截图。新页面的保留／剥离前缀路径均通过，线上资源hash与本次构建一致。
- 发布回退包：`/volume/home/services/ra-sim/backups/issue-sim-split-20260930T062214Z/`。仿真参数与运行模式未调整；生产仍manual、3089场景计划、批次为空。
- 正式截图：`browser-split-sso-issues.png`、`browser-split-sso-history.png`、`browser-split-sso-simulation.png`，位于 `reports/release_workflow_20260930/`。

## 实际回放参数与结果核对

- 对看板12个历史Job的17418个任务完整读取实际task_args：未设置`sim_state_recovery_level`，无独立RA回放标志，无缺失参数。不是依据后来修改过的启动脚本推断已运行Job。
- 已完成验收Job47016349同样未显式设置恢复level；核心sim-exec参数与基线Job45142569（RA_repro_initial_20260821）一致。区别为binary1775147→1804023、scenario38193673→39031957、cache strict→disabled；runtime prod-76541、DPE保持一致。
- 当前源码将恢复level默认定义为0；任务通过aligned mode与planner warmup参数单独启用恢复，不能把“未指定Level4”直接标成“标准Level3”。与具体RA AutoTrigger配置的逐项一致性需对应模板或Job ID核对；暂未以基线Job名字代替这一身份核验。
- 单场景实际结果再次查询为TP／已复现，完整性与质量门禁通过；不把单场景通过率用作全量周期准召。0904全量未提交。最新完整历史0828：P83.86%、R81.95%、行为复现90.9%。
- 参数审计与发布API核对保存在 `replay-parameter-audit.json` 和 `issue-sim-split-api-acceptance.json`。


## 0904 全量正式启动

用户明确接受动画差异并要求开始后，通过正式工作流提交固定计划 `40e6a1be918110aa6e11874c087817f8f97045c8bd0b7e087559959ba8222258`，返回 Orion Job `47022753`。全部3089个场景集合逐条一致；核心sim-extra-args、trip HD map、binary1804023、DPE和禁用缓存均核验通过。仍使用baseline，无Level4或独立RA回放，动画保持关闭。

提交后首次实查：Job RUNNING，1条RUNNING、3088条UNASSIGNED，并发1，prod_gen4 / prod-76541。看板批次已关联该Job，后台继续轮询；模式保持manual。本节更新取代前文发布验收时的“全量未提交”状态。回执：`reports/release_workflow_20260930/0904-full-job-launch.json`。

## Job 进度与按版本看板（2026-09-30）

- 仿真管理改为卡片看板：样本规模、关联场景、线上准召、独立Job进度卡、评测结果和操作区；长参数说明折叠收起。
- 版本选择覆盖14个release，支持当前0904、历史Job和0918路测收集中状态；版本写入URL，刷新保持选择。Issue入口跟随所选版本。
- 新增只读Orion `progress` 驱动动作与 `/workflow/board` 接口，逐Job缓存并用文件锁避免重复查询。页面每30秒更新，首次加载与主动刷新后更快取回新进度；终态历史Job采用较长缓存，仍可主动刷新。
- 展示成功、运行中、排队、失败、取消、未知、已结束百分比、任务总数、并发、耗时、更新时间、Job链接与异常任务示例。上游失败保留旧计数和时间戳，不显示伪造的0或100%。
- 仿真执行结束与结果质量门禁分别展示。历史归档准召保留，质量未通过时明确标记；当前周期完整指标仍须通过原有验收流程。
- 45项工作流、进度聚合、版本隔离及缓存错误回归通过，前端构建通过。浏览器实测0904自动更新、0828归档指标及失败Task展开、0918无Job状态、版本刷新保持和手动刷新；浏览器无console error。
- 已发布。回退包：`/volume/home/services/ra-sim/backups/progress-board-20260930T072628Z/`；T3650驱动回退：`driver-before-progress-20260930T072539Z.py`。新资源 `index-L_MAwApE.js` 的本地/线上SHA256一致。
- 正式接口15:28实查：0904 Job47022753，成功1、运行1、排队3087、失败0，3089任务计数闭合；0828 Job46268691，成功1506、失败1、合计1507。正式批次仍只有原0904 Job，模式manual。
- 截图：`board-current-preview.png`、`board-history-preview.png`，均为隔离验收库与真实Orion状态。正式域名截图补验时Mac已锁定，浏览器工具要求用户手动解锁；已告知用户，未把预发布截图当成正式域名截图。线上API验收记录：`progress-board-acceptance.json`。


## 并发调整至1000并重提（2026-09-30 22:18）

用户明确要求取消旧Job并将并发改为1000。官方取消代理已确认47022753为CANCELLED、运行0；同一3089场景及binary1804023重新提交为Job47032991，并发上限1000，首次实查实际运行60、排队3029。全部场景集合与核心参数核验一致，指纹为 `fa59383e340bed0f485c87fa28eb80fd91b76f3ef5fe9e3552f03f9ebd91496c`。

提交、计划、轮询校验和页面预览均改为读取配置中的并发值，支持1–1000的整数；取消状态可正常回填并释放旧批次。47项相关检查及前端构建通过，正式入口核验通过。配置回退包：`backups/concurrency1000-20260930T141503Z/`。原心跳自动化已更新为只跟踪新Job。


## HIGH submission - 2026-10-01 09:34 Asia/Shanghai

User requested cancellation and a new HIGH-priority job. Server source confirms that the earlier 509 applies to the administrative in-place modification API; standard submit_precheck accepts HIGH under normal submission authorization. The new submission used the official launch path and its permission checks. No administrative credentials or permission changes were used.

Old Job 47032991 is CANCELLED. New Job 47045687 is verified HIGH, max_concurrency=1000, with all 3089 scenario identities and execution parameters matching the approved plan. Initial progress: 0 completed, 0 running, 3089 queued, 0 failed. Fingerprint: 9d59c4e6d4a8f062599b3a3119f1382bed697ee7277e914cf63ea8d40a14d45c. 49 checks and frontend build passed. Deployment backup: backups/high-priority-20261001T013159Z/.

Priority is explicit in the plan and verified against actual job metadata. Only release0904 is configured HIGH; other releases retain NORMAL. Dashboard and heartbeat now track 47045687. Verification: reports/release_workflow_20260930/0904-high-launch.json.


## 2026-10-01 普优 / 高优并行对照

用户授权保留 HIGH Job `47045687`，新建 NORMAL Job `47052469`，两者并发上限均为 1000。预检后使用标准提交路径创建；逐条读取实际任务确认全部 3089 个场景及任务参数完全一致，runtime 均为 `prod-76541`。正式看板已登记两个独立批次，未更改默认优先级或模式。

16:15（Asia/Shanghai）共同对照基线：HIGH 成功 4、运行 1、排队 3084；NORMAL 成功 0、运行 0、排队 3089。按相同观测时段的新增完成数比较吞吐量，不将并发上限视作实际运行量。运行进度、提交回执和基线保存在本地 `reports/release_workflow_20260930/`，不纳入 Git；此时两个任务均未完成结果验收。
