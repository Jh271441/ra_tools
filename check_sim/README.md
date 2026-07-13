# check_sim

`check_sim` 是 road bag 与 EzSim bag 的 Scenario DNN 输入、输出对比工具。它作为
`ra_tools` 内的独立 Python 包维护，不依赖旧的 `check_sim_reproduction` 仓库。

## 目录结构

```text
check_sim/
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

01-07 是命令行入口。公共的 bag 解析、shape、tensor 转换和 ONNX 推理只在共享模块中
实现，避免编号脚本之间相互 import 或复制代码。

## 运行

从仓库根目录直接运行：

```bash
.venv/bin/python3 check_sim/01_check_nearby_frames.py --help
.venv/bin/python3 check_sim/06_analyze_nearby_lane_alignment.py --help
```

也支持包模式：

```bash
.venv/bin/python3 -m check_sim.06_analyze_nearby_lane_alignment --help
```

完整的 01-07 用法见 [`docs/check_sim_01_07_guide.md`](../docs/check_sim_01_07_guide.md)。

## 依赖边界

- 01-03、05 读取 bag 时才加载 `rosbag` 和 Voyager protobuf。
- 04、05、07 创建模型会话时才加载 `onnx` 和 `onnxruntime`。
- 06 只依赖 NPZ，可脱离 ROS/Voyager 环境运行。
- `VOYAGER_PROTO_PB` 可覆盖 protobuf Python bindings 的默认路径。

这种延迟加载保证未安装完整 Voyager runtime 的机器仍可查看命令帮助并运行纯 NPZ
分析。
