# 准召趋势图 UI 调研与决策

## 结论

当前看板继续使用 Recharts，不立即迁移图表库。当前数据量是 12 个 release、最多 4 条线，Recharts 的多序列折线、响应式容器、Tooltip、LabelList 和轴配置已经足够。换库带来的包体、交互迁移和验收成本高于当前收益。

准召趋势图固定展示同版本全量预估，移除滚动回测模式选择和当前版本徽标；标题、图例与三个指标按钮放在同一行，图例靠右紧邻按钮，窄屏允许换行。三个指标按钮为：精确率、召回率、全部。四条指标线全部使用实线；精确率用实色蓝／青，召回率用实色红／橙来区分线上与仿真，避免依赖深浅区别。所有模式显示点数值，相近标签在点上方错开。横轴将 release key 压缩为 `MM-DD`，版本较多时减少 tick 数量但保留 Tooltip 中的完整版本号。

两张趋势图共用 `frontend/src/lib/releaseChart.ts` 的 release 序号横轴：每个版本占等宽区间，日期刻度、折线点、悬停竖线使用同一个中心坐标。浮窗默认距竖线右侧 40px，右侧空间不足时自动放左侧。浮窗共用 88% 不透明度背景与轻微模糊，避免遮住当前点的数值标签。不要按容器宽度手算 band 半宽偏移；双 Y 轴、响应式宽度变化会使此计算失效。复现率图左轴固定 60%～100%，右轴显示柱状数量的自适应刻度；准召图左轴用整数刻度和自适应步长。两图共用网格样式、288px 图高及左右轴预留空间，均显示五条水平网格线（四等分），确保同一版本点位上下对齐。

刷新期间保留最近一份与当前配置 hash 匹配的完整快照。旧配置的快照不能参与当前图表，避免历史版本混入当前 release 曲线。图表数据缺失保持断点，不能用 0 或插值填充。

## 参考实现比较

| 方案 | 可借鉴点 | 当前是否迁移 |
|---|---|---|
| Recharts | 多序列 LineChart、ResponsiveContainer、Tooltip、LabelList、轴 interval、同步交互 | 保留，当前规模已经够用 |
| Apache ECharts | `axisPointer` 十字指针、轴标签旋转、dataZoom、双轴组合图 | 版本超过约 30 个或需要缩放/刷选时再评估 |
| Ant Design Charts | Legend filter、Tooltip、Slider、Focus and Context、组合图示例 | 作为交互设计参考，不引入第二套图表运行时 |
| MUI X Charts | axis tooltip 一次显示同一 release 的所有 series、Legend toggle、隐藏 series 不重算轴域 | 当前用 Recharts 自定义 Tooltip/按钮实现相同模式 |
| Carbon Charts | 先明确图表故事；趋势用折线；轴和标签保持简单；缺失数据不插值；时间轴刻度保持一致 | 作为视觉和数据表达规范 |

官方资料：

- [Recharts examples](https://recharts.github.io/en-US/examples/)：包含多序列、Compare Two Lines、Axis Interval、Highlight And Zoom 等折线案例。
- [MUI X Tooltip](https://mui.com/x/react-charts/tooltip/)：区分 item tooltip 和 axis tooltip，axis tooltip 适合同一 release 对比多条 series。
- [MUI X Legend](https://mui.com/x/react-charts/legend/)：Legend toggle 和仅按可见 series 计算轴域的交互模式。
- [Apache ECharts Axis](https://echarts.apache.org/handbook/en/concepts/axis/)：axisPointer、轴标签旋转和多轴配置。
- [Ant Design Charts Gallery](https://ant-design-charts.antgroup.com/en/examples)：Legend filter、Slider、Focus and Context、Series Line 等案例。
- [Carbon Axes and Labels](https://carbondesignsystem.com/data-visualization/axes-and-labels/)：轴刻度、缺失数据和时间序列标签原则。

## 当前实现验收点

- “全部”模式四条线可见，点数值保持显示，Tooltip 按 release 同时显示线上/仿真精确率和召回率。
- 用真实数据在浏览器分别检查首个、中间、末尾 release：竖线穿过折线点，浮窗与竖线保持 40px 间距且不会遮住它；在 1、5、12 个版本下检查横轴均分。
- 复现率图左轴使用 60%、70%、80%、90%、100% 刻度，右轴显示整数计数；准召图左轴按可见数据自适应。
- 汇总表固定列宽，表头按语义换行，数据源和数值列居中。
- 总览首屏不请求 Issue 明细；版本、summary、comparison 并行加载；浏览器缓存和后端快照用于刷新期间维持旧内容。
