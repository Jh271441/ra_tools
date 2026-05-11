# ra_tools

一些围绕 RA issue、scenario 和结果分析的 Python 脚本集合。

## 项目说明

这个仓库主要包含三类内容：

- `ra_api/`：对 issue、scenario 相关内部接口的简单封装
- `utils/`：一些通用的数据处理和分析脚本
- `stuck/`、`swag/`：按具体问题域拆分的脚本
- `model_release_pipeline/`：scenario dnn 模型导出、IFX 转换和 Voyager handoff 工具

从当前代码结构看，这个仓库更偏向“脚本工具箱”，而不是一个完整打包发布的 Python 包。

## 目录结构

```text
ra_tools/
├── issue_to_scenairo.py
├── model_release_pipeline/
├── ra_api/
│   ├── issue_api.py
│   ├── scenario_api.py
│   └── utils.py
├── stuck/
├── swag/
└── utils/
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

本机无法直接访问 `/nfs/...` 实验目录时，可以通过 `--remote luban_2_card` 让工具 ssh 到 Luban 读取实验元信息：

```bash
python -m model_release_pipeline.cli inspect --remote luban_2_card --experiment /nfs/.../experiment
python -m model_release_pipeline.cli export --remote luban_2_card --experiment /nfs/.../experiment --epoch 5 --dry-run
```

默认远端 Python 是 `/home/luban/miniconda3/bin/conda run -n scen_dnn python`，也可以用 `--remote-python` 临时覆盖。

如果已手动确定 checkpoint，`export`/`release` 传 `--epoch` 会跳过自动选模，直接推进 ONNX 导出、IFX 转换和 Voyager handoff。
