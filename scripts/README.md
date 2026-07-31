# scripts/ — 兼容入口与少量独立工具

本目录以历史命令路径的薄包装为主（转发到正式模块）；少量与 RA/Studio 运维相关的独立脚本也可放在这里。

## 兼容入口

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

新业务代码请优先放正式模块，或 `python -m check_sim...`。

## 独立工具

### `merge_studio_layout.py` — 把 Planning Layout 更新并入 RA Layout

把 **Planning** Studio layout 里的新 tab / Node Playground 节点合并进 **RA** layout（如 `RA_stuck_swag`），方向固定为：

| 角色 | 含义 |
|------|------|
| `--base` | RA layout（默认视图、active tab、3D 勾选状态） |
| `--donor` | Planning layout（只贡献新内容） |
| `--output` | 合并结果 |

规则摘要：

1. 保留 RA 顶层 layout、分栏比例、全部 `activeTabIdx`。
2. 保留 RA 已有 tab 与 panel 配置；**不覆盖**同名 tab 内容。
3. 只**追加** Planning 里 RA 没有的 tab 标题（不产生 `xxx (Planning)` 双份）。
4. 补齐新 tab 引用到的 Planning-only `configById`。
5. 合并 Planning-only `userNodes`（Node Playground）。
6. Voyager3D `checkedKeys` **保持 RA**（新 playground 节点默认不勾选）。
7. Voyager3D `expandedKeys` 并入 playground 相关 key，便于在 topic tree 里搜到。
8. 不拷贝 Planning-only 的 Voyager3D `subscriptions` / `querySnippets`（避免连带勾选）。
9. `globalVariables` / `topics` 等只做缺失 key 的加法合并。

示例：

```bash
python3 scripts/merge_studio_layout.py \
  --base  "/path/to/RA_stuck_swag.json" \
  --donor "/path/to/Planning Layout.json" \
  --output "/path/to/RA_stuck_swag_with_planning.json"
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--report PATH` | 文本报告路径（默认 `<output>.report.txt`） |
| `--v3d-panel-id` | 3D panel id（默认 `Voyager3DPanel!2olm9lp`） |
| `--compact` | 写出无缩进 JSON |

成功时 exit code `0` 且报告末尾 `OVERALL_OK: True`；校验失败（layout/active/勾选被改写等）exit code `1`。
