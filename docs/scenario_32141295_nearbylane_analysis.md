# Scenario 32141295 Road/Sim Nearbylane 分析

## 1. 分析对象

| 项目 | 值 |
|---|---|
| scenario id | `32141295` |
| issue id | `cn32459463` |
| binary id | `1660677` |
| road bag | `/home/didi/ra_bags/scenario_32141295/road.bag` |
| sim bag | `/home/didi/ra_bags/scenario_32141295/sim.bag` |
| sim id | `016110cc-11d6-46fa-a335-8fbde7f51e23` |

目标是判断最新场景的 `nearby_lane` 特征是否存在内容或 tensor slot 排序问题，并导致
road/sim 推理不一致。

## 2. Bag 级结果

使用：

```bash
.venv/bin/python3 check_sim/compare_road_sim_bags.py \
  /home/didi/ra_bags/scenario_32141295/road.bag \
  /home/didi/ra_bags/scenario_32141295/sim.bag
```

结果：

| 指标 | Road | Sim |
|---|---:|---:|
| bag 时长 | 34.976s | 35.001s |
| topic 数 | 59 | 70 |
| `/planning/seed` | 348 | 329 |
| `/planning/planning_debug` | 348 | 329 |
| `/planning/remote_assist_model_debug` | 290 | 274 |
| `/planning/assist_request` | 1 | 1 |
| `/planning/stuck_detection_recall_signal` | 1 | 2 |

road 的 59 个 topic 全部存在于 sim。两侧最终都触发 RA，但触发时刻不同：

- road assist request：`1779961633078 ms`
- sim assist request：`1779961637987 ms`
- sim 比 road 晚约 `4908 ms`

因此“最终是否触发”一致，“触发过程和时机”不一致。

## 3. PlanningSeed 解析方式

Voyager 的 `proto_msg/PlanningSeed` 使用占位 md5。cloud_server 的系统 `rosbag` 虽然能遍历
消息，但自动生成的消息对象没有字段。分析脚本采用：

1. `rosbag.read_messages(raw=True)` 获取原始字节。
2. 跳过 4 字节 ROS 长度前缀。
3. 使用 Voyager 构建产物中的 `planning_seed_pb2.PlanningSeed` 解析 protobuf。

实现位于 `check_sim/planning_seed_reader.py`。

## 4. 模型执行 cycle 错位

以 road 触发时间为中心检查前后 20 帧，非空 TensorDict 帧如下。

### Road

| seed record time ms | previous inference time ms | scenario score |
|---:|---:|---:|
| 1779961631806 | 1779961631686 | 0.630371 |
| 1779961633078 | 1779961632979 | 0.516602 |
| 1779961634091 | 1779961633981 | 0.481689 |
| 1779961634514 | 1779961634382 | 0.000000 |

### Sim

| seed record time ms | previous inference time ms | scenario score |
|---:|---:|---:|
| 1779961631685 | 1779961631555 | 0.581055 |
| 1779961631806 | 1779961631656 | 0.587891 |
| 1779961633783 | 1779961633671 | 0.591309 |
| 1779961633899 | 1779961633755 | 0.594727 |

road/sim 模型输出不是稳定发生在相同 planning cycle。直接按 frame index 或固定 `offset=-1`
比较会选中空 TensorDict，或比较到不同 inference cycle。

## 5. 同一绝对时间比较

选择两侧均有 42 个 feature 的共同 seed record：

```text
1779961631806 ms, offset=0
```

其内部 inference timestamp 相差 30ms：

- road：`1779961631686 ms`，score `0.630371`
- sim：`1779961631656 ms`，score `0.587891`

使用 02/03 比较 TensorDict 后，显著差异主要来自：

- `old_dnn_features`：max abs diff `2049.0`
- agent group：geometry、heading、continuous、discrete、trajectory 和 valid mask 均有明显差异
- traffic light：continuous/discrete 有差异
- ego continuous/trajectory 有小幅差异

五个 nearby lane feature 的 max abs diff 全部为 `0`。

## 6. Nearbylane lane 级匹配

共同时间帧运行：

```bash
.venv/bin/python3 check_sim/06_analyze_nearby_lane_alignment.py \
  --road /home/didi/ra_bags/scenario_32141295/road_features_1779961631806.npz \
  --sim /home/didi/ra_bags/scenario_32141295/sim_features_1779961631806.npz \
  --show-mapping
```

结果：

```text
identity mean cost  : 0.0000
best-match mean cost: 0.0000
remapped lanes      : 0/90
max matched cost    : 0.0000
nonzero matched cost: 0/90
```

这表示 90 个 slot 在 road/sim 中逐槽完全一致，不存在内容差异，也不存在 lane 重排。

## 7. 触发相对帧补充比较

另外比较：

- road 触发附近有效帧：`1779961633078 ms`
- sim 后续最近有效帧：`1779961633783 ms`

这两个帧不是同一世界时间，只用于观察触发相对状态。06 的结果仍为：

```text
identity mean cost  : 0.0000
best-match mean cost: 0.0000
remapped lanes      : 0/90
max matched cost    : 0.0000
```

即使在触发相对帧上，nearby lane 也逐槽完全一致。其他 feature 则存在明显差异，最大的仍是
`old_dnn_features` 和 agent group。

## 8. 结论

针对 scenario `32141295`：

1. **没有发现 nearbylane bug。** 同一绝对时间和触发相对帧的五组 nearby lane tensor 都
   完全一致，90 个 lane slot 没有重排。
2. road/sim 的模型执行 cycle 和 RA 触发时机不一致，sim 最终 RA request 晚约 4.91 秒。
3. v49 复算的 `stuck_score` 相差 `-0.042403`，与 seed 记录值高度一致。07 显示
   `old_dnn_features` 单组替换贡献 `-0.035440`，解释约 84% 的分数差；agent/ego 是次要
   因素，nearby lane 贡献为 0。
4. 该结论与旧案例 `cn30851935` 不冲突。旧案例确实存在 nearby lane 集合相同但 slot
   重排；当前新场景没有复现该问题。

## 9. 模型敏感性实验

EzSim model cache 中存在本次下载的 ONNX：

```text
/home/didi/.cache/voyager/model_files/
planner.model-files_vectorized_scenario_remote_assist_model.onnx_78_e6fa832263f2a97aa870b13615dffefe
```

该模型经 ORT compatibility rewrite 后输出约 `0.722`，与 seed 记录的 IFX 历史输出不一致，
因此不能用它解释线上绝对分数。上传的 v49 compat 模型则高度复现 seed：

| 项目 | Road | Sim |
|---|---:|---:|
| seed 记录 score | 0.630371 | 0.587891 |
| v49 ONNX 复算 | 0.630462 | 0.588058 |

v49 feature replacement 的 `stuck_score` 结果：

| Feature group | mixed score | delta from road | 说明 |
|---|---:|---:|---|
| `old_dnn_features` | 0.595021 | -0.035440 | 解释约 84% 总分差 |
| ego | 0.625184 | -0.005278 | 次要贡献 |
| agent | 0.628881 | -0.001580 | group 总贡献较小，单特征有交互 |
| traffic light | 0.629669 | -0.000793 | 较小 |
| nearby lane | 0.630462 | 0.000000 | 无贡献 |

单特征中，除 `old_dnn_features` 外影响较大的包括：

- `agent_geometric`：`-0.017824`
- `agent_trajectory`：`-0.005851`
- `ego_continuous`：`-0.005279`
- `agent_heading`：`-0.005173`

单特征贡献不能直接相加，因为不同输入之间存在非线性交互。

## 10. 跨版本复核

v60/v61 不是 binary `1660677` 的正式复算模型，仅用于验证敏感性结论是否依赖 v49：

| 模型 | Road score | Sim score | 总差异 | Nearby lane delta |
|---|---:|---:|---:|---:|
| v49 | 0.630462 | 0.588058 | -0.042403 | 0.000000 |
| v60 | 0.083085 | 0.082982 | -0.000103 | 0.000000 |
| v61 | 0.324074 | 0.296353 | -0.027721 | 0.000000 |

三个模型的 nearby lane group 替换贡献均为 0，进一步支持当前场景与 nearbylane 无关。

07 命令：

```bash
.venv/bin/python3 check_sim/07_analyze_model_feature_sensitivity.py \
  --road /home/didi/ra_bags/scenario_32141295/road_features_1779961631806.npz \
  --sim /home/didi/ra_bags/scenario_32141295/sim_features_1779961631806.npz \
  --models /home/didi/ra_models/vectorized_scenario_remote_assist_model_v49.ort_compat.onnx \
  --intra-op-threads 4
```
