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

export LD_LIBRARY_PATH=/home/didi/.voyager/ezsim/binary/1665523/tmp/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/voy-sdk/lib/python3/dist-packages:$PYTHONPATH
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

export SCENARIO_ID=32138520
export BINARY_ID=1665523
export WORK_DIR=/home/didi/ra_bags/scenario_${SCENARIO_ID}
mkdir -p "$WORK_DIR"
```

`BINARY_ID` 应替换为路测当时版本对应的 Orion binary。使用更新的默认 build 只能用于
现状验证，不能作为严格的路测复现结论。

## 2. 查询 scenario 元数据

```bash
cd /home/didi/workspace/ra_tools
python3 - "$SCENARIO_ID" <<'PY'
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

推荐按 trip 和时间窗下载，并只保留 RA 分析需要的 topic。为了覆盖 warmup 状态，可把
`start_timestamp` 向前扩 5 至 10 秒。

```bash
cd "$WORK_DIR"
voy-bag download road.bag \
  -t <trip_id> \
  -s <start_timestamp_ms> \
  -e <end_timestamp_ms> \
  -T /planning/seed \
     /planning/planning_debug \
     /planning/remote_assist_model_debug \
     /planning/assist_request \
     /planning/stuck_detection_recall_signal
```

也可以按 issue 下载，但可能明显更大：

```bash
voy-bag download road.bag -i <issue_uid> \
  -T /planning/seed \
     /planning/planning_debug \
     /planning/remote_assist_model_debug \
     /planning/assist_request \
     /planning/stuck_detection_recall_signal
```

不要省略 `-T`。整 issue 下载可能达到几十 GB。

## 4. 先检查是否已有历史 EzSim

```bash
cd /home/didi/workspace/ra_tools
python3 scripts/ezsim_run.py --list | grep "ra_repro_${SCENARIO_ID}" || true
```

如果已有状态为 `Success` 的同 binary 结果，优先复用，产物位于：

```text
/home/didi/.voyager/ezsim/simulation/<sim_id>/output.bag
/home/didi/.voyager/ezsim/simulation/<sim_id>/events.log
```

## 5. 触发 EzSim

```bash
cd /home/didi/workspace/ra_tools
python3 scripts/ezsim_run.py "$SCENARIO_ID" \
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

先统计关键 topic 帧数：

```bash
python3 - "$WORK_DIR/road.bag" "$SIM_DIR/output.bag" <<'PY'
import sys
import rosbag

topics = [
    "/planning/seed",
    "/planning/planning_debug",
    "/planning/remote_assist_model_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]
for path in sys.argv[1:]:
    with rosbag.Bag(path) as bag:
        info = bag.get_type_and_topic_info().topics
        print(path)
        for topic in topics:
            print(f"  {topic}: {info[topic].message_count if topic in info else 0}")
PY
```

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
python3 08_batch_job_diff_analysis.py \
  --job-id <orion_job_id> \
  --limit 5 \
  --bag-dir "$WORK_DIR" \
  --output-dir "$WORK_DIR/batch_diff_outputs"
```

对已抽取的 npz 做 nearby lane 对齐：

```bash
python3 06_analyze_nearby_lane_alignment.py \
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
