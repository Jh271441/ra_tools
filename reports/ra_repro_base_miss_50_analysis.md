# RA 路测触发 / Base Sim 未触发：50 Case 复现性分析

## 范围与方法

- 输入 case：50；成功解析：48；失败：2。
- 原始 case 集来自 `~/utils/仿真复现性/`；仓库输入清单为 `check_sim/batch/data/base_miss_50.csv`。
- 对比从 Trail `trip_segment.startTimestamp` 开始，排除 EzSim warmup。
- 信号来自 `/planning/planning_debug`，重点检查模型召回、FP、voluntary unstuck、StuckSignal 和正式请求。
- 原 Orion output bag 已超过保留期；除已有本地 case 外，sim 使用 CSV 中的 base binary 和同一组标准 extra args 重新运行。
- CSV DPE 是历史任务指标，报告中的 planning/session 信号来自当前重跑；二者不一致时单独标记为跨运行复现不稳定。

## 摘要

- 当前重跑产生 planning `MODEL_REQUEST`：7/48。
- Road 请求帧出现 `StuckSignal start=0,last>0`：40/48。
- `MODEL_REQUEST` 仅表示 planning 生成请求；是否建立 assist channel 还需结合 session opened 和历史 DPE。

## 当前 Case 29434409 根因

正式对比从 `1777372719965` 开始，不额外裁掉 5 秒 warmup。当前 case 存在两条相互独立的差异链：

1. **PerfectPose 速度误差影响 `FP_YIELD_DYNAMIC_OBJECT` 时序**：baseline 相对 road 的 speed MAE 为 `0.0577 m/s`、P95 为 `0.2048 m/s`，共有 155 个 pose 帧位于 `0.5 m/s` 阈值的不同侧，令 `yield_temp_parked_cycles` 相差约 6 个 planning cycle。回放 road pose 后速度误差归零，首次 road 请求前的 Yield 决策差异由 22 帧降为 0；关闭 smart agent 与 baseline 相同，因此本 case 的 Yield FP 差异来自 ego speed 时序，不是障碍物选择或 smart agent。
2. **Selected trajectory `StuckSignal` 掉零影响正式请求时机**：road 首次 `MODEL_REQUEST` 帧为 `reason=kNoStuck,start_timestamp=0,last_stuck_timestamp=1777372738256`。`IsVoluntaryUnstuckFail()` 未校验 reason/start 是否有效，直接计算 `last-start > 5000 ms`，因此掉零帧立即得到 `UnstuckFail` 并绕过 voluntary unstuck 等待。sim 同期仍为连续 `kNotBlockageObject`，duration `2490 ms`，状态为 `WAITTING_CORE_PLANNER_UNSTUCK`，随后 signal 掉零时才请求。

Pose 回放只修复第一条链，没有修复 selected trajectory 的 StuckSignal 连续性，所以不能让正式请求时刻完全对齐。历史 Orion base DPE 记录为未触发，但当前相同 binary/extra args 重跑已出现 `MODEL_REQUEST`、`/planning/assist_request` 和 opened session；因此该 case 的批量标签是 `SIM_REQUESTED_BUT_METRIC_MISSED`，并且必须把历史任务指标与当前重跑分开报告。

| 输入/实验 | Speed MAE | Speed P95 | 0.5 m/s 异步帧 | Yield 决策差异 | RA 请求时间 |
|---|---:|---:|---:|---:|---:|
| road | - | - | - | - | `1777372739933` |
| baseline | 0.0577 m/s | 0.2048 m/s | 155 | 22 | `1777372741648` |
| replay road pose | 0 | 0 | 0 | 0 | `1777372742157` |
| disable smart agent | 0.0577 m/s | 0.2048 m/s | 155 | 22 | `1777372741648` |

## 根因分布

| 根因 | 数量 |
|---|---:|
| `SIM_FORCING_RECALL_NOT_REPRODUCED` | 22 |
| `SIM_MODEL_NOT_RECALLED` | 9 |
| `SIM_REQUESTED_BUT_METRIC_MISSED` | 7 |
| `SIM_ROAD_TRIGGER_NOT_REPRODUCED:SPECIAL_STUCK_SCENE` | 2 |
| `SIM_REQUEST_STATE_OR_OTHER_GATE` | 2 |
| `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_SELECTION` | 2 |
| `SIM_ROAD_TRIGGER_NOT_REPRODUCED:REQUEST_FROM_ROUTING` | 1 |
| `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_VEHICLE_HAZARD_SIGNAL` | 1 |
| `SIM_FP_SUPPRESSED:FP_QUEUING` | 1 |
| `SIM_VOLUNTARY_UNSTUCK_GATE` | 1 |

## Road 触发路径

| Process reason | 数量 |
|---|---:|
| `FN_FORCING_RECALL` | 23 |
| `ASSIST_STUCK_MODEL` | 19 |
| `SPECIAL_STUCK_SCENE` | 2 |
| `FN_SELECTION` | 2 |
| `REQUEST_FROM_ROUTING` | 1 |
| `FN_VEHICLE_HAZARD_SIGNAL` | 1 |

## Case 明细

| Scenario | Issue | Road trigger | 根因 | Road request | Sim model frames | Sim waiting | Sim session opened | Sim max score |
|---:|---|---|---|---:|---:|---:|---:|---:|
| 29434409 | #31463987 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777372739933 | 12 | 5 | 1 | 0.6426 |
| 29434418 | #31461485 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777369323343 | 0 | 0 | 0 | 0.2123 |
| 29434429 | #31454747 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777361370773 | 0 | 0 | 0 | 0.4690 |
| 29434436 | #31445269 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777349333137 | 2 | 0 | 1 | 0.6489 |
| 29434440 | #31439527 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777340192538 | 0 | 0 | 0 | 0.1729 |
| 29434442 | #31438941 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777339533350 | 0 | 0 | 0 | 0.1554 |
| 29434444 | #31438693 | `SPECIAL_STUCK_SCENE` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:SPECIAL_STUCK_SCENE` | 1777339260843 | 26 | 0 | 0 | 0.6250 |
| 29434445 | #31438571 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777339097559 | 0 | 0 | 0 | 0.2622 |
| 29434458 | #31434711 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777335227366 | 0 | 0 | 0 | 0.1792 |
| 29434463 | #31433285 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777334122063 | 0 | 0 | 0 | 0.2489 |
| 29434469 | #31431905 | `SPECIAL_STUCK_SCENE` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:SPECIAL_STUCK_SCENE` | 1777332561817 | 1 | 0 | 0 | 0.5020 |
| 29434494 | #31419719 | `ASSIST_STUCK_MODEL` | `SIM_REQUEST_STATE_OR_OTHER_GATE` | 1777288341194 | 31 | 0 | 0 | 0.5620 |
| 29434500 | #31417183 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777283834600 | 0 | 0 | 0 | 0.4897 |
| 29434512 | #31409451 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777275072931 | 0 | 0 | 0 | 0.3604 |
| 29434513 | #31408963 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777274484937 | 0 | 0 | 0 | 0.4077 |
| 29434515 | #31402861 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777268062575 | 0 | 0 | 0 | 0.2554 |
| 29434526 | #31391855 | `FN_SELECTION` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_SELECTION` | 1777251586462 | 0 | 0 | 0 | 0.4902 |
| 29434529 | #31390755 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777250292745 | 0 | 0 | 0 | 0.4814 |
| 29434530 | #31390613 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777250223869 | 0 | 0 | 0 | 0.1846 |
| 29434535 | #31388675 | `FN_SELECTION` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_SELECTION` | 1777248405833 | 13 | 0 | 0 | 0.6694 |
| 29434547 | #31378549 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777207179446 | 0 | 0 | 0 | 0.7344 |
| 29434549 | #31375999 | `REQUEST_FROM_ROUTING` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:REQUEST_FROM_ROUTING` | 1777201644990 | 0 | 0 | 0 | 0.3616 |
| 29434552 | #31373939 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777197369732 | 0 | 0 | 0 | 0.1476 |
| 29434556 | #31369545 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777190760345 | 0 | 0 | 0 | 0.1989 |
| 29434559 | #31365135 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777185599175 | 0 | 0 | 0 | 0.4663 |
| 29434560 | #31360643 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777179887983 | 0 | 0 | 0 | 0.2720 |
| 29434566 | #31357521 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777173553942 | 0 | 0 | 0 | 0.2163 |
| 29434567 | #31354523 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777168590346 | 0 | 0 | 0 | 0.1891 |
| 29434580 | #31337285 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777112942608 | 13 | 0 | 1 | 0.5918 |
| 29434595 | #31331923 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777103884762 | 0 | 0 | 0 | 0.4551 |
| 29434598 | #31330551 | `FN_VEHICLE_HAZARD_SIGNAL` | `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_VEHICLE_HAZARD_SIGNAL` | 1777102135030 | 13 | 0 | 0 | 0.6929 |
| 29434603 | #31327239 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777097528266 | 0 | 0 | 0 | 0.2377 |
| 29434621 | #31305797 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777038546839 | 0 | 0 | 0 | 0.2400 |
| 29434628 | #31299617 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777028776941 | 18 | 0 | 2 | 0.5762 |
| 29434637 | #31298079 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777025805271 | 0 | 0 | 0 | 0.2942 |
| 29434645 | #31295071 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777021859518 | 10 | 0 | 1 | 0.6167 |
| 29434652 | #31287811 | `FN_FORCING_RECALL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777014086422 | 0 | 0 | 1 | 0.2603 |
| 29434653 | #31285431 | `ASSIST_STUCK_MODEL` | `SIM_REQUESTED_BUT_METRIC_MISSED` | 1777011114763 | 5 | 0 | 1 | 0.2389 |
| 29434685 | #31257997 | `ASSIST_STUCK_MODEL` | `SIM_FP_SUPPRESSED:FP_QUEUING` | 1776940703716 | 24 | 0 | 0 | 0.6558 |
| 29434697 | #31256871 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1776938957416 | 0 | 0 | 0 | 0.3113 |
| 29434713 | #31237141 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1776915323631 | 0 | 0 | 0 | 0.6304 |
| 29730440 | #31485217 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777427937429 | 0 | 0 | 0 | 0.3440 |
| 29730442 | #31484335 | `ASSIST_STUCK_MODEL` | `SIM_VOLUNTARY_UNSTUCK_GATE` | 1777426773742 | 6 | 4 | 0 | 0.2615 |
| 29730450 | #31480733 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777422904927 | 0 | 0 | 0 | 0.2961 |
| 29730451 | #31480593 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777422701545 | 0 | 0 | 0 | 0.1763 |
| 29730456 | #31479575 | `ASSIST_STUCK_MODEL` | `SIM_REQUEST_STATE_OR_OTHER_GATE` | 1777421621326 | 30 | 0 | 0 | 0.7041 |
| 29730459 | #31478611 | `ASSIST_STUCK_MODEL` | `SIM_MODEL_NOT_RECALLED` | 1777420701932 | 0 | 0 | 0 | 0.5723 |
| 29730463 | #31478225 | `FN_FORCING_RECALL` | `SIM_FORCING_RECALL_NOT_REPRODUCED` | 1777420239628 | 0 | 0 | 0 | 0.2537 |

## 机制结论

1. **Voluntary unstuck / StuckSignal**：`IsVoluntaryUnstuckFail()` 直接计算 `last_stuck_timestamp - start_timestamp`。若 signal 掉为 `kNoStuck` 时 start 清零、last 保留，会立即满足超时并改变 RA 请求时机。
2. **Forcing recall**：该 FN 路径不依赖模型过阈值，而依赖 `accumulated_cycle == trigger_cycle`。排队、让行、红灯、即将起步、速度达到 reset 阈值等状态会阻止累计或清零。
3. **跨运行不稳定**：历史 Orion DPE 与当前同 binary/extra args 重跑可能不同。应分别报告历史指标、planning request、assist request/session，不能合并为单一“触发/未触发”。

## 逐案证据

- `29434409` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777372739933；road request coincides with StuckSignal start=0/last>0 dropout；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434418` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777369323343；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=428 sim=428；sim forcing accumulated=49/200
- `29434429` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777361370773；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=370 sim=356；sim forcing accumulated=194/200
- `29434436` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777349333137；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434440` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777340192538；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=472 sim=472；sim forcing accumulated=50/200
- `29434442` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777339533350；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=671 sim=666；sim forcing accumulated=50/200
- `29434444` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:SPECIAL_STUCK_SCENE`：road request @ 1777339260843；road trigger path=SPECIAL_STUCK_SCENE; sim frames=1
- `29434445` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777339097559；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=471 sim=469；sim forcing accumulated=50/200
- `29434458` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777335227366；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=899 sim=898；sim forcing accumulated=116/300
- `29434463` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777334122063；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=430 sim=428；sim forcing accumulated=113/300
- `29434469` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:SPECIAL_STUCK_SCENE`：road request @ 1777332561817；road trigger path=SPECIAL_STUCK_SCENE; sim frames=0
- `29434494` `SIM_REQUEST_STATE_OR_OTHER_GATE`：road request @ 1777288341194；Model reason exists without request, waiting, or recorded FP
- `29434500` `SIM_MODEL_NOT_RECALLED`：road request @ 1777283834600；sim max score=0.4897
- `29434512` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777275072931；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=502 sim=499；sim forcing accumulated=104/300
- `29434513` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777274484937；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=669 sim=667；sim forcing accumulated=103/300
- `29434515` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777268062575；road request coincides with StuckSignal start=0/last>0 dropout；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=548 sim=545；sim forcing accumulated=110/300
- `29434526` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_SELECTION`：road request @ 1777251586462；road trigger path=FN_SELECTION; sim frames=264
- `29434529` `SIM_MODEL_NOT_RECALLED`：road request @ 1777250292745；sim max score=0.4814
- `29434530` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777250223869；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=475 sim=471；sim forcing accumulated=54/200
- `29434535` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_SELECTION`：road request @ 1777248405833；road trigger path=FN_SELECTION; sim frames=54
- `29434547` `SIM_MODEL_NOT_RECALLED`：road request @ 1777207179446；road request coincides with StuckSignal start=0/last>0 dropout；sim max score=0.7344
- `29434549` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:REQUEST_FROM_ROUTING`：road request @ 1777201644990；road trigger path=REQUEST_FROM_ROUTING; sim frames=0
- `29434552` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777197369732；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=556 sim=552；sim forcing accumulated=107/300
- `29434556` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777190760345；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=611 sim=609；sim forcing accumulated=104/300
- `29434559` `SIM_MODEL_NOT_RECALLED`：road request @ 1777185599175；sim max score=0.4663
- `29434560` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777179887983；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=583 sim=582；sim forcing accumulated=104/300
- `29434566` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777173553942；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=544 sim=544；sim forcing accumulated=107/300
- `29434567` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777168590346；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=513 sim=513；sim forcing accumulated=50/200
- `29434580` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777112942608；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434595` `SIM_MODEL_NOT_RECALLED`：road request @ 1777103884762；sim max score=0.4551
- `29434598` `SIM_ROAD_TRIGGER_NOT_REPRODUCED:FN_VEHICLE_HAZARD_SIGNAL`：road request @ 1777102135030；road trigger path=FN_VEHICLE_HAZARD_SIGNAL; sim frames=0
- `29434603` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777097528266；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=445 sim=416；sim forcing accumulated=104/300
- `29434621` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777038546839；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=686 sim=683；sim forcing accumulated=50/200
- `29434628` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777028776941；sim bag contains 2 MODEL_REQUEST frame(s)；assist session opened in 2 frames
- `29434637` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777025805271；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=476 sim=471；sim forcing accumulated=105/300
- `29434645` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777021859518；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434652` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777014086422；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434653` `SIM_REQUESTED_BUT_METRIC_MISSED`：road request @ 1777011114763；sim bag contains 1 MODEL_REQUEST frame(s)；assist session opened in 1 frames
- `29434685` `SIM_FP_SUPPRESSED:FP_QUEUING`：road request @ 1776940703716；dominant sim FP=FP_QUEUING
- `29434697` `SIM_MODEL_NOT_RECALLED`：road request @ 1776938957416；sim max score=0.3113
- `29434713` `SIM_MODEL_NOT_RECALLED`：road request @ 1776915323631；sim max score=0.6304
- `29730440` `SIM_MODEL_NOT_RECALLED`：road request @ 1777427937429；sim max score=0.3440
- `29730442` `SIM_VOLUNTARY_UNSTUCK_GATE`：road request @ 1777426773742；sim model detected but voluntary unstuck gate returned WAITTING_CORE_PLANNER_UNSTUCK；sim stuck signal duration=3200 ms, modes=(2,)
- `29730450` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777422904927；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=476 sim=471；sim forcing accumulated=103/200
- `29730451` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777422701545；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=478 sim=474；sim forcing accumulated=49/200
- `29730456` `SIM_REQUEST_STATE_OR_OTHER_GATE`：road request @ 1777421621326；Model reason exists without request, waiting, or recorded FP
- `29730459` `SIM_MODEL_NOT_RECALLED`：road request @ 1777420701932；sim max score=0.5723
- `29730463` `SIM_FORCING_RECALL_NOT_REPRODUCED`：road request @ 1777420239628；road trigger path=FN_FORCING_RECALL；sim FN_FORCING_RECALL frames=0；stationary cycles road=735 sim=733；sim forcing accumulated=106/300

## 失败项

- `29434531`: RuntimeError('EzSim 9491d1c6-aef2-4be4-9514-e9209e8c602e failed: Failed to complete simulation: Running data_sim failed with error: Running script file returned 1 [<lambda> in context.py:1585]')
- `29730417`: RuntimeError('EzSim 144b5170-3d4d-495a-b71e-6722dd37b6a5 failed: Failed to complete simulation: Running data_sim failed with error: Running script file returned 1 [<lambda> in context.py:1585]')

两项均已串行手工重试，仍在约 61% 仿真进度稳定失败。`simulator.log` 的直接原因是
`joint_prediction_for_smart_agent.onnx` 执行时报
`CUDA failure 400: invalid resource handle`，随后 `data_sim` 以 `-6` 退出。该问题属于
EzSim smart-agent ONNX/CUDA 运行时故障，不是 bag 下载或 RA 分析脚本错误。关闭 smart
agent 会改变仿真条件，因此未将降级实验混入同口径统计；上面的根因分布只使用 48 个完整
成功 case。
