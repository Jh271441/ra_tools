# CR 6657869 独立 RA 回放 A/B canary 结果

日期：2026-09-01

## 结论

CR 6657869 的新开关在真实 Orion Level-4 仿真中已经生效：feature 从第 3 个 planning seed（index 2）开始保留并演进仿真自产的 RA 状态，而 control 继续被路测 bag 中的 RA seed/state 覆盖。

在本次已知可触发正例 scenario `29433817` 上，control 和 feature 均只触发一次，且 AssistRequest 时间戳完全相同。因此本轮证明了：

- 修复改变了目标 RA 状态路径，不是空开关；
- 修复没有破坏该已能复现正例的触发结果；
- 单个 canary 不能证明总体仿真复现率已经提升，仍需用旧代码漏触发样本做小批量 A/B。

## 实验身份

| 项目 | 值 |
|---|---:|
| CR | 6657869 |
| Commit | `170c8f05bc4dcbc33ad69cbf55bad978e0ca0fcc` |
| Orion binary | 1782885 |
| Orion job | 45393519 |
| Scenario | 29433817 |
| Control task | 4539351900000000 |
| Feature task | 4539351900000001 |

两路使用相同 binary、scenario、runtime、Level-4 recovery 和 DPE 配置；feature 仅额外增加 `--planning_enable_sim_assist_stuck_independent_replay`。缓存关闭，输出 bag 强制保留。

## Orion 结果

| 指标 | Control | Feature |
|---|---:|---:|
| 状态 | Done with warnings | Done with warnings |
| DPE `assist_channel_triggered` | 2.0 | 2.0 |
| 是否触发 | 是 | 是 |
| AssistRequest 数量 | 1 | 1 |
| AssistRequest 时间戳（ns） | 1777008104183093253 | 1777008104183093253 |
| simulator cache hit | false | false |
| inference log | 1 | 1 |
| DPE output | 1 | 1 |
| output bag | 1 | 1 |
| failed evaluation | 0 | 0 |
| 仿真耗时（s） | 345.508 | 505.615 |

两路 warning 都是关闭 task reuse cache 后的 `task_reuse_cache_key_build_miss`，不是仿真失败。

## Bag / protobuf 证据

- `planning_debug`：两路各 208 帧，时间戳序列完全一致，payload 从 index 1 开始不同。
- `planning_seed`：两路各 208 帧，时间戳序列完全一致；`assist_stuck_seed` 有 206 帧不同，首次差异为 index 2；`assist_request_scheduler_seed` 208 帧均相同。
- 首次 RA seed 差异全部位于 `ego_stuck_feature`。该帧的 `end_idx_of_features` 为 control `1`、feature `2`，说明 feature 沿仿真帧连续推进，control 使用了恢复状态。
- 触发前最后一帧为 seed index 130。差异覆盖 `ego_stuck_feature`、`assist_stuck_model_output`、`ignoring_construction_zones` 和 `forcing_recall`；其中 `forcing_recall.accumulated_cycle/ego_blocked_cycles` 为 control `22/22`、feature `16/16`。
- 唯一 AssistRequest 的外层时间戳不变，但 control 的 `request_id=8`，feature 为缺省 `0`；construction-zone 状态数量为 control `1`、feature `2`。这与“不再恢复路测 RA 状态、保留仿真自产 RA 状态”的设计一致。

## 后续判定边界

本 canary 的终态相同，不能据此计算复现率增益。下一轮应从旧 binary 的“路测自触发、仿真未触发”样本中抽取一批，以同样的单 binary/双 task 方式 A/B；只有 feature 将其中一部分从未触发变为触发，且人工触发/误触发集合没有异常回归，才能量化此次修复对准召预测的提升。
