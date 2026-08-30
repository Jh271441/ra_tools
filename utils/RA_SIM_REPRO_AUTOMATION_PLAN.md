# RA 路测数据与仿真复现自动化计划

更新时间：2026-08-31

## 1. 目标与口径

项目分为两条必须同时成立的链路：

1. Trail 路测 issue 挖掘尽可能复刻数易
   `dwd_rt_ra_issue_triage_result_hf` 的筛选与准召口径。
2. 将同一批 issue 稳定转换为 scenario，按 release/binary 运行 Orion，输出可审计的
   路测行为复现率和 truth Precision/Recall，并发布到 Dashboard。

三类数据语义：

- `positive_auto`：路测自触发且业务真值为正确触发/无需协助；仿真期望触发，truth 记 TP。
- `negative_auto`：路测自触发但业务真值为误触发；仿真仍期望复现触发，truth 记 FP。
- `positive_manual`：路测人工触发且属于应自动触发场景；仿真期望不复现路测的人工触发，
  truth 中若未自动触发记 FN。

因此必须并列展示两组指标，不能混用：

- road→sim 行为复现率；
- truth TP/FP/FN/TN、Precision/Recall。

## 2. 路测数据对齐

权威基准是数易报表使用的底表和聚合 SQL。Trail 查询只作为可自动化复刻入口。

当前 release 级查询至少包含：

- `version like gen4-release-YYYYMMDD`；
- `trip_category in [0]`；
- `trip_odd in [ODD2]`；
- `platform in [7, 8]`，对应 GEN4_PT/GEN4_SOP；
- `is_deleted in [0]`；
- `ra_type in [2]` 用于自触发；召回分母使用 `[2, 3]`；
- 路测标签/`tags_ops like '%RA&stuck%'` 通过 Trail 的
  `abnormal_behavior` 枚举映射实现，并保留枚举映射审计。

每次数据刷新都生成逐 issue 差集，不只比较总数：

- 数易有、Trail 无；
- Trail 有、数易无；
- 相同 issue 但 trigger/result/version 字段不同；
- join 或一对多展开产生的重复 issue。

数易分子分母必须以 distinct `issue_id` 计算。Trail 结果也先按 `issue_id` 去重，再比较。

## 3. Issue 转 Scenario

原始转换逻辑以 `ra_start_timestamp` 为锚点：

```text
scenario_start = max(ra_start_timestamp - 20s, trip_start_time)
scenario_end   = min(ra_start_timestamp + 10s, trip_end_time)
warmup         = 3s
```

转换前门禁：

- issue_id、trip_id、ra_start_timestamp、trip 起止时间非空；
- 起止时间合法且 scenario 不越过 trip 边界；
- 同一分析集合 issue_id 和 scenario_id 唯一；
- `does not have bags`、`trip_id does not exist` 作为明确不可重试损失单独统计；
- timeout、服务错误等未知上传失败不能静默排除。

标签至少包含 source release、cohort、trigger 类型和 issue id，名称保持确定性，重复运行复用
已有 scenario。

## 4. 仿真可复现性分层

scenario 成功创建不等于能够复现。需要分别统计：

- scenario/bag 可用率；
- Orion simulation 完成率；
- DPE 覆盖率；
- inference log 和关键 output bag 完整率；
- road→sim 行为复现率；
- truth Precision/Recall。

不可复现原因至少分为：bag 缺失、时间窗不足、依赖线上/云端状态、初始化差异、模型未运行、
DPE 缺失、仿真输出缺失、真正的模型/规则行为差异。

## 5. 四版本滚动 Binary 回测

目标 release 的 binary/runtime 回放目标版本及其前三个连续 release：

```text
target T binary × [T-3, T-2, T-1, T] source scenarios
```

每个 source release 对三个 cohort 做固定 seed 的均匀抽样。registry key 包含 target、source
集合、抽样数、seed、manifest hash 和 replay 配置 hash，重复提交必须拒绝。

Gen4 硬门禁：

- cluster=`prod_gen4`；
- 同一时刻仅一个活动 Orion Job，`max_concurrency=1`；
- simulator cache disabled；
- 每个 task 启用 DPE；
- `--planning_enable_sim_assist_stuck_independent_replay`；
- binary ID 与 target release 配置一致。

运行中增量检查已完成样本：

- cache hit=0；
- inference log、DPE output、关键 output bag 非空；
- failed evaluation=0；
- unexpected warning=0；
- manifest 与 Orion scenario 必须有精确交集并保持完整计数。

Orion 可能因 DPE 内存不足等基础设施原因自动提升资源并重试同一 task。报告必须保留
`task_runs` 的重试次数、历史失败 run 和 DPE OOM scenario id；只有最终 task 成功且输出
完整时才允许通过。历史 infra retry 本身不计作模型失败，也不能从审计中删除。

出现 task 异常或质量污染时，先写 JSONL 审计，再按授权取消剩余任务。完整 Job 通过后才补齐
同 target 的缺失 source；四个 source 全部通过后才发布指标。

## 6. 指标与 Dashboard

每个 target/source 输出：

- expected、evaluated、DPE coverage；
- TP、FP、FN、TN；
- Precision、Recall；
- cohort counts；
- job IDs、binary ID、配置门禁和质量门禁结果。

Dashboard 的“当前 Binary 跨版本准召预估”按可调 2/3/4 版本窗口聚合：

- 线上：窗口内 `auto_trigger_tp`、`auto_trigger_fp`、`manual_trigger_fn`；
- 仿真：目标 binary 对相同 source 窗口的 TP/FP/FN。

只有 target `quality_gate_passed=true`，且每个 source 满足
`expected=evaluated`、DPE coverage=100% 时，才允许展示仿真曲线。Dashboard refresh 失败可重试，
不能阻塞后续 Orion 实验。

## 7. 自动化状态机

状态转换顺序：

1. 检查 unresolved launch intent 和现有活动 Job；
2. 活动 Job 增量质量检查；
3. terminal Job 完整配置与离线质量检查；
4. 补目标窗口缺失 source；
5. 四个 source 完整后原子写 metrics artifact；
6. 异步刷新 Dashboard；
7. 推进下一个较早 target window；
8. 所有目标完成后退出。

关键文件：

- `scripts/ra_repro_launch_binary_backtest.py`
- `scripts/ra_repro_advance_binary_backtest.py`
- `scripts/ra_repro_run_binary_backtest_pipeline.py`
- `scripts/run_with_voyager_env.py`
- `scripts/ra_repro_validate_orion.py`
- `scripts/ra_repro_finalize_binary_backtest.py`
- `reports/ra_binary_backtest_20260831_jobs.json`
- `reports/ra_binary_backtest_20260831_pipeline.jsonl`
- `reports/ra_binary_backtest_20260831_metrics.json`

## 8. 验收标准

- Trail 与数易逐 issue 差集有明确解释，不能只用相近总数验收；
- scenario 转换损失和不可复现原因全部可计数；
- 每个 rolling target 的四个 source 均完整通过配置、DPE/cache/inference/output 门禁；
- artifact 中的 P/R 可从 scenario 明细重新计算；
- Dashboard 线上窗口和仿真窗口完全同源、同版本范围；
- 重启 runner 不重复创建 Job；异常取消、Dashboard 暂时不可用和 artifact 更新均有审计记录；
- 代码、测试和运行说明有独立 checkpoint commit/tag。

当前代码 checkpoint：`ra-binary-backtest-rolling-canary-20260831`。
