# check_sim

`check_sim` 是从 Trail scenario 复现到 Scenario DNN 输入、输出分析的完整工具链。它作为
`ra_tools` 内的独立 Python 包维护，不依赖旧的 `check_sim_reproduction` 仓库。

## 目录结构

```text
check_sim/
├── scenario_repro.py        # 下载 road bag、启动 EzSim、归档产物
├── ezsim.py                 # Trail 查询和 EzSim client
├── compare_road_sim_bags.py # bag topic、帧数和时间戳对齐概览
├── get_scenario_ids.py      # 从 Orion job 获取批量 scenario id
├── read_bag.py              # 通用 bag/proto 信号检查
├── read_forcing_trajectory.py # events.log forcing recall 轨迹
├── bag_bev_visualizer.py    # road/sim bag BEV 帧导出
├── setup_cloud_python.sh    # cloud_server uv/venv 环境检查
├── default_road_topics.txt  # 首次下载时的默认 sim topic 快照
├── 01_check_nearby_frames.py
├── 02_analyze_numerical_diffs.py
├── 03_extract_features_to_npz.py
├── 04_model_inference_compare.py
├── 05_full_analysis_suite.py
├── 06_analyze_nearby_lane_alignment.py
├── 07_analyze_model_feature_sensitivity.py
├── features.py              # Scenario DNN feature schema 和分组
├── tensor_io.py             # TensorDict/NPZ 转换
├── planning_seed_reader.py  # PlanningSeed bag 读取
└── model_io.py              # ONNX Runtime 会话和推理
```

完整链路是：

```text
scenario_id
  -> scenario_repro.py 下载 road bag 并启动 EzSim
  -> compare_road_sim_bags.py 检查最终触发和时间对齐
  -> 01-03 定位并导出模型输入
  -> 04-07 对比推理、lane 排序和 feature 敏感性
```

公共的 EzSim 调用、bag 解析、shape、tensor 转换和 ONNX 推理只在包内共享模块中实现，
避免编号脚本之间相互 import 或复制代码。`scripts/` 下保留同名兼容入口，但不再承载实现。

以下脚本有意留在 `scripts/`：

- `_launch_*.py`：写死 trip/build 的一次性 EzSim 实验，不属于通用工作流。
- `download_road_bag.py`、`download_road_bag_cloud.py`：带旧机器路径的下载兼容工具；正式
  链路统一使用 `scenario_repro.py`。
- `extract_bag_features.py`：处理 triage JSONL，不读取 road/sim bag。

## 运行

从仓库根目录直接运行：

```bash
.venv/bin/python3 check_sim/01_check_nearby_frames.py --help
.venv/bin/python3 check_sim/06_analyze_nearby_lane_alignment.py --help
```

从 scenario 开始完整复现：

```bash
.venv/bin/python3 check_sim/scenario_repro.py <scenario_id> --binary <binary_id>
.venv/bin/python3 check_sim/compare_road_sim_bags.py \
  /home/didi/ra_bags/scenario_<scenario_id>/road.bag \
  /home/didi/ra_bags/scenario_<scenario_id>/sim.bag
```

也支持包模式：

```bash
.venv/bin/python3 -m check_sim.06_analyze_nearby_lane_alignment --help
```

完整的 01-07 用法见 [`docs/check_sim_01_07_guide.md`](../docs/check_sim_01_07_guide.md)。

## 依赖边界

- 01-03、05 读取 bag 时才加载 `rosbag` 和 Voyager protobuf。
- `scenario_repro.py` 通过 `ezsim.py` 使用 Trail/EzSim，不依赖 `scripts/`。
- `compare_road_sim_bags.py` 优先使用 pip 的 `rosbags`，否则回退到 voy-sdk `rosbag`。
- `read_bag.py` 依赖 `rosbags`；`bag_bev_visualizer.py` 额外依赖 `numpy` 和
  `matplotlib`，且只在实际绘图时加载。
- 04、05、07 创建模型会话时才加载 `onnx` 和 `onnxruntime`。
- 06 只依赖 NPZ，可脱离 ROS/Voyager 环境运行。
- `VOYAGER_PROTO_PB` 可覆盖 protobuf Python bindings 的默认路径。

这种延迟加载保证未安装完整 Voyager runtime 的机器仍可查看命令帮助并运行纯 NPZ
分析。
