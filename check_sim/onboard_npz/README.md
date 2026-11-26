# Offline Onboard Stuck NPZ 推理与 10Hz 路测复刻引擎 (`check_sim.onboard_npz`)

无需运行 `data_sim` / EzSim / Orion 在线仿真，直接在离线增强型 `.npz` 上原生调用 Voy-SDK `libifx.so` 并按 10Hz 逐周期复刻 Voyager Onboard 实车路测的 Stuck ScenarioNet 推理、队列生命周期、FP/FN 规则仲裁及外层会话门控。

---

## 1. 核心原理

1. **零预处理张量契约**：实车 `RemoteAssistModelVNode` 中 `AssistDNNFeatureExtractor::TensorDict()` 生成的 `map<string, RATensor>` 原样同时送入 `AssistStuckEstimator::InferWithTensorDict()` 与调试消息落盘（`<= 20261009` 位于 `/planning/seed` 的 `AssistStuckModelOutput.field 4`，`>= 20261016` 位于 `/planning/remote_assist_model_debug` 的 `AssistStuckFeatureDebug.field 8.1`），中间无任何额外归一化、裁剪或缩放。
2. **轻量 5-Topic 实车 Bag 完整承载 10Hz 规则与状态真值**：仅需拉取实车路测 Bag 的 5 个轻量规划 Topic（单场景临时 Bag 仅几十至百余 MB，无需相机/点云），即可从 `/planning/remote_assist_debug`（`EgoStuckDebug`）、`/planning/seed`、`/planner/state`、`/planning/assist_request` 中完整还原当周版本 C++ 算出的逐周期 `fp_reasons`、`fn_reasons`、`entry_gate_status`、`already_in_assist_status`、`scheduler_session_blocked` 与初始队列状态。
3. **即下即删零残留治理**：流式导出器在 `finally` 块中立即删除临时 `.bag`，仅保留约 `6–10 MB/case` 的压缩 `.npz` 与 `.EXPORT.json` 回执，`.staging/` 全程保持零残留。

---

## 2. 模块结构与云端数据集落盘路径

### 代码结构（`ra_tools/check_sim/onboard_npz/`）

```text
check_sim/onboard_npz/
├── __init__.py               # 公共导出 API
├── __main__.py               # python3 -m check_sim.onboard_npz 入口
├── schema.py                 # 实车 C++ 枚举、remote_assist.conf 默认参数与 NPZ Schema 常量
├── bag_exporter.py           # 纯 Python ROSBAG V2.0 + Protobuf wire 解析器（兼容 <=1009 与 >=1016 双协议）
├── model_runner.py           # 零预处理模型运行器（.ifxmodel 原生桥接 / .onnx / recorded）
├── native/
│   └── ifx_native_bridge.cpp # 直连 /opt/voy-sdk/lib/libifx.so 的 C++17 ctypes 桥接层（首次运行自动编译缓存）
├── detector_replay.py        # Layer 1（裁剪 NPZ）+ Layer 2（10Hz 完整状态机与反事实门控）回放器
├── batch_export_1030.py      # Release 1030 冻结场景集多进程流式导出器
├── diff_report_1030.py       # Release 1030 Base vs Feature 成对四分群（TE7）评测与 SQL 独立校验
├── historical_shuyi_eval.py  # 通用多版本流式导出与数易看板（288969/6276081）6 层口径对账引擎
├── cli.py                    # 统一命令行入口
└── test_onboard_npz.py       # 端到端回归单测（Layer 1/2、bz2 Bag 往返、反事实门控、1009 旧协议、数易口径）
```

### 已就绪云端增强型路测 NPZ 数据集（`cloud_server`）

| 版本 | 云端 NPZ 目录 | 场景数 | 大小 | 说明 |
| --- | --- | ---: | ---: | --- |
| `gen4-release-20261009` | `/volume/home/datasets/onboard_road_npz_1009_v1/npz/` | `1,967` | `13.5 GB` | 含旧版 `/planning/seed` 内嵌 49 路 `TensorDict` |
| `gen4-release-20261016` | `/volume/home/datasets/onboard_road_npz_1016_v1/npz/` | `2,018` | `14.1 GB` | 100% 覆盖业务有效样本 |
| `gen4-release-20261023` | `/volume/home/datasets/onboard_road_npz_1023_v1/npz/` | `1,873` | `13.6 GB` | 100% 覆盖业务有效样本 |
| `gen4-release-20261030` | `/volume/home/datasets/onboard_road_npz_1030_v1/npz/` | `1,567` | `11.4 GB` | 含冻结 `1,561` 评测集 + `6` 条增量样本 |
| `gen4-release-20261106` | `/volume/home/datasets/onboard_road_npz_1106_v1/npz/` | `1,704` | `12.0 GB` | 100% 覆盖业务有效样本 |
| `gen4-release-20261113` | `/volume/home/datasets/onboard_road_npz_1113_v1/npz/` | `1,831` | `13.6 GB` | 覆盖已归档 `89.96%` 有效样本 |

---

## 3. 回放模式与统计窗口选择指南

| 模式 / 视图 | `mode` 参数 | 适用目标 | 行为定义 |
| --- | --- | --- | --- |
| **模型替换对比 / 对齐 Orion 仿真（默认推荐）** | `onboard_full` | 评估新 `.ifxmodel` 替换基线模型的业务准召与成对 Diff | **方案 B 反事实会话门控**：在候选新模型自身尚未发出请求且自车物理静止（`entry_gate == 0`）期间，解除路测旧模型提前触发遗留的 `ALREADY_IN_ASSIST` 屏蔽（在 `Release 1030` 上与 Orion 仿真 `Job 50509481` 误差仅 `0.12%` P / `0.55%` R，`FP=92`、`TN=539` 完全相等） |
| **历史实车复刻 / 对账数易看板** | `onboard_strict_road`（配合 `strict_road_causal` 视图） | 1:1 复现当年当周线上实车指标、对账数易看板 `288969 / 6276081` | 严格沿用实车录制 `ALREADY_IN_ASSIST` 状态；对 `ra_type=3`（人工触发）样本要求请求发生在 `<= ra_start_timestamp`（人工接管前）才计为自触发抢占，消除 30s 仿真在人工接管后多等 10s 导致的 `+5%` 召回虚高（`1009`–`1113` 逐案复现率 `98.54%–99.42%`） |
| **仅解除浅层建联屏蔽** | `onboard_light_counterfactual` | 区分浅层建联与 Waypoint/倒车执行态消融 | 仅在候选模型未触发前屏蔽 `ALREADY_IN_LIGHT_ASSIST`，保留 `WAYPOINT / REVERSING` 抑制 |
| **纯模型 + 10Hz 静止窗** | `model_only` | 剥离非模型 FP/FN 规则，单看模型自身队列触发能力 | 关闭非模型 FP/FN 规则与自主脱困门控，保留 10Hz 静止准入、异步帧到达时序与 `AssistStuckEstimator` 连续 3 帧队列判定 |
| **裁剪集快速评测** | `cropped_model_only`（自动识别） | 评测无 10Hz 周期数组的旧版裁剪 NPZ（如 `native6035`） | 零预处理前向 + `AssistStuckEstimator` 队列判定（`12000ms` 过期、`10` 帧上限、`1500ms` 新鲜度） |

---

## 4. 常用 CLI 命令速查

> 在 `cloud_server`（含 `/opt/voy-sdk/lib/libifx.so`）上建议在 `/volume/home/workspace/ra_tools` 下直接用 `/usr/bin/python3` 执行。

### 4.1 在冻结 `Release 1030` 上秒级评测新 `.ifxmodel` 与基线成对 Diff（最常用）
```bash
python3 -m check_sim.onboard_npz eval-1030 \
  --npz-dir /volume/home/datasets/onboard_road_npz_1030_v1/npz \
  --out-dir /volume/home/workspace/ra_tools/reports/onboard_npz_1030_<exp_tag> \
  --base-model /volume/home/.cache/voyager/model_files/planner.model-files_vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel_89_6a15846abf8e0ea2375d4dd1a812061d \
  --feature-model /path/to/candidate_x86.ifxmodel \
  --workers 24
```
*24 核约 `100 秒` 跑完 `1,561` 场景，自动生成四分群（`all_business` / `traffic_EOL` / `non_traffic_business` / `NPZ_business_common`）SQL 校验后的 `SUMMARY.json`、`REPORT.md`、`per_case_outcomes.jsonl` 与 `changed_cases_base_vs_feature.csv`。*

### 4.2 接入新每周 Release（先 5 包自检，再全量流式导出与数易对账）
```bash
# Step 1: 抽 5 个样本流式导出并执行 10Hz 逐周期对齐防呆自检（约 10 秒）
python3 -m check_sim.onboard_npz export-population \
  --out-root /volume/home/datasets/onboard_road_npz_1120_v1 \
  --population-jsonl /path/to/gen4-release-20261120/population.jsonl \
  --release-tag 1120_smoke --workers 4 --limit 5 --min-free-gb 200

python3 -m check_sim.onboard_npz verify-parity \
  /volume/home/datasets/onboard_road_npz_1120_v1/npz --model recorded

# Step 2: 确认 unstuck_status_matches >= 99.5% 且 tensor_dict_frames > 0 后，全量流式导出（自动跳过已导出）
python3 -m check_sim.onboard_npz export-population \
  --out-root /volume/home/datasets/onboard_road_npz_1120_v1 \
  --population-jsonl /path/to/gen4-release-20261120/population.jsonl \
  --release-tag 1120 --workers 24 --min-free-gb 200

# Step 3: 运行单版本或多版本数易看板对账套件
python3 -m check_sim.onboard_npz eval-shuyi-suite \
  --config-json /path/to/shuyi_suite_config.json \
  --out-dir /volume/home/workspace/ra_tools/reports/onboard_npz_shuyi_<tag> \
  --workers 24
```

### 4.3 单场景/目录推理、多模型横评与单 Bag 导出
```bash
# 单场景 Bag（本地文件或 scenario_id）导出为增强型路测 NPZ
python3 -m check_sim.onboard_npz export-bag --scenario-id cn37543011 -o /tmp/cn37543011.npz

# 单场景或目录推理
python3 -m check_sim.onboard_npz infer /tmp/cn37543011.npz --model /path/to/model.ifxmodel --mode onboard_full

# 多模型 × 多模式批量横评
python3 -m check_sim.onboard_npz batch-eval /volume/home/datasets/onboard_road_npz_1030_v1/npz \
  --model q2_v89=/path/to/v89.ifxmodel \
  --model cand_v122=/path/to/v122.ifxmodel \
  --modes onboard_full,model_only \
  --json-out /tmp/eval.json --md-out /tmp/eval.md
```

---

## 5. C++ 版本演进与适用边界

1. **新每周线上 Release 路测数据（如 `1120`、`1127`）**：底层特征提取与各 `FP/FN` 子规则已由当周实车 C++ 二进制执行并写入路测 Bag，`bag_exporter.py` 动态遍历全部 `TensorDict` key 导出，**通常无需修改任何代码**（用 `verify-parity --limit 5` 即可 10 秒确认；仅当未来 C++ 改动 Protobuf 字段号或修改顶层 `reasoner_arbitrator.cpp` / `assist_stuck_estimator.cpp` 队列公式时，`verify-parity` 会精确定位差异周期，按 diff 同步几行 `schema.py` / `detector_replay.py` 即可）。
2. **固定老数据集（如 `1030`）测试未上车的 C++ 改动**：
   - **纯换 `.ifxmodel` / `.onnx`（只要所需输入张量在已 dump 的 49 路 `TensorDict` 内）或改阈值/队列/开关现有枚举**：**100% 免仿真、免重导 NPZ**。
   - **修改底层几何规则 C++（如 `queuing_scene_reasoner.cpp`）或新增第 50 路老 Bag 未录过的 `TensorDict` 特征**：老路测 Bag 中不含重算底层几何规则所需的全量感知 Topic，需先用新 C++ 跑一次仿真生成新 Sim Bag，再用 `export-bag --source-kind simulation` 导出新 C++ 底座 NPZ；此后在该新底座上迭代模型即可再次完全脱离仿真。

---

## 6. 回归测试

```bash
PYTHONPATH=/Users/didi/workspace/ra_tools pytest -q check_sim/onboard_npz/test_onboard_npz.py
```
