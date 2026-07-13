# 旧版路测 bag 下载工具

带机器硬编码路径的 Tempest 下载脚本。正式复现链路请统一使用：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py <scenario_id> --binary <binary_id>
```

兼容入口仍可通过：

```bash
.venv/bin/python3 scripts/download_road_bag.py ...
.venv/bin/python3 scripts/download_road_bag_cloud.py ...
```

- `download_road_bag.py`：本机 Ubuntu 22.04 + ICU shim
- `download_road_bag_cloud.py`：cloud_server 环境
- `icu60shim.cpp`：本机 ICU 60→70 桥接
