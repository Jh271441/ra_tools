# nearby_lane 特征导致推理不一致排查记录

整理日期：2026-07-10

## 1. 背景

这次排查的目标是确认 RA stuck 自触发模型在路测与仿真复现之间出现推理不一致时，`nearby_lane` 特征是否存在 bug。

用户最初提到的仓库路径是 `../check_sim`。本机实际存在的是：

- `/home/didi/workspace/check_sim_reproduction`

本文里的 `check_sim` 均指这个本地仓库。

RA stuck 触发链路上需要先区分两类问题：

- 模型输入/输出不一致：`/planning/seed` 中 `assistStuckModelOutput.TensorDict` 抽出来的特征不同，直接导致 DNN 分数不同。
- 触发链路不一致：模型输出后还会经过计数、FN 兜底、FP 抑制、仲裁，最终是否触发 RA 不能只看一个分数。

本次重点是第一类：模型输入特征里 `nearby_lane_*` 是否存在特征构造 bug。

## 2. 相关数据与仓库

### 2.1 check_sim 本地数据

路径：`/home/didi/workspace/check_sim_reproduction`

关键文件：

| 文件 | 作用 |
| --- | --- |
| `road_features_cn30851935.npz` | cn30851935 路测帧抽取后的模型输入 |
| `sim_features_cn30851935.npz` | cn30851935 仿真帧抽取后的模型输入 |
| `road_cn30851935.bag` | cn30851935 路测 bag |
| `sim_cn30851935.bag` | cn30851935 仿真 bag |
| `batch_diff_outputs/job_39687031_limit5_local_feature/summary.json` | 本地最新批量差异汇总 |
| `vectorized_scenario_remote_assist_model_v49.ort_compat.onnx` | 可用 ONNX Runtime 跑的 v49 模型 |
| `vectorized_scenario_remote_assist_model_v60.ort_compat.onnx` | 可用 ONNX Runtime 跑的 v60 模型 |
| `vectorized_scenario_remote_assist_model_v61.ort_compat.onnx` | 可用 ONNX Runtime 跑的 v61 模型 |

注意：`summary.json` 中最新 rank1 场景是 `cn29081785`，但它引用的 bag：

- `/home/didi/workspace/voyager/cn29081785.bag`
- `/home/didi/workspace/voyager/3968703100000003_0_0.bag`

当前本机不存在，所以不能直接对 `cn29081785` 复跑 bag 级分析。完整复算使用的是仓库里已有的 `cn30851935` npz。

### 2.2 Voyager 线上特征代码

关键实现文件：

- `/home/didi/workspace/voyager/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp`
- `/home/didi/workspace/voyager_gen4/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp`
- `/home/didi/workspace/voyager/onboard/planner/assist/feature_extraction/utils/dnn_features_utils.cpp`
- `/home/didi/workspace/voyager/onboard/pnc_map_service/joint_pnc_map_service.cpp`
- `/home/didi/workspace/voyager/onboard/pnc_map_service/pnc_map_service.cpp`
- `/home/didi/workspace/voyager/onboard/pnc_map_service/util/pnc_map_service_utility.cpp`

## 3. 本地环境

默认 `/usr/bin/python3` 没有分析依赖：

- `numpy` 缺失
- `rosbag` 缺失
- `onnxruntime` 缺失
- `onnx` 缺失

可用环境是：

```bash
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python ...
```

该环境具备：

- `numpy 2.0.1`
- `onnxruntime 1.19.2`
- `onnx 1.19.0`

但没有 `rosbag`，所以在当前 shell 环境下：

- 可以分析已抽好的 `.npz`
- 可以跑 ONNX 推理敏感性分析
- 不能重新从 bag 中抽新帧，除非切到有 `rosbag` 的环境

### 3.1 推荐运行位置：cloud_server

后续 bag 级分析建议统一在 `ssh cloud_server` 上执行，不再把本机作为主运行环境。

原因：

- EzSim 服务运行在 `cloud_server`，历史产物原生位于
  `/home/didi/.voyager/ezsim/simulation/<sim_id>/`。
- Orion/cloud sim bag 和路测 bag 都可以在服务器上用 `voy-bag download` 获取。
- 服务器补齐 voy-sdk 环境变量后，`rosbag`、`numpy`、`onnxruntime` 均可用。
- 本机 `check_sim_reproduction` 当前约 57 GB，主要空间都被 bag 占用；其中单个
  `road.bag` 约 32 GB。脚本代码和 npz/summary 本身很小。
- 本机分析环境缺 `rosbag`，会导致 bag 下载、读取和 npz 抽取被拆成两套环境。

推荐架构：

```text
GitHub check_sim_reproduction
          |
          v
cloud_server 工作目录
  |- voy-bag 下载 road/cloud-sim bag
  |- 直接读取 EzSim output.bag
  |- 抽取 TensorDict -> npz
  |- 特征 diff / nearby_lane 对齐 / ONNX 推理
  `- 生成 summary.json / summary.csv
          |
          v
本机只同步小体积 npz、summary 和最终文档
```

这里的“迁移”应当是远端重新 `git clone/pull` 代码并在远端运行，不建议把本机
57 GB 目录整体复制到服务器。bag 应在服务器按任务下载和管理，代码仍以 Git 仓库为唯一来源。

服务器当前检查结果（2026-07-10）：

- `/home/didi/workspace/check_sim_reproduction` 尚未部署。
- `/home/didi/workspace/voyager` 已存在。
- `~/.voyager/ezsim/simulation` 当前有 2 组历史仿真，约 13 GB。
- `/home/didi/ra_bags` 当前约 859 MB。
- `/volume` 总容量 7.0 TB，剩余约 754 GB，但使用率已经 90%，必须限制 bag topic 并设置清理策略。
- `cn29081785` 只有 triage 视觉 bag 缓存，没有本次需要的完整 road/sim RA bag；仍需用
  `voy-bag` 按 issue/task 下载。

服务器执行前需要补齐 voy-sdk 环境：

```bash
export LD_LIBRARY_PATH=/home/didi/.voyager/ezsim/binary/1665523/tmp/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/voy-sdk/lib/python3/dist-packages:$PYTHONPATH
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
```

验证结果：

```text
voy-bag     /home/didi/.local/bin/voy-bag
rosbag      OK
numpy       1.26.2
onnxruntime 1.13.1
```

注意：当前 `08_batch_job_diff_analysis.py` 下载 bag 时没有传 `-T` topic 白名单，可能拉取
几十 GB 的整 issue bag。迁移执行前应先把下载范围限制为至少 `/planning/seed`；如果还要分析
完整 RA 触发链路，再增加 `/planning/planning_debug`、`/planning/remote_assist_model_debug`、
`/planning/assist_request` 和 `/planning/stuck_detection_recall_signal`。

## 4. check_sim 脚本说明

### 4.1 `01_check_nearby_frames.py`

用途：查看指定时间戳附近，road/sim 两侧 `/planning/seed` 是否都有 `TensorDict`。

默认输入：

- `road_cn30851935.bag`
- `sim_cn30851935.bag`
- topic：`/planning/seed`
- 字段：`behaviorSeed.assistStuckSeed.assistStuckModelOutput.TensorDict`

运行方式：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 01_check_nearby_frames.py
```

当前环境缺 `rosbag` 时不能运行。

### 4.2 `02_analyze_numerical_diffs.py`

用途：从 road/sim bag 中取同一目标时间附近的帧，逐 feature 打印数值差异，适合初筛哪个 feature 差异最大。

运行方式：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 02_analyze_numerical_diffs.py
```

当前环境缺 `rosbag` 时不能运行。

### 4.3 `03_extract_features_to_npz.py`

用途：把指定帧的 `TensorDict` 抽成 `.npz`，方便脱离 bag 做模型推理和特征对齐。

默认输出：

- `road_features_cn30851935.npz`
- `sim_features_cn30851935.npz`

运行方式：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 03_extract_features_to_npz.py
```

当前环境缺 `rosbag` 时不能运行。仓库里已经有抽好的 npz，所以本次直接使用现有文件。

### 4.4 `04_model_inference_compare.py`

用途：对 road/sim `.npz` 分别跑 ONNX，比较模型输出。

默认模型路径指向 `../../utils/onnx/vectorized_scenario_remote_assist_model_v49.onnx`，脚本会尝试生成 `.ort_compat.onnx`。当前 `check_sim_reproduction` 下已有可运行的 compat 模型，建议优先用 `07_analyze_model_feature_sensitivity.py` 指定 compat 模型，避免脚本重写只读文件。

### 4.5 `06_analyze_nearby_lane_alignment.py`

用途：专门分析 `nearby_lane` 的 slot 是否对齐。

它会读取：

- `nearby_lane_geometric`
- `nearby_lane_continuous`
- `nearby_lane_discrete`
- `nearby_lane_valid_geometric`
- `nearby_lane_valid_history`

然后构造 lane signature，用几何、离散、连续、valid 信息做 road lane 到 sim lane 的匹配。这个脚本是本次定位的关键。

运行方式：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 06_analyze_nearby_lane_alignment.py \
  --road road_features_cn30851935.npz \
  --sim sim_features_cn30851935.npz \
  --show-mapping
```

关键输出：

```text
identity mean cost : 18.1497
best-match mean cost: 0.0000
remapped lanes      : 56/90
max matched cost    : 0.0000
nonzero matched cost: 0/90
exact match verdict : all lanes match exactly after reordering
```

解释：

- 如果按原始 slot 对齐，road/sim 差异很大。
- 如果允许重排，90 条 lane 全部能以 0 cost 完全匹配。
- 这说明 `nearby_lane` 内容本身不是算错，而是 road/sim 两侧进入 tensor 的 slot 顺序不同。

### 4.6 `07_analyze_model_feature_sensitivity.py`

用途：把 sim 的某组 feature 替换到 road 输入里，再跑模型，观察模型分数变化。用于判断哪个 feature group 对输出差异贡献最大。

运行方式：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 07_analyze_model_feature_sensitivity.py \
  --road road_features_cn30851935.npz \
  --sim sim_features_cn30851935.npz \
  --models vectorized_scenario_remote_assist_model_v49.ort_compat.onnx \
           vectorized_scenario_remote_assist_model_v60.ort_compat.onnx \
           vectorized_scenario_remote_assist_model_v61.ort_compat.onnx \
  --group-limit 8 \
  --feature-limit 12
```

v49 关键输出：

```text
Output: stuck_score
  road score : 0.597374
  sim  score : 0.224466
  total diff : -0.372908

Top group sensitivities:
nearby_lane  mixed_score=0.204164  delta_from_road=-0.393210
agent        mixed_score=0.591058  delta_from_road=-0.006316
```

解释：

- v49 的 road/sim 分数差异是 `-0.372908`。
- 只把 `nearby_lane` 从 sim 替换到 road 后，分数从 `0.597374` 变成 `0.204164`。
- 这几乎解释了全部推理差异。

v60 关键输出：

```text
Output: stuck_score
  road score : 0.146407
  sim  score : 0.160851
  total diff : +0.014444

Top group sensitivities:
nearby_lane  mixed_score=0.163258  delta_from_road=+0.016851
```

v61 关键输出：

```text
Output: stuck_score
  road score : 0.229023
  sim  score : 0.234652
  total diff : +0.005629

Top group sensitivities:
agent        mixed_score=0.238220  delta_from_road=+0.009197
nearby_lane  mixed_score=0.224554  delta_from_road=-0.004470
```

解释：

- v49 对 `nearby_lane` slot 顺序非常敏感。
- v60/v61 的总分差异小很多，但 `nearby_lane` 仍会影响输出。
- 不能因为 v60/v61 影响较小就认为特征没有 bug。特征排序不稳定本身仍然会造成线上/仿真不可复现。

### 4.7 `08_batch_job_diff_analysis.py`

用途：批量从仿真 job 查询结果，下载 sim/road bag，抽取 `/planning/seed` 中的模型输入，并比较特征差异。

默认 job：

```text
39687031
```

默认 topic 和字段：

```text
/planning/seed
behaviorSeed.assistStuckSeed.assistStuckModelOutput.TensorDict
```

常用命令：

```bash
cd /home/didi/workspace/check_sim_reproduction
python3 08_batch_job_diff_analysis.py \
  --job-id 39687031 \
  --limit 5 \
  --output-dir batch_diff_outputs/job_39687031_limit5_local_feature \
  --skip-download
```

如果要跑 ONNX 推理，需要加：

```bash
--enable-inference --model-path vectorized_scenario_remote_assist_model_v49.ort_compat.onnx
```

但当前默认环境中 `rosbag` 缺失，且 summary 里引用的 `/home/didi/workspace/voyager/*.bag` 当前不存在，所以本次没有直接复跑最新 rank1 bag。

本地最新 summary 中 rank1：

```json
{
  "issue_id": "cn29081785",
  "sim_task_id": 3968703100000003,
  "max_feature_name": "nearby_lane_geometric",
  "max_feature_abs_diff": 74.8391466140747,
  "road_frame_index": 1,
  "sim_frame_index": 149,
  "time_delta_s": 0.0
}
```

这说明最新批量场景里，最大特征差异已经指向 `nearby_lane_geometric`。

## 5. 本次排查过程

### 5.1 确认仓库和最新产物

最初检查 `../check_sim`，发现路径不存在。本机实际仓库是：

```bash
/home/didi/workspace/check_sim_reproduction
```

查看最新输出：

```bash
find ../check_sim_reproduction/batch_diff_outputs -maxdepth 3 -type f \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p %s\n' | sort -r | head
```

最新有效产物：

```text
batch_diff_outputs/job_39687031_limit5_local_feature/summary.json
batch_diff_outputs/job_39687031_limit5_local_feature/summary.csv
```

### 5.2 检查最新 summary

`summary.json` 显示 rank1 `cn29081785`：

- road/sim 时间戳完全对齐：`time_delta_s = 0.0`
- 最大特征差异：`nearby_lane_geometric`
- 最大差异：`74.8391466140747`

这一步只能说明 `nearby_lane_geometric` 差异最大，还不能判断是几何算错、坐标系错、还是 slot 顺序错。

### 5.3 用 cn30851935 npz 复算 nearby_lane 对齐

先看 raw diff：

```text
nearby_lane_geometric            max=51.856426 nonzero=2366
nearby_lane_continuous           max=2.007387  nonzero=112
nearby_lane_discrete             max=10.000000 nonzero=149
nearby_lane_valid_geometric      max=42.000000 nonzero=46
nearby_lane_valid_history        max=0.000000  nonzero=0
```

raw diff 很大，但这还只是按原始 slot 下标逐项相减。

再用 `06_analyze_nearby_lane_alignment.py` 做 lane-level matching：

```text
remapped_count=56/90
matched_max_cost=0
```

这一步是关键结论：

- road/sim 有相同的 lane 集合和相同的 lane 特征内容。
- 56 条 lane 的 slot 下标不同。
- 重排后所有 lane 完全匹配。

因此，`nearby_lane` 差异不是“lane 几何内容错”，而是“相同 lane 被放到了不同 tensor slot”。

### 5.4 用 ONNX 敏感性分析确认对推理输出的影响

用 `07_analyze_model_feature_sensitivity.py` 对 v49/v60/v61 做分组替换。

v49 结果最明显：

- road score：`0.597374`
- sim score：`0.224466`
- diff：`-0.372908`
- 替换 `nearby_lane` 后 mixed score：`0.204164`

这说明 v49 推理不一致主要由 `nearby_lane` 引起。

### 5.5 回查线上特征代码

`nearby_lane` 生成逻辑在：

```text
voyager/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp
voyager_gen4/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp
```

核心逻辑：

```cpp
std::vector<const pnc_map::Lane*> nearby_lane =
    world_model.joint_pnc_map_service()->GetNearLanesWithPose(...);
if (nearby_lane.size() <= kCapacityOfLanesOnCycle) {
  return nearby_lane;
}
...
std::sort(nearby_lane.begin(), nearby_lane.end(), ...distance...);
nearby_lane.resize(kCapacityOfLanesOnCycle);
return nearby_lane;
```

问题点：

- `kCapacityOfLanesOnCycle = 90`
- 候选 lane 数量 `<=90` 时直接返回 `GetNearLanesWithPose()` 的原始顺序
- 只有候选 lane 数量 `>90` 时才按距离排序

然后 `FetchInterestingLanes()` 直接把这个顺序写入 `interesting_ids`：

```cpp
for (const pnc_map::Lane* lane : *interesting_lanes) {
  interesting_ids->Add(lane->id());
}
```

`ConstructTensors()` 再按 `interesting_ids[n]` 写第 n 个 tensor slot：

```cpp
const int64_t ins_id = interesting_ids[n];
...
const int64_t nt_bias = (n * num_history + t);
```

也就是说，`interesting_ids` 顺序就是模型看到的 lane slot 顺序。

### 5.6 回查 `GetNearLanesWithPose()` 顺序来源

`GetNearLanesWithPose()` 内部会：

1. 调 `hdmap()->GetRoads(point, radius)` 拿附近 road。
2. 遍历 road 的 geo info。
3. 遍历 road -> section -> lane。
4. append lane。
5. 调 `GetFilteredNearLanesByHeading()` 过滤 heading。

`GetFilteredNearLanesByHeading()` 是按输入 lanes 顺序追加保留项，不做排序：

```cpp
for (const auto* lane : lanes) {
  ...
  candidate_near_lanes.push_back(lane);
}
return candidate_near_lanes;
```

所以 `GetNearLanesWithPose()` 没有给 nearby lane 提供稳定排序语义。road/sim 两边如果 map/road/section/lane 遍历顺序不同，或者动态地图/缓存顺序不同，就会得到相同集合但不同顺序。

## 6. 结论

本次排查确认：`nearby_lane` 特征存在会导致推理不一致的 bug。

更准确地说：

- 不是 `nearby_lane` 几何点、离散属性、连续属性本身计算错。
- 是 `nearby_lane` 的 lane slot 排序不稳定。
- road/sim 中相同 lane 集合被写入了不同 tensor slot。
- DNN 模型不是 permutation invariant 的，因此 slot 顺序变化会造成模型输出变化。
- 在 v49 上，这个问题足以解释主要推理分数差异。

本地证据：

- 最新批量 summary 的 rank1 `cn29081785` 最大差异字段为 `nearby_lane_geometric`，max diff `74.8391`。
- 可完整复算的 `cn30851935` 中，`nearby_lane` raw diff 很大，但重排后 `90/90` 完全匹配。
- `cn30851935` 有 `56/90` 个 nearby lane slot 被重排。
- v49 替换 `nearby_lane` 后，模型输出几乎从 road 分数跳到 sim 分数附近。

代码证据：

- `nearby_lane_features_tracker.cpp` 只有候选 lane 数量 `>90` 时才排序。
- 候选 lane 数量 `<=90` 时直接使用 `GetNearLanesWithPose()` 返回顺序。
- `GetNearLanesWithPose()` 没有稳定排序保证。
- `ConstructTensors()` 直接按 `interesting_ids` 顺序写 tensor slot。

## 7. 修复建议

建议在 `SearchClosestLanes()` 中无论候选 lane 数量是否超过 90，都先计算稳定 rank 并排序，再截断。

建议排序 key：

1. lane 到 ego pose 的距离
2. lane id 作为 tie-break

伪代码：

```cpp
std::unordered_map<int64_t, double> id_to_distance;
const math::geometry::Point2d pose_point(world_model.core().pose().x(),
                                         world_model.core().pose().y());
for (const pnc_map::Lane* lane : nearby_lane) {
  id_to_distance.emplace(
      lane->id(), math::geometry::Distance(pose_point, lane->border()));
}
std::sort(nearby_lane.begin(), nearby_lane.end(),
          [&id_to_distance](const pnc_map::Lane* a, const pnc_map::Lane* b) {
            const double dist_a = id_to_distance[a->id()];
            const double dist_b = id_to_distance[b->id()];
            if (std::abs(dist_a - dist_b) > 1e-6) {
              return dist_a < dist_b;
            }
            return a->id() < b->id();
          });
if (nearby_lane.size() > kCapacityOfLanesOnCycle) {
  nearby_lane.resize(kCapacityOfLanesOnCycle);
}
return nearby_lane;
```

需要同步修改：

- `voyager/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp`
- `voyager_gen4/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp`

修复后建议补充测试：

- 构造同一批 lane 的不同输入顺序，验证输出 `interesting_ids` 顺序一致。
- 候选数 `<90`、`=90`、`>90` 三种 case 都覆盖。
- 距离相同或近似相同的 case 验证 lane id tie-break。
- 跑 `cn30851935` 或同类场景，确认 raw `nearby_lane_*` diff 不再表现为纯 slot permutation。

## 8. 局限与待补充

本次没有完成的部分：

- 最新 rank1 `cn29081785` 的 road/sim bag 当前不在本机，无法复跑 bag 级抽取与 ONNX 推理。
- 当前可用 conda 环境没有 `rosbag`，不能直接执行 `01/02/03/08` 的 bag 读取流程。
- 结论中的完整数值复算来自 `cn30851935` 已抽取 npz。

但这不影响核心判断，因为：

- 最新 summary 已经指向 `nearby_lane_geometric` 是最大差异字段。
- `cn30851935` 证明了 `nearby_lane` 存在“内容一致但 slot 重排”的确定性问题。
- 代码实现能解释这种现象。

## 9. 复查命令汇总

查看最新 batch 输出：

```bash
cd /home/didi/workspace/ra_tools
find ../check_sim_reproduction/batch_diff_outputs -maxdepth 3 -type f \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p %s\n' | sort -r | head -80
```

查看 latest summary：

```bash
cd /home/didi/workspace/ra_tools
sed -n '1,220p' ../check_sim_reproduction/batch_diff_outputs/job_39687031_limit5_local_feature/summary.json
```

复跑 nearby lane slot 对齐：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 06_analyze_nearby_lane_alignment.py \
  --road road_features_cn30851935.npz \
  --sim sim_features_cn30851935.npz \
  --show-mapping
```

复跑模型 feature sensitivity：

```bash
cd /home/didi/workspace/check_sim_reproduction
/home/didi/software/miniconda3/bin/conda run -n assist_stuck python 07_analyze_model_feature_sensitivity.py \
  --road road_features_cn30851935.npz \
  --sim sim_features_cn30851935.npz \
  --models vectorized_scenario_remote_assist_model_v49.ort_compat.onnx \
           vectorized_scenario_remote_assist_model_v60.ort_compat.onnx \
           vectorized_scenario_remote_assist_model_v61.ort_compat.onnx \
  --group-limit 8 \
  --feature-limit 12
```

查看 nearby lane 线上实现：

```bash
cd /home/didi/workspace/ra_tools
nl -ba ../voyager/onboard/planner/assist/feature_extraction/utils/nearby_lane_features_tracker.cpp | sed -n '29,154p'
nl -ba ../voyager/onboard/planner/assist/feature_extraction/utils/dnn_features_utils.cpp | sed -n '249,270p'
nl -ba ../voyager/onboard/pnc_map_service/util/pnc_map_service_utility.cpp | sed -n '2480,2548p'
```
