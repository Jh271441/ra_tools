# Release 1030 Offline Onboard NPZ Full Evaluation & Diff Report (Base `v89` vs CR `7028995` `v122`)

- **Scenarios evaluated**: `1561 / 1561` executable (`1563` physical issues; `1415` review-eligible business issues; full recall denominator `784`)
- **Base model**: `/volume/home/.cache/voyager/model_files/planner.model-files_vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel_89_6a15846abf8e0ea2375d4dd1a812061d` (`sha256=90753d43dd924440...`, `100.716s`)
- **Feature model (CR 7028995)**: `/volume/home/workspace/ra_tools/outputs/cr7028995_models/vectorized_scenario_remote_assist_model_bs0_fp32_x86_v122.ifxmodel` (`sha256=ad458dfe2a706e6d...`, `101.211s`)

## 1. All-Business (`1,415` Issues) Full-Chain Comparison (Offline NPZ vs Orion Sim)

| Arm / Source | Known | TP | FP | FN | TN | Unified P (`TP/Req`) | Known R (`TP/Known+`) | Strict GOOD P |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Road Bag `/planning/assist_request` GT | 1414 | 612 | 631 | 171 | 0 | 612/1243 (**49.24%**) | 612/783 (**78.16%**) | 520/1243 (41.83%) |
| Offline NPZ (`recorded` car scores) | 1414 | 614 | 631 | 169 | 0 | 614/1245 (**49.32%**) | 614/783 (**78.42%**) | 521/1245 (41.85%) |
| Offline NPZ Base (`v89` Q2 x86 IFX) | 1414 | 647 | 630 | 136 | 1 | 647/1277 (**50.67%**) | 647/783 (**82.63%**) | 534/1277 (41.82%) |
| Orion Sim Base (`Jobs 50119729+50121701`) | 1414 | 622 | 539 | 161 | 92 | 622/1161 (**53.57%**) | 622/783 (**79.44%**) | 519/1161 (44.70%) |
| Offline NPZ Feature (`CR 7028995 v122` x86 IFX) | 1414 | 539 | 92 | 244 | 539 | 539/631 (**85.42%**) | 539/783 (**68.84%**) | 462/631 (73.22%) |
| Offline NPZ Feature (`v122`, `onboard_strict_road`) | 1414 | 498 | 82 | 285 | 549 | 498/580 (**85.86%**) | 498/783 (**63.60%**) | 444/580 (76.55%) |
| Orion Sim Feature (`Job 50509481` CR 7028995 E21) | 1413 | 534 | 92 | 248 | 539 | 534/626 (**85.30%**) | 534/782 (**68.29%**) | - |

## 2. Subgroup Breakdown (`Base v89` vs `Feature CR 7028995 v122`, `onboard_full`)

| Cohort | Issues | Base `v89` Unified P / Known R | Feature `v122` Unified P / Known R | TP Restored / Lost | FP Added / Removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| All Business (`1,415`) | 1415 | 50.67% / 82.63% (`647/1277`) | 85.42% / 68.84% (`539/631`) | `+7 / -115` | `+1 / -539` |
| Traffic Light / EOL (`400`) | 400 | 96.50% / 100.00% (`386/400`) | 96.73% / 99.48% (`384/397`) | `+0 / -2` | `+0 / -1` |
| Non-Traffic Business (`1,015`) | 1015 | 29.76% / 65.74% (`261/877`) | 66.24% / 39.04% (`155/234`) | `+7 / -113` | `+1 / -538` |
| Legacy Cropped-NPZ Common (`974`) | 974 | 29.51% / 64.49% (`247/837`) | 69.80% / 36.81% (`141/202`) | `+7 / -113` | `+1 / -530` |

## 3. Paired Transition Summary (`Base v89` -> `Feature CR 7028995 v122`, All Business)

- **Paired known issues**: `1414` (`same=752`, `changed=662`)
- **TP restored (`0 -> 1`)**: `+7` (`{'正确触发': 4, '成功': 2, '失败': 1}`)
- **TP lost (`1 -> 0`)**: `-115` (`{'正确触发': 40, '失败': 6, '无需协助': 36, '成功': 33}`)
- **FP added (`0 -> 1`)**: `+1`
- **FP removed (`1 -> 0`)**: `-539`
