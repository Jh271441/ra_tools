# ra_tools

一些围绕 RA issue、scenario 和结果分析的 Python 脚本集合。

## 项目说明

这个仓库主要包含三类内容：

- `ra_api/`：对 issue、scenario 相关内部接口的简单封装
- `utils/`：一些通用的数据处理和分析脚本
- `stuck/`、`swag/`：按具体问题域拆分的脚本
- `model_release_pipeline/`：scenario dnn 模型导出、IFX 转换和 Voyager handoff 工具
- `check_sim/`：scenario 路测 bag 下载、EzSim 复现和 road/sim 模型差异分析
- `auto_triage_bot/`：DChat Auto Triage 只读问答 Bot（看板上下文 + 内部大模型）

从当前代码结构看，这个仓库更偏向“脚本工具箱”，而不是一个完整打包发布的 Python 包。

## 目录结构

```text
ra_tools/
├── ares_playwright/            # Ares Studio 登录态 / 截图
├── auto_triage/                # triage JSONL 特征分析
├── auto_triage_bot/            # DChat 事件、看板知识和 LLM 回复服务
├── check_sim/                  # scenario 复现与 road/sim 分析完整链路
│   ├── bag/ analysis/ repro/
│   └── repro/legacy/           # 旧版按时间段下载路测 bag
├── issue_to_scenairo.py
├── model_release_pipeline/
├── ra_api/                     # issue/scenario API + export_issues
├── ra_sim_repro_dashboard/     # 仿真复现看板（含 stats 脚本）
├── scripts/                    # 兼容入口（实现已迁到 check_sim 等）
├── swag/
├── utils/
└── vlm/                        # VLM prompt 与 multimodal 客户端
```

## 环境要求

- Python 3.9+
- 常用依赖：
  - `pandas`
  - `requests`
  - `PyYAML`

可先手动安装：

```bash
pip install pandas requests PyYAML
```

## 快速开始

1. 克隆仓库并进入目录

```bash
cd ra_tools
```

2. 按需安装依赖

```bash
pip install pandas requests
```

3. 直接运行目标脚本，例如：

```bash
python issue_to_scenairo.py
python -m model_release_pipeline.cli print-config
```

## 核心模块

### `auto_triage_bot/`

独立于看板运行的只读 DChat 助手。它从 RA Triage Workbench 的 loopback API 获取不可变 GT、指定 Model Run 和该 Run 的 Review，上下文受限后调用内部模型网关，并通过 DChat BotUser 回复。启动配置、回调验签和开放平台操作见 [`auto_triage_bot/README.md`](auto_triage_bot/README.md)。

### `ra_api/issue_api.py`

封装 issue 查询相关能力，包含：

- 按条件分页查询 issue
- 按 issue id 批量查询
- 基于内部接口的请求签名与请求发送

### `ra_api/scenario_api.py`

封装 scenario 相关能力，包含增删改查能力

### `issue_to_scenairo.py`

一个从 RA issue 拉取数据并尝试自动创建 scenario 的示例脚本，当前逻辑包括：

- 查询指定条件的 issue
- 从事件流中提取触发时间
- 按 trip 时间片创建 scenario

### `model_release_pipeline/`

封装 scenario dnn 发布链路的本机入口，包含选模、远端导出 ONNX、触发 IFX 转换，以及生成 Voyager/Kunpeng handoff 文件。

本机无法直接访问 `/nfs/...` 实验目录时，可以通过 `--remote luban_1_card` 让工具 ssh 到 Luban 读取实验元信息：

```bash
python -m model_release_pipeline.cli inspect --remote luban_1_card --experiment /nfs/.../experiment
python -m model_release_pipeline.cli export --remote luban_1_card --experiment /nfs/.../experiment --epoch 5 --dry-run
```

默认远端 Python 是 `/home/luban/miniconda3/bin/conda run -n scen_dnn python`，也可以用 `--remote-python` 临时覆盖。
Web 页面里的 Luban remote 输入框支持一键切换，候选列表来自配置里的 `luban.host_aliases`；默认当前使用 `luban.host_alias: luban_1_card`。

如果已手动确定 checkpoint，`export`/`release` 传 `--epoch` 会跳过自动选模，直接推进 ONNX 导出、IFX 转换和 Voyager handoff。

---

## check_sim — Scenario 复现与 bag 工具

不依赖 voyager 仓库或本地 ROS 安装，纯 pip 环境即可使用。

### 前置依赖（只需装一次）

```bash
cd ra_tools
python3 -m venv .venv
.venv/bin/pip install rosbags
```

**proto 定义来源（二选一，优先用方式 A）：**

**方式 A（推荐）**：直接引用 voyager Docker 编译产物，路径 `~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb/`。
这是 `//protobuf_python:protos_python` 的输出，包含所有 onboard proto 的完整 `_pb2.py` 文件。
如果该路径不存在，进 Docker 编译一次即可：

```bash
docker exec -it $CONTAINER_NAME_GEN4 zsh -c \
  "cd ~/workspace/voyager && bazel build --config=local //protobuf_python:protos_python"
# 编译产物自动写入宿主机可见的 bazel-build/bin/（cache 目录共享）
```

**方式 B（无 Docker/voyager 时的兜底）**：用 `check_sim/bag/planning_stub.proto`（手写的最小 stub，只含 `is_opened` 字段路径）：

```bash
.venv/bin/pip install grpcio-tools google-protobuf
.venv/bin/python3 -m grpc_tools.protoc \
    -I check_sim/bag --python_out=check_sim/bag check_sim/bag/planning_stub.proto
```

`read_bag.py` 启动时自动检测方式 A 的路径，找不到时降级到方式 B。

### 1. 下载路测 bag（在 cloud_server 上执行）

`check_sim/repro/legacy/download_road_bag_cloud.py` 通过内网 Tempest SDK 按 trip_id + 时间段下载 `.bag` 文件
（`scripts/download_road_bag_cloud.py` 为兼容入口）。
**需在 cloud_server（172.16.145.60:12017）上运行**，该机器已预装 `voy-tempest` 和 `voy-vbag`。

```bash
# 上传脚本到 cloud_server（首次）
scp check_sim/repro/legacy/download_road_bag_cloud.py cloud_server:/tmp/

# SSH 进去执行
ssh cloud_server "python3 /tmp/download_road_bag_cloud.py \
    --trip  10385_20260525_070411 \
    --start 1779665020000 \
    --end   1779665070000 \
    --output /tmp/my_road.bag"

# 把 bag 拉回本机
scp cloud_server:/tmp/my_road.bag /tmp/
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--trip` | trip_id，格式如 `10385_20260525_070411` |
| `--start` / `--end` | 时间范围，毫秒时间戳 |
| `--output` | 输出 `.bag` 路径 |
| `--topics` | 可选，指定 topic 列表（默认下载 planning_debug / assist_request / stuck_detection_recall_signal） |

### 2. 本机读取 bag 并解析 proto 字段

`check_sim/bag/read_bag.py` 纯 Python 读取 `.bag` 文件，解析 `planning_debug` 中的 proto 字段，**无需 ROS/voyager 环境**。

首次运行时会自动编译 `planning_stub.proto` → `planning_stub_pb2.py`（之后跳过）。

```bash
# 默认：打印所有 planning_debug 消息的 is_opened 字段
.venv/bin/python3 check_sim/bag/read_bag.py /tmp/my_road.bag

# 只看 is_opened=True 的行
.venv/bin/python3 check_sim/bag/read_bag.py /tmp/my_road.bag | grep True

# 显示所有 topic 的所有消息
.venv/bin/python3 check_sim/bag/read_bag.py /tmp/my_road.bag --show-all

# 只看指定 topic
.venv/bin/python3 check_sim/bag/read_bag.py /tmp/my_road.bag \
    --topic /planning/assist_request /planning/stuck_detection_recall_signal
```

**方式 A 的优势**：完整 pb2 覆盖所有字段，proto 有改动时重新 `bazel build` 即可，无需维护 stub。

**方式 B 的局限**：`planning_stub.proto` 只保留到 `is_opened` 的字段路径（field numbers 21→14→5→1）。field number 被修改时对照 `onboard/planner/planner_protos/` 更新 stub 数字即可。
