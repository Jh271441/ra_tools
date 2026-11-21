# ra_tools

围绕 Voyager RA（Remote Assist）的 **模型训练与发布、离线与线上仿真复现、标注复核平台、算力监控与运维工具** 的主工具仓。

各子模块独立维护依赖与运行方式，仓库不提供统一的 Python 包安装入口。项目级协作规范（Luban Monitor 实验登记、x86 制品版本、Workbench 分页/下拉/移动端/中英文约定）见 [`AGENTS.md`](AGENTS.md)。

---

## 按主线选择入口

### 1. Stuck DNN 训练、离线回放与模型发布

| 模块 | 职责 | 文档 |
|---|---|---|
| `stuck_training/` | Stuck DNN 源数据准入、低速门控帧筛选、训练包装配与 CPU 预检 | [`stuck_training/README.md`](stuck_training/README.md) |
| `check_sim/` | Trail scenario 路测 bag 下载、EzSim 复现与 road/sim 模型输入输出分析 | [`check_sim/README.md`](check_sim/README.md) |
| `check_sim/offline/` | 离线原生回放（NPZ / state / 逐周期输入）与三例 smoke 验收 | [`check_sim/offline/README.md`](check_sim/offline/README.md) |
| `model_release_pipeline/` | Scenario DNN 选模、Luban 远端 ONNX 导出、IFX 转换与 Voyager handoff | [`model_release_pipeline/README.md`](model_release_pipeline/README.md) |

### 2. RA 标注、复核与问答平台

| 模块 | 职责 | 文档 |
|---|---|---|
| `ra_triage_dashboard/` | RA Triage Workbench（`/manual`）：Issue 复核、不可变 Runs 对比、意图标注与 Batch | [`ra_triage_dashboard/README.md`](ra_triage_dashboard/README.md) |
| `auto_triage_bot/` | DChat Auto Triage 只读问答 Bot（对接 Workbench loopback API 与内部模型网关） | [`auto_triage_bot/README.md`](auto_triage_bot/README.md) |
| `auto_triage/` | Triage JSONL 特征提取与离线分析脚本 | — |
| `vlm/` | VLM Prompt 与多模态客户端工具 | — |

> 说明：PIPO / RO VLM 的正式训练与生产代码位于独立仓库 `pipo_vlm`、`ro_vlm`（经 GitHub 同步至 Luban OFS 主生产仓），不放在本仓。

### 3. 周度 Release 仿真复现看板

| 模块 | 职责 | 文档 |
|---|---|---|
| `ra_sim_repro_dashboard/` | 仿真复现看板（`/sim`）、周度 Release 统计与调度脚本 | [`ra_sim_repro_dashboard/README.md`](ra_sim_repro_dashboard/README.md) |
| `ops/sim_deploy/` | `/sim` 独立原生部署、数据库备份恢复、迁移与周报调度 | [`ops/sim_deploy/README.md`](ops/sim_deploy/README.md) |

### 4. Luban / AXE 资源监控与服务运维

| 模块 | 职责 | 文档 |
|---|---|---|
| `ops/luban_monitor_macos/` | Luban Monitor 原生 macOS 菜单栏 App、TensorBoard 入口与采集运维（后台在 `outputs/luban_resource_monitor/`） | [`ops/luban_monitor_macos/README.md`](ops/luban_monitor_macos/README.md) |
| `ops/portal/` | RA Tools 聚合首页（`/manual/`、`/sim/overview` 同源转发） | [`ops/portal/README.md`](ops/portal/README.md) |
| `ops/gateway/`、`ops/cpa/` | 网关路由与 CPA 运维配置 | [`ops/gateway/README.md`](ops/gateway/README.md)、[`ops/cpa/README.md`](ops/cpa/README.md) |

### 5. 公共 API、SWAG 与可视化工具

| 模块 | 职责 | 文档 |
|---|---|---|
| `ra_api/` | 内部 Issue / Scenario 查询与增删改查接口封装（含 `export_issues`） | — |
| `ares_playwright/` | Ares Studio 登录态（`storage_state`）与截图工具 | [`ares_playwright/README.md`](ares_playwright/README.md) |
| `swag/`、`swag_triage_reversed/` | SWAG / waypoint-assist 触发与逆向分析脚本 | — |
| `utils/`、`scripts/` | 通用数据处理工具与 `check_sim` 兼容入口 | [`scripts/README.md`](scripts/README.md) |

---

## 目录结构与产物边界

```text
ra_tools/
├── AGENTS.md                   # 项目协作规范（监控登记、制品版本、UI/i18n 约定）
├── stuck_training/             # Stuck DNN 低速门控与源数据准入
├── check_sim/                  # scenario 复现、road/sim 对比与 offline/ 原生回放
├── model_release_pipeline/     # ONNX 导出、IFX 转换与发布 handoff
├── ra_triage_dashboard/        # RA Triage Workbench (/manual)
├── ra_sim_repro_dashboard/     # 仿真复现看板 (/sim)
├── auto_triage_bot/            # DChat 只读问答 Bot
├── auto_triage/                # triage JSONL 分析
├── ra_api/                     # Issue / Scenario 内部 API 封装
├── ares_playwright/            # Ares Studio 登录态与截图
├── swag/ & swag_triage_reversed/
├── vlm/ & utils/ & scripts/
├── ops/                        # luban_monitor_macos / sim_deploy / portal / gateway / cpa
├── docs/                       # 跨模块专题指南（如 check_sim 01-07 手册）
├── tests/                      # 跨模块与回归测试
├── outputs/                    # 运行时产物（含 luban_resource_monitor/ 后台源码与 runtime）
└── reports/                    # 实验回执、仿真对账与审计报告（高频增长，勿与源码混写）
```

### 边界约定

- **代码与报告分离**：核心逻辑放入对应子模块；实验回执、临时汇总统一写入 `reports/<topic_date>/`（或 OFS 实验目录），不在仓库根目录堆积一次性脚本或临时包。
- **运行数据外置**：看板数据库、媒体缓存、凭据与秘钥保持在代码仓外（`0600` 权限，禁止提交）。
- **根目录历史脚本**：`issue_to_scenairo.py`、`compare_releases.py`、`sweep_all_orders.py`、`sweep_priority.py`、`test_disable_r5.py` 及 `NOTES.md`、`自触发模型仿真复现性现状.md` 为早期独立脚本/记录，新功能统一按模块归档。

---

## 快速参考

常用通用依赖（Python 3.9+）：

```bash
pip install pandas requests PyYAML
```

常用单模块入口示例：

```bash
# 1. 模型发布配置检查与远端实验查看
python -m model_release_pipeline.cli print-config
python -m model_release_pipeline.cli inspect --remote luban_1_card --experiment /nfs/.../experiment

# 2. Stuck 低速门控单元测试
python3 -m unittest stuck_training/test_low_speed_policy.py

# 3. Scenario 复现与 bag 解析（详细见 check_sim/README.md）
.venv/bin/python3 check_sim/repro/scenario_repro.py <scenario_id> --binary <binary_id>
.venv/bin/python3 check_sim/bag/read_bag.py /tmp/my_road.bag
```
