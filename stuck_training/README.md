# stuck_training

Stuck DNN 源数据准入、低速门控筛选与训练包装配脚本。

## 文件说明

| 文件 | 作用 |
|---|---|
| `low_speed_policy.py` | 源样本准入、低速门控帧筛选、红绿灯触发源排除、EOL 准入及 Manual 排队/让行负样本权重口径 |
| `freeze_source_metadata.py` | 联结冻结源标签、Manual 标注与 EOL 准入清单，生成可复现的源元数据 |
| `stage_low_speed.py` | 基于既有冻结训练代码装配低速门控 / 源数据训练 bundle |
| `verify_low_speed.py` | 在 CPU 上对装配后的训练 bundle 执行真实数据读取器与 temporal loss 预检 |
| `test_low_speed_policy.py` | 低速门控与源标签准入口径的回归单元测试 |

## 运行测试

```bash
python3 -m unittest stuck_training/test_low_speed_policy.py
```

## 相关入口

- Stuck 训练与仿真监控登记规范：[`../AGENTS.md`](../AGENTS.md)
- 模型导出、IFX 转换与发布：[`../model_release_pipeline/README.md`](../model_release_pipeline/README.md)
- 离线原生回放与 road/sim 对比：[`../check_sim/README.md`](../check_sim/README.md)、[`../check_sim/offline/README.md`](../check_sim/offline/README.md)
