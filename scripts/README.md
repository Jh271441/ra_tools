# scripts/ — 兼容入口

本目录**不再承载实现**，只保留历史命令路径的薄包装，转发到正式模块。

| 兼容入口 | 实现位置 |
|----------|----------|
| `ezsim_run.py` | `check_sim/repro/ezsim.py` |
| `scenario_repro.py` | `check_sim/repro/scenario_repro.py` |
| `get_scenario_ids.py` | `check_sim/repro/get_scenario_ids.py` |
| `setup_cloud_python.sh` | `check_sim/repro/setup_cloud_python.sh` |
| `read_bag.py` / `read_forcing_trajectory.py` | `check_sim/bag/` |
| `compare_road_sim_bags.py` / `bag_bev_visualizer.py` | `check_sim/bag/` |
| `download_road_bag.py` / `download_road_bag_cloud.py` | `check_sim/repro/legacy/` |

已迁出（无 scripts 入口）：

| 原路径 | 新路径 |
|--------|--------|
| `playwright_test.py` | 删除 → 使用 `ares_playwright/` |
| `export_issues.py` | `ra_api/export_issues.py` |
| `q2_model_master_stats.py` | `ra_sim_repro_dashboard/scripts/` |
| `multimodal_api_client.py` | `vlm/multimodal_api_client.py` |
| `extract_bag_features.py` | `auto_triage/extract_bag_features.py` |
| `_launch_*.py` | `check_sim/repro/experiments/` |

新代码请直接调用实现路径或 `python -m check_sim...`。
