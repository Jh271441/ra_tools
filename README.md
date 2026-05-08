# ra_tools

一些围绕 RA issue、scenario 和结果分析的 Python 脚本集合。

## 项目说明

这个仓库主要包含三类内容：

- `ra_api/`：对 issue、scenario 相关内部接口的简单封装
- `utils/`：一些通用的数据处理和分析脚本
- `stuck/`、`swag/`：按具体问题域拆分的脚本

从当前代码结构看，这个仓库更偏向“脚本工具箱”，而不是一个完整打包发布的 Python 包。

## 目录结构

```text
ra_tools/
├── issue_to_scenairo.py
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

可先手动安装：

```bash
pip install pandas requests
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

