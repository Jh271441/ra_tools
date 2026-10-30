# 每日任务运行图采用的公开模式

## 按版本查看同一流水线（2026-10-30）

本次展示调整复用同一个 React Flow/ELK 模型和共享增强下拉，不按版本复制页面或调度器。
页面顶部的“查看范围”默认选最新版本；所有已发现版本（包括1009）都保留独立入口，
另有显式“全部版本汇总”和旧日期批次。选定后轮询、新版本发现和语言切换不改变范围，
`cron_version`/`cron_day` URL参数支持刷新恢复。新版本只增加选择器选项，不增加首页流程图。

顶部推理/媒体计数、图节点、每轮增量和局部BEV成员统计使用同一版本范围。
全局07:00/19:00调度、Camera/Orion/本地并发和局部BEV控制器状态仍明确为共享信息。
历史日期批次及独立媒体回溯继续可查，不能把它们理解为停止采集的历史版本。
1009采集、源补齐、抽样、任务分配、GT/人审、预测与媒体数据均不迁移或冻结。

API保留原总览字段，增加`incremental.versions`。推理状态来自同一次只读SQLite台账
`items GROUP BY family,state`（mode=ro、query_only、750ms执行预算）；不以滞后的平台
导入状态代替采集队列。媒体回执只扫描一次，再与各版本当前目标成员求交、去重。
台账不可读时按版本显示不可用，媒体可独立展示；选择暂时消失的版本不会自动跳到别的版本。
无新增生产写接口、迁移、采集触发或模型调用。

回归入口：`test_cron_version_source.py`、`test_cron_version_views.py`，以及
`CRON_VERSION_QA=1 node ra_triage_dashboard/tests/cron_bootstrap_browser.cjs`。
浏览器使用合成只读API和实际前端模块；覆盖320/390/1440、中英、深浅主题、键盘/关闭、
选择保持及未知状态。此为响应式验收，不代表真机或线上SSO验收。

核对日期：2026-10-21。使用官方文档及维护方源码，不按第三方介绍推断产品行为。

| 参考 | 已核对的交互 | 当前实现 |
|---|---|---|
| [Airflow Graph View](https://airflow.apache.org/docs/apache-airflow/stable/ui.html#graph-view) | 按 Run 选择，任务依赖图叠加运行状态，节点可打开详情 | 主要参照；双任务链、日期选择、状态节点、详情侧栏 |
| [Airflow Run Graph 截图](https://airflow.apache.org/docs/apache-airflow/stable/_images/dag_run_graph.png) | 图作为执行排障的主要画布 | 大画布、平移、缩放、全屏、MiniMap |
| [Airflow 前端依赖](https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/ui/package.json) | React Flow 与 ELK | 使用相同的图组件/布局引擎；版本由 npm registry 核对并锁定 |
| [Prefect FlowRunGraphs](https://github.com/PrefectHQ/prefect/blob/main/ui/src/components/FlowRunGraphs.vue) | 运行图与选中项详情联动 | 点击任务显示该阶段的计数、回执、失败案例 |
| [Dagster UI](https://docs.dagster.io/guides/operate/webserver) | 独立运行与图视图 | 作为对照；当前流程是任务调度，未引入资产目录的页面结构 |

字体和主题继续使用 Workbench 的设计变量。将说明性流程图收进每个监控卡的“!”对话框；
实际执行图在主页面显示两个任务链，旁路从完成回执触发且无反向阻塞依赖。
运行中节点与依赖随30秒观测刷新；没有回执的阶段保持未知，不能因最终完成便将重试链补绿。
仅在有运行证据时显示运行中动画；未发生的路径不模拟流动。

历史旁路517只保留在折叠的历史区域。当前运行按同一天的完整冻结成员核验发布回执，
避免用已被替换的74条部分Run描述90条完整Run。已验证的Case在多队列出现时只计一次。
原始Orion队列覆盖范围单列，部分队列完成数不冒充完整批次总数。

构建源：`frontend/cron-graph/`；`npm ci --ignore-scripts && npm run build`。
浏览器使用已提交的 `static/vendor/cron-graph/`，无需生产环境安装 Node 或访问 CDN。
版本、构建产物哈希和许可证保存在该目录；React Flow采用MIT，ELK选择EPL-2.0许可。
未修改ELK源码，原版源码可从 [elkjs 0.12.0](https://github.com/kieler/elkjs/tree/v0.12.0) 获取。

MiniMap与主画布共用显式节点width/height，不能仅在style声明尺寸：
受控节点未回写measured时，缩略图会因缺少节点尺寸而变为空框。
缩略图为160×100，沿用状态颜色和主题，支持拖动/缩放；浏览器检查需确认实际SVG节点可见。

顶部主题、语言和刷新操作与工作台保持一致，靠右对齐。运行图为分支连线和标签保留独立间距，
节点标题、阶段计数和泳道标题提高字号/对比度，状态边框与加粗箭头强调流程。
未观测路径仍用中性虚线，不能因加强视觉而暗示执行成功或制造运行动画。
构建将模板字面量转换为语义一致的字符串，以避免依赖包内多行模板的行尾空格进入产物；
锁定依赖和许可证不变，产物哈希仍随构建更新。

连线、转折点和标签一起交给 ELK 正交布局，并直接渲染其路径；禁止只取节点坐标后
再用默认 smoothstep 重画。显式左入右出端口与节点尺寸一致，标签按中英文字宽保留
背景空间，成功、失败、仍失败分支不得穿过其他节点或互相遮盖。跨泳道完成回执
使用两组之间的独立通道，标签远离泳道边框。状态颜色、虚线和任务执行语义不变。
布局回归：`cd frontend/cron-graph && node --test tests/layout.test.mjs`，覆盖中英文、
双链实际运行与单链说明，检查节点互不覆盖、连线避让节点、标签避让节点/其他标签。

Run-date selection uses the shared themed single-select, including keyboard
selection, checked state, outside/Escape dismissal and viewport-aware anchoring.
The latest option includes its target date; completed-with-gaps is one status
phrase. Each refresh updates options and preserves automatic/manual selection.

## Duration and receipt spans

Run cards show the main pipeline's exported elapsed_seconds (registration to
execution receipt) and media time since cohort registration to the final dual
video publication receipt. The two independent pipelines are never summed.
Chinese timing always spells out 小时 and 分钟, including compact graph nodes;
compact hour values omit seconds, while details retain them. Finished stage
spans say 阶段用时. Acquisition/inference details explicitly include acquisition
and waits and state that inference-only runtime was not recorded separately.
Nodes have a separate timing row; both CSS and ELK use 116px task height so
counts, state and duration stay visible. Details and run history show CST start,
end, receipt coverage and the timing scope.

- Query/freeze span: scheduler launch to frozen cohort registration, including startup.
- Acquisition/inference span: registration to the first publication attempt,
  including acquisition, model work and preparation waits.
- Publication/sample span: first corresponding attempt to final verification
  receipt, including retry waits. Concurrent task durations are not summed.
- Dual-media publication span: first to final publication receipt; this is not
  video processing runtime.
- Orion task P50: observed median task runtime, explicitly distinct from batch
  wall-clock duration. Missing queue timing stays unavailable.
- Camera attempt: latest process start to final results for that exact cohort.
  Old batches without runtime start receipts remain unavailable.
- Local recovery span: first claim to final result for current cohort members,
  with concurrent work and retries represented by a wall-clock span.

Running elapsed time uses the observation timestamp and the existing 30-second
refresh. Stale/error views say last observed elapsed and keep a frozen snapshot.
Missing, invalid, reversed or future timing is unavailable; zero is distinct
from missing. Partial receipt coverage is labelled observed span with counts.

Stage reads are bounded to the latest eight main batches, validated Run/date
and selection-hash-bound publication cohorts. Do not read large/private Trail
selection snapshots or infer execution times from filesystem mtimes. Historical
runs retain exported totals. Replacement media cohorts must not reuse a partial
batch's registration start. Broken optional timing must preserve run outcomes
and progress. No scheduler, prediction, capture, Trail write or schema change.


## Per-stage progress · 2026-10-22

Task nodes show one compact count/percentage line and a4px track, retaining the
status and duration rows. Task height116px is shared by CSS and ELK. Failure
segments are amber; processed work includes failed/skipped items and does not
establish success. Counts cannot be inferred from elapsed time. Unknown, invalid
or inconsistent totals show “进度待回执”; upstream-dependent stages show “等待上游”.
Zero-work completed cohorts have no percentage. Stale/error snapshots freeze
counts, mute the track and explain the last observation in details.

Active main stages use finished/total before terminal selected/inferred aggregates
exist. Completed inference includes explicit skips; publication uses its own
inferred cohort; sample verification uses the sample-hook counters/receipt cohort,
never whole-run verified counts. Import/assignment shows assigned/target with
import counts in details. Camera uses confirmed completion; Orion uses its original
queue scope, with queue coverage and final dual-video verification kept separate.
Retry total comes only from the retry receipt, never the full daily cohort. Local
recovery counts launched attempts/finished receipts and explains that later claims
increase the denominator. Final coverage remains separate from assignment/readiness.

Desktop preserves the routed interactive graph. Phones<=639px display the same
TaskNode/progress component as paired128px stage cards with two-line titles,
grouped by the two pipelines;
buttons open and scroll to the existing detail panel, closing restores card focus.
Polling never initiates that scroll. Shared date picker occupies its own row
below title/fullscreen. Definition help has no live progress. Desktop/mobile
views share one selected node and update on the existing30-second polling cycle.
Only read-only projections/UI change; scheduler, inference, captures, notifications,
writer policy, database schema and task allocations remain unchanged.

## 首次加载性能（2026-10-23）

Cron 快照独立于数据集、模型 Run 与 Review 概览。bootstrap 在等待配置前立即发起
首次只读 Cron 请求，后续初始化复用该 Promise；共享初始化继续服务后续页面导航，
不再阻塞 Cron 首屏。页面激活时提前下载图组件，与快照并行；离开页面仍取消请求，
沿用 active/controller 所有权保护、8秒超时及30秒可见页轮询。

仅 `/static` 挂载 Starlette gzip（最小1024字节、等级5），保留原有缓存、
Content-Type 与条件请求。API 和媒体路由不进入压缩器。图资源 URL 随本次缓存版本
更新，避免浏览器继续复用旧未压缩副本。图脚本原始1,890,039字节，gzip约583,836字节。

回归：`navigation_races.cjs` 用未决配置、Run及概览验证首次 Cron 提前显示、
只读一次和离开页面后不回跳；`test_static_assets.py` 检查原始ASGI字节、解压一致性、
identity、Vary、304及API隔离。`cron_bootstrap_browser.cjs` 使用实际应用模块与
合成只读API，卡住配置时验证图已显示、中英/深浅主题、1440/390/320px和零写请求。
本地模拟耗时不代表生产端到端耗时；线上SSO视觉验收单独记录。
