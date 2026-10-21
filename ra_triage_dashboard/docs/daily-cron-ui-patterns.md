# 每日任务运行图采用的公开模式

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

## Duration and receipt spans

Run cards show the main pipeline's exported elapsed_seconds (registration to
execution receipt) and media time since cohort registration to the final dual
video publication receipt. The two independent pipelines are never summed.
Nodes have a separate timing row; both CSS and ELK use 104px task height so
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
