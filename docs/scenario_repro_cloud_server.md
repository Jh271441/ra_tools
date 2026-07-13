# Scenario 路测 Bag 与 EzSim 复现全流程

本文用于在 `cloud_server` 上从一个 Trail `scenario_id` 开始，完成：

1. 查询 scenario 的 `trip_id`、时间窗和 issue id。
2. 下载路测 RA bag。
3. 使用路测地图和对应 binary 触发 EzSim 开环规划仿真。
4. 定位 EzSim 生成的 `output.bag` 和 `events.log`。
5. 检查 road/sim 是否触发 RA。
6. 使用 `check_sim_reproduction` 做 `/planning/seed` 特征比较。

## 1. 登录与环境

```bash
ssh cloud_server
cd /home/didi/workspace/ra_tools
bash scripts/setup_cloud_python.sh

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
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" --binary "$BINARY_ID"
```

首次执行前建议先检查计划，不下载 bag、也不启动仿真：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" --binary "$BINARY_ID" --dry-run
```

自动流程产物位于 `/home/didi/ra_bags/scenario_<scenario_id>/`：默认 topic 裁剪包
`road.bag`、指向 EzSim 产物的 `sim.bag`/`events.log` 软链接，以及记录 trip、binary、
sim id、状态和 topic 帧数的 `metadata.json`。

默认使用 sim topic 白名单，不再下载完整 raw bag：当前场景目录已有 `sim.bag` 时动态读取；
否则读取 `config/default_road_topics.txt` 中从 scenario `32141295` sim bag 提取的 70-topic
快照。完整 raw bag 需要显式使用：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --raw-road
```

只需要 5 个 RA 核心 topic 时显式使用：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --filtered-road
```

5-topic 裁剪包保存为 `road_filtered.bag`，完整包保存为 `road_raw.bag`，避免和默认
`road.bag` 混淆。`metadata.json` 中的
`road_download_mode`、`road_download_topics` 和 `road_bag` 会记录实际选择。

自定义 topic 时重复传入 `--road-topic`；此参数会自动启用 filtered 模式，不需要再加
`--filtered-road`：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
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
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
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
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
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
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only
```

遇到 `Too many open files` 时可显式提高目标值，但不能超过服务器 hard limit：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --nofile-limit 131072
```

`voy-bag` 默认使用 Python Protobuf，保持 Voyager 旧 proto、Data Gateway 鉴权和完整 topic
流程的兼容性。重复的性能提示由父进程精确过滤，不会隐藏其他 stderr。C++ Protobuf 只在
同一 trip 的 1 秒 `/planning/seed` 小样中验证过，不作为完整 raw bag 的默认配置。需要实验
C++ 性能时显式指定：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --download-protobuf cpp
```

脚本仍会过滤完全匹配的重复 Protobuf 性能提示，但不会过滤其他 stderr。下载期间每 30 秒
打印一次当前 road bag 的实际大小；默认连续 300 秒不增长时打印 stall warning，但不会
自动终止下载。阈值可调整：

```bash
.venv/bin/python3 scripts/scenario_repro.py "$SCENARIO_ID" \
  --binary "$BINARY_ID" \
  --road-only \
  --stall-warning-seconds 600
```

## 4. 先检查是否已有历史 EzSim

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 scripts/ezsim_run.py --list | grep "ra_repro_${SCENARIO_ID}" || true
```

如果已有状态为 `Success` 的同 binary 结果，优先复用，产物位于：

```text
/home/didi/.voyager/ezsim/simulation/<sim_id>/output.bag
/home/didi/.voyager/ezsim/simulation/<sim_id>/events.log
```

## 5. 触发 EzSim

```bash
cd /home/didi/workspace/ra_tools
.venv/bin/python3 scripts/ezsim_run.py "$SCENARIO_ID" \
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
.venv/bin/python3 scripts/compare_road_sim_bags.py \
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

## 7. 使用 check_sim 比较模型特征

先把 sim bag 链接到本场景工作目录，避免复制大文件：

```bash
ln -s "$SIM_DIR/output.bag" "$WORK_DIR/sim.bag"
cd /home/didi/workspace/check_sim_reproduction
```

当前 `01/02/03` 脚本仍带有 `cn30851935` 默认文件名和目标时间，分析新场景前需要通过参数化
版本指定 road/sim bag 和对齐时间。批量 job 结果可使用：

```bash
/home/didi/workspace/ra_tools/.venv/bin/python3 08_batch_job_diff_analysis.py \
  --job-id <orion_job_id> \
  --limit 5 \
  --bag-dir "$WORK_DIR" \
  --output-dir "$WORK_DIR/batch_diff_outputs"
```

对已抽取的 npz 做 nearby lane 对齐：

```bash
/home/didi/workspace/ra_tools/.venv/bin/python3 06_analyze_nearby_lane_alignment.py \
  --road "$WORK_DIR/road_features.npz" \
  --sim "$WORK_DIR/sim_features.npz" \
  --show-mapping
```

ONNX 模型需要单独放到服务器；`.onnx` 被仓库 `.gitignore` 排除，不会随 clone 下载。

## 8. 结果归档与清理

建议长期保留：

- `summary.json`、`summary.csv`
- road/sim feature npz
- `events.log`
- scenario 元数据和使用的 binary id

bag 体积较大，确认 npz 和结论后再按服务器容量清理。不要删除
`~/.voyager/ezsim/simulation/<sim_id>`，除非确认该 EzSim 结果不再需要。
