# check_sim

`check_sim` 是从 Trail scenario 复现到 Scenario DNN 输入、输出分析的完整工具链。它作为
`ra_tools` 内的独立 Python 包维护，不依赖旧的 `check_sim_reproduction` 仓库。

## 目录结构

```text
check_sim/
├── repro/                    # Trail、下载与 EzSim 执行
│   ├── scenario_repro.py
│   ├── run_pose_ab.py
│   ├── ezsim.py
│   ├── get_scenario_ids.py
│   ├── setup_cloud_python.sh
│   └── default_road_topics.txt
├── bag/                      # bag、events 和可视化检查
│   ├── compare_road_sim_bags.py
│   ├── compare_ra_debug.py
│   ├── read_bag.py
│   ├── read_forcing_trajectory.py
│   ├── bag_bev_visualizer.py
│   └── planning_stub.proto
└── analysis/                 # TensorDict、ONNX 和 01-07 分析
    ├── 01_check_nearby_frames.py
    ├── ...
    ├── 07_analyze_model_feature_sensitivity.py
    ├── features.py
    ├── tensor_io.py
    ├── planning_seed_reader.py
    └── model_io.py
```

完整链路是：

```text
scenario_id
  -> repro/scenario_repro.py 下载 road bag 并启动 EzSim
  -> bag/compare_road_sim_bags.py 检查最终触发和时间对齐
  -> analysis/01-03 定位并导出模型输入
  -> analysis/04-07 对比推理、lane 排序和 feature 敏感性
```

公共的 EzSim 调用、bag 解析、shape、tensor 转换和 ONNX 推理只在包内共享模块中实现，
避免编号脚本之间相互 import 或复制代码。`scripts/` 下保留同名兼容入口，但不再承载实现。

相关但已不在 `scripts/` 承载实现的内容：

- `repro/experiments/_launch_*.py`：写死 trip/build 的一次性 EzSim 实验，不属于通用工作流。
- `repro/legacy/download_road_bag*.py`：带旧机器路径的下载兼容工具；正式
  链路统一使用 `repro/scenario_repro.py`。`scripts/download_road_bag*.py` 仅保留兼容入口。
- `auto_triage/extract_bag_features.py`：处理 triage JSONL，不读取 road/sim bag。

## 运行

从仓库根目录直接运行：

```bash
.venv/bin/python3 check_sim/analysis/01_check_nearby_frames.py --help
.venv/bin/python3 check_sim/analysis/06_analyze_nearby_lane_alignment.py --help
```

从 scenario 开始完整复现：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py <scenario_id> --binary <binary_id>
.venv/bin/python3 check_sim/bag/compare_road_sim_bags.py \
  /home/didi/ra_bags/scenario_<scenario_id>/road.bag \
  /home/didi/ra_bags/scenario_<scenario_id>/sim.bag
.venv/bin/python3 check_sim/bag/compare_ra_debug.py \
  /home/didi/ra_bags/scenario_<scenario_id>/road.bag \
  /home/didi/ra_bags/scenario_<scenario_id>/sim.bag
```

`compare_ra_debug.py` 默认从同目录 `metadata.json` 的 scenario 正式起点开始比较，排除
EzSim warmup；无 metadata 时默认排除前 5000 ms。

也支持包模式：

```bash
.venv/bin/python3 -m check_sim.analysis.06_analyze_nearby_lane_alignment --help
```

对 ego pose 与 smart agent 做两组隔离实验：

```bash
.venv/bin/python3 check_sim/repro/run_pose_ab.py \
  <scenario_id> --binary <binary_id>
```

结果分别写入 `scenario_<id>/experiments/replay_road_pose/` 和
`scenario_<id>/experiments/disable_smart_agent/`，不会覆盖默认仿真。

## 批量复现性归因

对 road 已触发、base sim 未触发的 case 清单，可逐案下载最小 road bag，并使用
清单中的 base binary 和标准 EzSim 参数重跑：

```bash
.venv/bin/python3 check_sim/batch/analyze_repro_cases.py \
  check_sim/batch/data/base_miss_50.csv \
  --output-root /home/didi/ra_batch_39367009
```

脚本从 Trail `trip_segment.startTimestamp` 开始比较，不重复裁掉 warmup。它会持续
写入每个 case 的 `summary.json`、全量 `summary.json` 和 `report.md`，单 case 失败
不会中断整批。默认删除脚本下载的临时 road bag，但保留 EzSim 原始仿真目录和
`sim_id`；使用 `--keep-bags` 可保留临时 bag，使用 `--scenario <id>` 或 `--limit N`
可做小批量验证。

根因分类覆盖模型未输出/未召回、FP 抑制、voluntary unstuck 门控、路测
`StuckSignal` 掉零触发，以及 bag 已有请求但 DPE 指标未识别等情况。

完整的 01-07 用法见 [`docs/check_sim_01_07_guide.md`](../docs/check_sim_01_07_guide.md)。

## 依赖边界

- 01-03、05 读取 bag 时才加载 `rosbag` 和 Voyager protobuf。
- `repro/scenario_repro.py` 通过同子包的 `ezsim.py` 使用 Trail/EzSim，不依赖 `scripts/`。
- `bag/compare_road_sim_bags.py` 优先使用 pip 的 `rosbags`，否则回退到 voy-sdk `rosbag`。
- `bag/compare_ra_debug.py` 使用仓库内最小 proto，不要求完整 Voyager protobuf 构建产物。
- `bag/read_bag.py` 依赖 `rosbags`；`bag/bag_bev_visualizer.py` 额外依赖 `numpy` 和
  `matplotlib`，且只在实际绘图时加载。
- 04、05、07 创建模型会话时才加载 `onnx` 和 `onnxruntime`。
- 06 只依赖 NPZ，可脱离 ROS/Voyager 环境运行。
- `VOYAGER_PROTO_PB` 可覆盖 protobuf Python bindings 的默认路径。

这种延迟加载保证未安装完整 Voyager runtime 的机器仍可查看命令帮助并运行纯 NPZ
分析。
