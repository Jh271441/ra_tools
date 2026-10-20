# Cron 运行图采用的公开模式

核对日期：2026-10-20。使用官方文档及维护方源码，不按第三方介绍推断产品行为。

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
