# Scenario 路测 Bag 与 EzSim 复现全流程

本文用于在 `cloud_server` 上从一个 Trail `scenario_id` 开始，完成：

1. 查询 scenario 的 `trip_id`、时间窗和 issue id。
2. 下载路测 RA bag。
3. 使用路测地图和对应 binary 触发 EzSim 开环规划仿真。
4. 定位 EzSim 生成的 `output.bag` 和 `events.log`。
5. 检查 road/sim 是否触发 RA。
6. 使用 `ra_tools/check_sim` 做 `/planning/seed` 特征比较。

## 1. 登录与环境

```bash
ssh cloud_server
cd /home/didi/workspace/ra_tools
bash check_sim/repro/setup_cloud_python.sh

export LD_LIBRARY_PATH=/home/didi/.voyager/ezsim/binary/1665523/tmp/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/voy-sdk/lib/python3/dist-packages:$PYTHONPATH
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

export SCENARIO_ID=32138520
export BINARY_ID=1665523
export WORK_DIR=/home/didi/ra_bags/scenario_${SCENARIO_ID}
mkdir -p "$WORK_DIR"
```

如果只需要一条命令完成第 2 至第 6 步，使用：

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" --binary "$BINARY_ID"
```

首次执行前建议先检查计划，不下载 bag、也不启动仿真：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" --binary "$BINARY_ID" --dry-run
```

自动流程产物位于 `/home/didi/ra_bags/scenario_<scenario_id>/`：默认 topic 裁剪包
`road.bag`、指向 EzSim 产物的 `sim.bag`/`events.log` 软链接，以及记录 trip、binary、
sim id、状态和 topic 帧数的 `metadata.json`。

默认使用 sim topic 白名单，不再下载完整 raw bag：当前场景目录已有 `sim.bag` 时动态读取；
否则读取 `check_sim/repro/default_road_topics.txt` 中从 scenario `32141295` sim bag 提取的 70-topic
快照。完整 raw bag 需要显式使用：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --raw-road
```

只需要 5 个 RA 核心 topic 时显式使用：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --filtered-road
```

5-topic 裁剪包保存为 `road_filtered.bag`，完整包保存为 `road_raw.bag`，避免和默认
`road.bag` 混淆。`metadata.json` 中的
`road_download_mode`、`road_download_topics` 和 `road_bag` 会记录实际选择。

自定义 topic 时重复传入 `--road-topic`；此参数会自动启用 filtered 模式，不需要再加
`--filtered-road`：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --road-topic /planning/seed \
  --road-topic /planning/planning_debug \
  --road-topic /planning/assist_request
```

手工 `--road-topic` 包使用 topic 集合哈希命名，例如 `road_filtered_a1b2c3d4.bag`。
topic 必须以 `/` 开头，重复值会自动去重。

默认 `road.bag.complete` 内保存 trip、时间窗和 topic 集合签名。任一项变化时不会复用旧
`road.bag`，而会重新下载。

已有 sim bag 时，可以直接读取它的全部 topic，并下载路测侧同名 topic：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --road-topics-from-sim-bag
```

不传路径时默认读取：

```text
/home/didi/ra_bags/scenario_<scenario_id>/sim.bag
```

也可以指定任意 EzSim 输出：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --road-topics-from-sim-bag \
    /home/didi/.voyager/ezsim/simulation/<sim_id>/output.bag
```

topic 选择参数 `--raw-road`、`--filtered-road`、`--road-topic`、
`--road-topics-from-sim-bag` 互斥。最终 topic 列表、来源类型、sim bag/配置文件路径和 topic
数量会写入 `road_download_topics`、`road_topics_source_type`、
`road_topics_source_sim_bag`、`road_topics_source_file`、`road_topics_source_count`。

`metadata.json` 会同时记录请求值和 EzSim 最终生效值：

- `requested_binary_id` / `requested_build`
- `sim_binary_id` / `sim_build_dir_hash`
- `sim_runtime_dir` / `sim_server_version`
- `sim_skip_map_update` / `sim_skip_model_update`

其中 `sim_binary_id` 和 `sim_runtime_dir` 来自仿真完成后的 EzSim API 返回，用于确认实际
运行版本，而不只依赖命令行请求值。

`BINARY_ID` 应替换为路测当时版本对应的 Orion binary。使用更新的默认 build 只能用于
现状验证，不能作为严格的路测复现结论。

## 2. 查询 scenario 元数据

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 - "$SCENARIO_ID" <<'PY'
import json
import sys

from ra_api.scenario_api import ScenarioInterface

scenario_id = sys.argv[1]
df = ScenarioInterface.query_scenario(query_scenario_ids=scenario_id, size=1)
if df.empty:
    raise SystemExit(f"scenario not found: {scenario_id}")
row = df.iloc[0]
keys = ["id", "name", "issue_uid", "trip_id", "start_timestamp", "end_timestamp"]
print(json.dumps({key: str(row.get(key, "")) for key in keys}, ensure_ascii=False, indent=2))
PY
```

记录输出中的：

- `trip_id`
- `start_timestamp`
- `end_timestamp`
- `issue_uid`

## 3. 下载路测 bag

自动脚本默认按 trip 和时间窗下载完整原始 bag。为了覆盖 warmup 状态，默认把
`start_timestamp` 向前扩 5 秒。

```bash
cd "$WORK_DIR"
voy-bag download road_raw.bag \
  -t <trip_id> \
  -s <start_timestamp_ms> \
  -e <end_timestamp_ms>
```

也可以按 issue 下载完整包，但通常明显更大：

```bash
voy-bag download road_raw.bag -i <issue_uid>
```

磁盘受限时才使用 topic 裁剪：

```bash
voy-bag download road_filtered.bag \
  -t <trip_id> -s <start_timestamp_ms> -e <end_timestamp_ms> \
  -T /planning/seed \
     /planning/planning_debug \
     /planning/remote_assist_model_debug \
     /planning/assist_request \
     /planning/stuck_detection_recall_signal
```

服务器磁盘使用率较高，下载完整包前应确认剩余容量。不要同时保留多个重复的完整 bag。

完整 bag 会打开大量临时流。自动脚本会把 `voy-bag` 继承的文件描述符 soft limit 提升到
`65536`，并只在下载成功后为选中的 road bag 创建 `.complete` 标记。如果下载中断，下次
执行会删除未标记完成的半包并重新下载。

已有 sim、只需要补原始 road bag 时使用：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only
```

遇到 `Too many open files` 时可显式提高目标值，但不能超过服务器 hard limit：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --nofile-limit 131072
```

`voy-bag` 默认使用 Python Protobuf，保持 Voyager 旧 proto、Data Gateway 鉴权和完整 topic
流程的兼容性。重复的性能提示由父进程精确过滤，不会隐藏其他 stderr。C++ Protobuf 只在
同一 trip 的 1 秒 `/planning/seed` 小样中验证过，不作为完整 raw bag 的默认配置。需要实验
C++ 性能时显式指定：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --download-protobuf cpp
```

脚本仍会过滤完全匹配的重复 Protobuf 性能提示，但不会过滤其他 stderr。下载期间每 30 秒
打印一次当前 road bag 的实际大小；默认连续 300 秒不增长时打印 stall warning，但不会
自动终止下载。阈值可调整：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --stall-warning-seconds 600
```

## 4. 先检查是否已有历史 EzSim

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 check_sim/repro/ezsim.py --list | grep "ra_repro_${SCENARIO_ID}" || true
```

如果已有状态为 `Success` 的同 binary 结果，优先复用，产物位于：

```text
/home/didi/.voyager/ezsim/simulation/<sim_id>/output.bag
/home/didi/.voyager/ezsim/simulation/<sim_id>/events.log
```

## 5. 触发 EzSim

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 check_sim/repro/ezsim.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --wait
```

脚本默认：

- `PLANNING,PERFECT_POSE`
- warmup 5000 ms
- `skip_map_update=False`，使用路测当时地图
- `skip_model_update=False`，允许补齐目标 binary 的模型包

不要为严格复现添加 `--skip-map-update` 或 `--skip-model-update`。

命令输出会打印完整 `sim_id`。完成后设置：

```bash
export SIM_ID=<sim_id>
export SIM_DIR=/home/didi/.voyager/ezsim/simulation/$SIM_ID
ls -lh "$SIM_DIR/output.bag" "$SIM_DIR/events.log"
```

## 6. 检查 road/sim RA 触发结果

先按时间戳比较关键 topic 的帧数和对齐覆盖率：

```bash
.venv/bin/python3 check_sim/bag/compare_road_sim_bags.py \
  "$WORK_DIR/road.bag" \
  "$WORK_DIR/sim.bag"
```

脚本默认比较 `/planning/seed`、`planning_debug`、`remote_assist_model_debug`、
`assist_request` 和 `stuck_detection_recall_signal`。`road cov`/`sim cov` 表示在另一侧
50 ms 内找到最近消息的比例；可用 `--tolerance-ms` 调整，或重复传入 `--topic` 比较其他
topic。需要机器可读结果时增加 `--json`。

不要直接按帧序号比较。仿真存在 warmup、模块启动和丢帧差异，应先按 bag 时间戳对齐，再
比较对应消息字段或 `/planning/seed` 中的模型特征。

最直接的判断：

- road 和 sim 都有 `assist_request`：触发结果复现。
- road 有、sim 没有：复现失败，需要继续比较 DNN 分数、FP 抑制和 feature。
- 两边都没有：先确认目标 road 时间窗和 issue 是否正确。

再检查 sim 事件：

```bash
grep -aoE 'rt_event\.planner::[A-Za-z0-9_]+' "$SIM_DIR/events.log" | sort | uniq -c
```

重点关注：

- `AssistStuckForcingRecallHit`
- `AssistStuckRequestForbidByLaneChange`
- `AssistStuckFNSelectionTriggered`
- `RouteUnstuck`

### 对比 FP/FN 规则字段

topic 帧数对齐后，使用专用脚本比较 `planning_debug.behaviorReasonerDebug`
中的 RA 状态、reasoner 输出和模型分：

```bash
.venv/bin/python3 check_sim/bag/compare_ra_debug.py \
  "$WORK_DIR/road.bag" \
  "$WORK_DIR/sim.bag"
```

脚本默认排除 warmup：优先读取两个 bag 同目录 `metadata.json` 中精确的
`trip_segment.startTimestamp`；metadata 不存在时，从 road/sim 共同起点排除 5000 ms。
使用 `--warmup-ms` 修改回退时长，只有专门排查 warmup 恢复时才传 `--include-warmup`。

正式窗口内按 bag 时间戳在 50 ms 内匹配消息，并输出：

- `unstuck_status`：最终状态，例如 `MODEL_FP`、`MODEL_REQUEST`。
- `process_reason`、`fp_reasons`、`fn_reasons`：具体命中的规则。
- `rule_decision`：仲裁结果，例如 `kAbort`、`kModelDetected`。
- `active_rules`：规则 activation 位。
- `scenario_dnn`、`threshold`：模型分和阈值。
- `lane_change_forbid_ts`：换道模块写入的禁止 RA requirement 时间戳。

若 sim 出现 `FP_LANE_CHANGE_FORBID` 而 road 没有，继续检查同一时间的
`/planning/seed.behavior_seed.assist_stuck_seed.ra_intervention_requirements`
和换道轨迹选择。不要通过删除 FP reasoner 或放宽 4 秒有效期来让仿真“通过”；应修复
仿真中 cross-lane requirement 的来源、warmup 恢复或上游场景发散。

## 7. 使用 check_sim 比较模型特征

先把 sim bag 链接到本场景工作目录，避免复制大文件：

```bash
ln -s "$SIM_DIR/output.bag" "$WORK_DIR/sim.bag"
cd /home/didi/workspace/ra_tools
```

当前 `check_sim/analysis/01-07` 已在 `ra_tools` 内独立维护。先按目标时间检查并抽取单帧特征：

```bash
export PY=/home/didi/workspace/ra_tools/.venv/bin/python3
export TARGET_MS=<road_target_timestamp_ms>

$PY check_sim/analysis/01_check_nearby_frames.py \
  --road "$WORK_DIR/road.bag" \
  --sim "$WORK_DIR/sim.bag" \
  --ts "$TARGET_MS" \
  --count 2

$PY check_sim/analysis/03_extract_features_to_npz.py \
  --road "$WORK_DIR/road.bag" \
  --sim "$WORK_DIR/sim.bag" \
  --ts "$TARGET_MS" \
  --offset -1 \
  --road-output "$WORK_DIR/road_features.npz" \
  --sim-output "$WORK_DIR/sim_features.npz"
```

对已抽取的 npz 做 nearby lane 对齐：

```bash
$PY check_sim/analysis/06_analyze_nearby_lane_alignment.py \
  --road "$WORK_DIR/road_features.npz" \
  --sim "$WORK_DIR/sim_features.npz" \
  --show-mapping
```

ONNX 模型需要单独放到服务器；`.onnx` 被仓库 `.gitignore` 排除，不会随 clone 下载。

## 8. 结果归档与清理

### Ego pose / smart agent A/B

当 road/sim ego speed 趋势一致但数值存在明显偏差时，运行两组隔离实验：

```bash
.venv/bin/python3 check_sim/repro/run_pose_ab.py \
  <scenario_id> --binary <road_test_binary_id>
```

- `replay_road_pose`：保留 smart agent，增加
  `--sim_overwrite_ego_pose_with_trip_pose`，验证 PerfectPose 闭环速度的影响。
- `disable_smart_agent`：保留默认 PerfectPose，增加 `--sim_smart_agent=false`，验证
  smart agent 通过障碍物运动和 planning trajectory 间接影响 ego speed 的程度。

实验复用主场景的 `road.bag`，结果保存在：

```text
/home/didi/ra_bags/scenario_<id>/experiments/
├── replay_road_pose/{road.bag,sim.bag,events.log,metadata.json}
├── disable_smart_agent/{road.bag,sim.bag,events.log,metadata.json}
└── summary.json
```

默认复用已经成功的实验；传 `--force` 才会重新发起。可用
`--experiment replay_road_pose` 或 `--experiment disable_smart_agent` 只运行一组。

### Scenario 29434409 A/B 结论（2026-07-14）

正式对比从 `trip_segment.startTimestamp=1777372719965` 开始，不包含 5 秒
warmup。路测 `/pose` 与仿真 `/simulation/pose` 按消息时间戳在 20 ms 内对齐。

| 实验 | speed MAE | speed P95 | 0.5 m/s 阈值异步帧 | 首次路测请求前 Yield 决策差异 | RA 请求时间 |
|---|---:|---:|---:|---:|---:|
| road | - | - | - | - | `1777372739933` |
| baseline | 0.0577 m/s | 0.2048 m/s | 155 | 22 | `1777372741648` |
| replay road pose | 0 | 0 | 0 | 0 | `1777372742157` |
| disable smart agent | 0.0577 m/s | 0.2048 m/s | 155 | 22 | `1777372741648` |

结论：

- PerfectPose 使用 planner trajectory 生成 `/simulation/pose`，没有保证速度与路测
  `/pose` 完全一致。小幅速度误差会改变跨越 `0.5 m/s` 静止阈值的时刻，并使
  `yield_temp_parked_cycles` 相差约 6 个 planning cycle。
- 回放路测 pose 后，首次请求前的 `FP_YIELD_DYNAMIC_OBJECT` 差异从 22 帧降为
  0，证明速度时序是该 FP 分支不一致的直接原因，而不是 Yield FP 判断了不同
  的障碍物。
- 关闭 smart agent 的结果与 baseline 完全相同，本场景可以排除 smart agent。
- pose 对齐后模型分数仍不同，且仿真请求没有提前。速度差异只解释 Yield FP
  时序，不能解释全部模型输入和请求仲裁差异。

进一步解析 selected trajectory 的 `StuckSignal` 后，正式请求差异落在 voluntary
unstuck 门控的上游输入：

- 路测首次 `MODEL_REQUEST` 帧为 `reason=kNoStuck`、`start_timestamp=0`，但
  `last_stuck_timestamp=1777372738256` 仍保留旧值。
- `IsVoluntaryUnstuckFail()` 直接计算 `last_stuck_timestamp - start_timestamp >
  5000`，没有先检查 `reason` 或 `start_timestamp` 是否有效，因此该掉零帧立即
  得到 `UnstuckFail`，绕过 voluntary unstuck 等待并发送请求。
- baseline sim 同期仍是 `kNotBlockageObject`，signal duration 为 2490 ms，返回
  `WAITTING_CORE_PLANNER_UNSTUCK`；到 signal 后续掉零时才请求。
- replay road pose 消除了 Yield FP 差异，但没有复现路测同一时刻的 selected
  trajectory StuckSignal 掉零，因此正式请求仍晚于路测。

这说明当前 case 有两条独立差异链：PerfectPose 速度阈值影响 Yield FP 时序；
selected trajectory 的 StuckSignal 连续性影响 voluntary unstuck 门控和正式请求。
此外，旧 Orion base DPE 记录未触发，而当前相同 binary/extra args 重跑既有
`MODEL_REQUEST`、`/planning/assist_request`，也有一帧 opened assist session，表明
本 case 还存在跨运行时序敏感性。报告中必须区分旧任务指标和当前重跑实测。

`WAITTING_CORE_PLANNER_UNSTUCK` 不代表模型未检出。代码在模型已返回
`kModelDetected` 后仍会检查 voluntary unstuck 状态；处于自主脱困阶段时只发送
recall signal，不发送正式 AssistRequest，并返回该状态。用
`compare_ra_debug.py` 中的 `non_voluntary_unstuck_reason`、`stuck_timer_ms`、
`strict_model_detected` 和 `uncertain_stuck` 判断门控解除原因。

建议长期保留：

- `summary.json`、`summary.csv`
- road/sim feature npz
- `events.log`
- scenario 元数据和使用的 binary id

bag 体积较大，确认 npz 和结论后再按服务器容量清理。不要删除
`~/.voyager/ezsim/simulation/<sim_id>`，除非确认该 EzSim 结果不再需要。
