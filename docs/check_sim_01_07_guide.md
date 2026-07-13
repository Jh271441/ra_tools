# Check Sim 01-07 使用说明

本文说明 `ra_tools/scripts/check_sim/` 下 01-07 脚本的用途、输入输出、运行命令和结果解释。
这些脚本用于比较同一场景的路测 `road.bag` 与 EzSim `sim.bag`，重点定位
`/planning/seed` 中模型 TensorDict 是否不一致，以及 `nearby_lane` 是否导致推理差异。

## 1. 脚本关系

01-07 并不是必须全部串行执行。推荐的数据流是：

```text
road.bag + sim.bag
        |
        +-- 01 定位目标帧和检查 TensorDict 是否存在
        |
        +-- 02 快速查看单帧各 feature 的数值差异
        |
        +-- 03 导出 road_features.npz / sim_features.npz
                    |
                    +-- 04 比较 road/sim 模型输出
                    +-- 06 判断 nearby_lane 是否只是槽位顺序不同
                    +-- 07 逐组替换 feature，量化谁导致模型输出变化

05 = 01-04 的单帧集成版本，并可选跑全 bag 推理；不是 04 后必须执行的步骤。
```

| 编号 | 脚本 | 主要用途 | 主要产物 |
|---|---|---|---|
| 01 | `01_check_nearby_frames.py` | 确认目标时间附近有哪些 seed 帧，TensorDict 是否存在 | 终端表格 |
| 02 | `02_analyze_numerical_diffs.py` | 快速找出差异大于 0.01 的 feature | 终端差异表 |
| 03 | `03_extract_features_to_npz.py` | 将一帧 TensorDict 转成 NumPy | road/sim NPZ |
| 04 | `04_model_inference_compare.py` | 用同一 ONNX 分别推理 road/sim NPZ | 模型输出差异 |
| 05 | `05_full_analysis_suite.py` | 单帧提取、差异、推理、NPZ 一体化 | `*_frame_neg1.npz` |
| 06 | `06_analyze_nearby_lane_alignment.py` | lane 级匹配，检查 tensor slot 重排 | lane 映射和 cost |
| 07 | `07_analyze_model_feature_sensitivity.py` | 混合替换 feature，做模型敏感性归因 | group/feature 贡献表 |

## 2. cloud_server 环境

```bash
ssh cloud_server

cd /home/didi/workspace/ra_tools

export BINARY_ID=1660677
export LD_LIBRARY_PATH=/home/didi/.voyager/ezsim/binary/$BINARY_ID/tmp/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/voy-sdk/lib/python3/dist-packages:$PYTHONPATH
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
export VOYAGER_PROTO_PB=/home/didi/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb

export PY=/home/didi/workspace/ra_tools/.venv/bin/python3
export CHECK_SIM=/home/didi/workspace/ra_tools/scripts/check_sim
export WORK_DIR=/home/didi/ra_bags/scenario_32141295
export ROAD_BAG=$WORK_DIR/road.bag
export SIM_BAG=$WORK_DIR/sim.bag
```

01-03、06 需要 `numpy`；05 还需要 `tqdm` 和 `onnxruntime`；04、07 需要 `onnx`、
`onnxruntime`。当前 cloud_server 的 `.venv` 已有 `numpy`、`tqdm`，但可能没有 ONNX 依赖。
使用 uv 安装到现有 venv：

```bash
cd /home/didi/workspace/ra_tools
uv pip install --python .venv/bin/python3 onnx onnxruntime
```

01、02、03、05 不使用系统 `rosbag` 自动生成的消息类，因为 Voyager 的
`proto_msg/PlanningSeed` 使用占位 md5，自动生成对象可能没有任何字段。迁移后的代码统一
通过 `raw=True` 读取字节、跳过 4 字节 ROS 长度前缀，再用 `planning_seed_pb2` 解析。

04、05、07 还需要实际 ONNX 模型。模型通常不进 Git，应单独放到服务器，例如：

```bash
export MODEL=/home/didi/ra_models/vectorized_scenario_remote_assist_model_v49.ort_compat.onnx
test -f "$MODEL"
```

模型必须和待复现 binary/实验版本对应。使用不匹配的模型只能用于敏感性实验，不能证明原
binary 的线上推理结果。

## 3. 选择目标时间戳

所有单帧脚本使用毫秒时间戳。比较特征一致性时，应给 road 和 sim 使用同一个绝对时间，
不要按第 N 帧硬对齐，因为仿真可能少帧或启动时间不同。

先运行 bag 概览：

```bash
$PY scripts/compare_road_sim_bags.py "$ROAD_BAG" "$SIM_BAG"
```

scenario `32141295` 当前记录到：

- road `assist_request`：`1779961633078 ms`
- sim `assist_request`：`1779961637987 ms`
- 两边触发时刻相差约 `4908 ms`

如果目标是比较“路测触发时相同世界状态下的输入”，使用 road 触发时间：

```bash
export TARGET_MS=1779961633078
```

如果目标是分别分析各自触发帧，应分别运行两次并使用各自触发时间。不要把两个不同绝对
时间的 feature 差异直接归因成仿真不一致。

## 4. 01：检查目标附近 seed 帧

### 含义

在 `/planning/seed` 中找到最接近 `--ts` 的消息，并展示其前后若干帧的时间戳和
TensorDict 大小。该步骤用于确认：

- road/sim 都包含 `/planning/seed`。
- 目标时间附近确实有模型输入。
- 选中的帧没有落在 bag 边界或空 TensorDict 区间。

### 命令

```bash
$PY "$CHECK_SIM/01_check_nearby_frames.py" \
  --road "$ROAD_BAG" \
  --sim "$SIM_BAG" \
  --ts "$TARGET_MS" \
  --count 2
```

### 结果解释

- `目标帧`：各 bag 内距离目标时间最近的帧。
- `-1/+1 帧`：各自最近帧的前后帧，不保证 road/sim 的相同 offset 就是同一绝对时间。
- `Size(N)`：TensorDict 包含 N 个 feature。
- `Empty/N/A`：该帧没有有效 TensorDict，不应继续用于模型差异结论。

如果目标附近所有帧都是 `Empty (0)`，说明该 binary/配置没有把 TensorDict dump 到 seed，
02-07 无法从这对 bag 恢复模型输入。此时应确认模型 debug dump 配置或换用包含 TensorDict
的 bag，不能用全零 tensor 代替。

## 5. 02：单帧 feature 数值差异

### 含义

读取目标附近同一 offset 的 TensorDict，逐 feature 比较最大绝对差。默认使用最近帧的
前一帧 `--offset -1`，与模型输出滞后一帧的历史分析约定一致。

### 命令

```bash
$PY "$CHECK_SIM/02_analyze_numerical_diffs.py" \
  --road "$ROAD_BAG" \
  --sim "$SIM_BAG" \
  --ts "$TARGET_MS" \
  --offset -1
```

### 结果解释

- 只打印最大绝对差大于 `0.01` 的 feature。
- `MISSING`：一侧缺少该 feature。
- `Size Mismatch`：两侧 tensor 元素数量不同，不能逐元素直接比较。
- 大的 `nearby_lane_geometric` 差异不一定代表地图内容不同，也可能只是 90 个 lane slot
  顺序不同，必须继续运行 06。

## 6. 03：导出 TensorDict 为 NPZ

### 含义

把目标帧 TensorDict 按脚本内的固定 shape 转成 NumPy，并导出 road/sim NPZ。06、07 都以
这两个文件为输入。

### 命令

```bash
$PY "$CHECK_SIM/03_extract_features_to_npz.py" \
  --road "$ROAD_BAG" \
  --sim "$SIM_BAG" \
  --ts "$TARGET_MS" \
  --offset -1 \
  --road-output "$WORK_DIR/road_features.npz" \
  --sim-output "$WORK_DIR/sim_features.npz"
```

检查产物：

```bash
ls -lh "$WORK_DIR/road_features.npz" "$WORK_DIR/sim_features.npz"
```

### 注意

- shape 是按当前 Scenario DNN 输入定义写死的，例如 nearby lane 为 90 个 slot。
- feature 缺失或元素数量与 shape 不一致时脚本会直接失败，不生成伪造的补零结果。
- NPZ 只代表一个 frame，不包含整段 bag 时序。

## 7. 04：比较 ONNX 推理输出

### 含义

用同一个 ONNX 模型分别推理 road/sim NPZ，比较每个输出的最大绝对差。脚本会尝试处理旧
ONNX Runtime 不支持的 scalar LayerNormalization，并在当前工作目录生成
`.ort_compat.onnx`。

### 命令

```bash
cd "$WORK_DIR"

$PY "$CHECK_SIM/04_model_inference_compare.py" \
  --model "$MODEL" \
  --road "$WORK_DIR/road_features.npz" \
  --sim "$WORK_DIR/sim_features.npz"
```

### 结果解释

- `Max Abs Diff`：该模型输出 tensor 的最大绝对差。
- `stuck_score` 等输出差异说明输入差异已传播到模型结果。
- 04 只能说明“整体输入不同导致输出不同”，不能判断具体由哪个 feature 导致；归因使用 07。

## 8. 05：单帧一体化分析

### 含义

05 将以下动作组合在一次执行中：

1. 找目标时间最近帧的前一帧。
2. 打印差异大于 0.01 的 feature。
3. 对 road/sim 运行 ONNX 推理。
4. 导出 road/sim NPZ。

它可以替代 01-04 的快速流程，但调试透明度不如分步执行。

### 单帧命令

```bash
cd "$WORK_DIR"

$PY "$CHECK_SIM/05_full_analysis_suite.py" \
  --road "$ROAD_BAG" \
  --sim "$SIM_BAG" \
  --ts "$TARGET_MS" \
  --offset -1 \
  --model "$MODEL" \
  --road-output "$WORK_DIR/road_frame.npz" \
  --sim-output "$WORK_DIR/sim_frame.npz"
```

### 全 bag 模式

```bash
$PY "$CHECK_SIM/05_full_analysis_suite.py" \
  --road "$ROAD_BAG" \
  --sim "$SIM_BAG" \
  --ts "$TARGET_MS" \
  --offset -1 \
  --model "$MODEL" \
  --road-output "$WORK_DIR/road_frame.npz" \
  --sim-output "$WORK_DIR/sim_frame.npz" \
  --full
```

`--full` 当前按 frame index 比较整段输出，没有按时间戳重新对齐。road/sim 存在启动丢帧
时，后续 frame index 会整体错位。因此它只适合快速浏览，不能作为严格的全时序一致性结论。

## 9. 06：nearby lane 槽位对齐

### 含义

对 road/sim 的 90 个 nearby lane slot 建立几何和属性 cost matrix，再进行一对一贪心匹配。
它用于区分两类问题：

1. 同一 slot 内容真的不同。
2. lane 集合相同，但写入 tensor 的 slot 顺序不同。

### 命令

```bash
$PY "$CHECK_SIM/06_analyze_nearby_lane_alignment.py" \
  --road "$WORK_DIR/road_features.npz" \
  --sim "$WORK_DIR/sim_features.npz" \
  --detail-count 8 \
  --show-mapping
```

### 核心指标

- `identity mean cost`：road slot i 与 sim slot i 直接比较的平均 cost。
- `best-match mean cost`：允许重新排列 slot 后的平均 cost。
- `remapped lanes`：最佳匹配中 slot index 发生变化的 lane 数量。
- `max matched cost`：重排后最差匹配 cost。

典型判断：

```text
identity mean cost  > 0
best-match mean cost = 0
remapped lanes       很多
max matched cost     = 0
```

这说明两侧 lane 内容完全相同，只是 tensor slot 顺序不同。由于模型直接消费固定位置的 slot，
这种顺序差异仍然会导致推理不一致。

如果 `best-match mean cost` 和 `max matched cost` 仍明显大于 0，则除了排序外，还存在 lane
集合、几何采样或属性内容差异。

## 10. 07：模型 feature 敏感性归因

### 含义

以 road 全量 feature 为基线，每次只把一个 feature group 或单个 feature 替换为 sim 值，
然后重新推理。这样可以量化哪组输入真正推动模型输出从 road 变化到 sim。

### 命令

```bash
$PY "$CHECK_SIM/07_analyze_model_feature_sensitivity.py" \
  --road "$WORK_DIR/road_features.npz" \
  --sim "$WORK_DIR/sim_features.npz" \
  --models \
    /home/didi/ra_models/vectorized_scenario_remote_assist_model_v49.ort_compat.onnx \
    /home/didi/ra_models/vectorized_scenario_remote_assist_model_v60.ort_compat.onnx \
    /home/didi/ra_models/vectorized_scenario_remote_assist_model_v61.ort_compat.onnx \
  --group-limit 8 \
  --feature-limit 12
```

只分析一个模型时，`--models` 后只传一个路径。

### 结果解释

- `road score`：全 road feature 的输出。
- `sim score`：全 sim feature 的输出。
- `mixed_score`：road 基线上仅替换当前 group/feature 后的输出。
- `delta_from_road`：这次替换让输出相对 road 改变多少。
- `remain_to_sim`：替换后距离完整 sim 输出还差多少。

如果 `nearby_lane` 的 `mixed_score` 已接近 `sim score`，且 `remain_to_sim` 接近 0，说明
nearby lane 可以解释大部分推理差异。再结合 06 的“重排后完全一致”，即可形成完整证据链：

```text
lane 集合相同
-> tensor slot 顺序不同
-> 单独替换 nearby_lane 几乎复现 sim score
-> nearby_lane 排序不稳定导致推理不一致
```

## 11. 推荐执行组合

### 只判断最终 RA 是否复现

运行 `compare_road_sim_bags.py` 并检查 `assist_request`，无需运行 01-07。

### 快速检查模型输入和输出

```text
01 -> 02 -> 05
```

### 严格排查 nearbylane

```text
01 -> 03 -> 06 -> 07
```

04 可用于补充确认完整 road/sim 输入的模型输出差异。

## 12. 结论边界

- 01-07 分析的是 `/planning/seed` 中已经 dump 的模型输入，不覆盖 FP 规则、FN 强召回、状态机
  和最终仲裁的全部逻辑。
- 两侧 `assist_request` 数量一致，只能说明最终都触发；触发时刻和触发原因仍可能不同。
- 单帧差异必须建立在同一绝对时间或明确的触发相对时间上。
- 06 证明 lane 重排，07 证明模型对该重排敏感；两者同时成立，才足以把推理差异归因到
  nearby lane slot 排序。
- 判断完整 RA 触发链路还需结合 `/planning/planning_debug`、
  `/planning/remote_assist_model_debug`、`assist_request` 和 `events.log`。
