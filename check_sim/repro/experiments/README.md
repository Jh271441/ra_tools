# check_sim 一次性 EzSim 实验

写死 trip / issue / binary 的临时实验脚本，不属于通用复现工作流。

正式复现请用：

```bash
.venv/bin/python3 check_sim/repro/scenario_repro.py <scenario_id> --binary <binary_id>
.venv/bin/python3 -m check_sim.repro.ezsim <scenario_id> --binary <binary_id> --wait
```

这些 `_launch_*.py` 依赖 `check_sim.repro.ezsim`，从仓库根目录执行：

```bash
.venv/bin/python3 check_sim/repro/experiments/_launch_ab.py
```
