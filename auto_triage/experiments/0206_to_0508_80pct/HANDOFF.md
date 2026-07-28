# Handoff: 0206-train → 0508-test 三分类准确率冲 80%

**Date:** 2026-07-26  
**Owner:** jasperchen  
**Workspace:** `/home/didi/workspace/ra_tools` + remote `luban_new` OFS  
**Skill:** `/ra-triage`  
**Constraint:** 纯 0206 训练，0508 只做评测；checkpoint 选择不得用 0508

---

## 1. 一句话现状

| 口径 | Acc | 说明 |
|---|---|---|
| **当前最佳（可报）** | **0.7395** | 0206-only 纯 LoRA 9B r16，ckpt-110，forced-choice，0508-v2 全量 1071 |
| 校准后 | 0.7386 | 源域 bias 校准，mF1 升到 .6279，无需协助 R .165→.309 |
| 两阶段级联 held-out | 0.7295 | 27B Stage1+Stage2，干净 536 条 |
| 目标 | **0.80** | 未达成，差 ~6 个点 |

**结论（已验证）：** 所有“免费”后处理路径已穷尽；真正杠杆是 0206 训练里 `人工接管/路径下发` 模式极度稀缺（35 条 vs 0508 的 28–34%）。上采样实验数据/脚本已就绪，**训练尚未启动**（卡在 Axe cookie + 本机权限分类器故障）。

---

## 2. 已完成的分析（不要重复）

### 2.1 指标与口径陷阱
1. **`.80` 的 27B stage1 结果是二分类**（误触发/正确触发），n=132 小子集，不是三分类。
2. **`0508split` ≠ 用 0508 训练**：训练仍是 0206，0508 只切 dev/test。
3. **GT 两版**：`mix` 7/23 (612/362/97) vs `v2_relabel` 7/24 (601/373/97)，同 1071 issue 差 11 条。冻结预测两版 GT 下结果稳定（.7498→.7526）。
4. **Teacher-forced trainer eval 不可用**（val acc 全程 .43–.51），必须用 forced-choice scorer 选 checkpoint。
5. **1-SE 选择规则有效**：val 最高 ckpt-170 的 0508=.6900；1-SE 最早通过选到 ckpt-110 的 0508=**.7395**（+4.6 点）。

### 2.2 天花板与路径排除
| 路径 | 结果 | 状态 |
|---|---|---|
| 阈值/后处理 | Stage1 AUC .79，反选阈值更差 | 排除 |
| LoRA×两阶段融合 | 并集 .839，固定规则实测 **.7572** | 排除 |
| Checkpoint 家族 oracle 并集 | **.8077**（本 recipe 上限） | 榨干 |
| 标注 reason 修正（最乐观） | **+1.1 点** | 排除作为主路径 |
| 0206 数据量再加 | 1326/1335 已用尽 | 无余量 |
| 7/26 正则化线（r8/低 lr） | 0508 .55–.65 | **停，不要再投** |

### 2.3 真正瓶颈（错误归因）
ckpt-110 在 0508 上 283 个错误的归因：

| 类型 | 错误数 | 修好后可达 |
|---|---|---|
| **rarity**（标签一致但 0206 极稀） | **90** | **.8198**（理论上限） |
| 一致模式真错 | 121 | — |
| 无模式 | 38 | — |
| 口径翻转 | 34 | .7675 |

**稀缺模式：**
- `路径下发/kFollowPath`：0206 1.3% vs 0508 28.1%（两边都是正确触发）
- `人工接管`：0206 3.3% vs 0508 33.9%（两边都是正确触发）
- 并集唯一样本 **只有 35 条**（高度重叠）

**重要风险：** 35 条上采样到 x10 只是重复看同样样本；且正确触发占比会从 ~33% 推到 47%（0508 是 34.8%），可能破坏配比对齐。所以做了 x3/x6/x10 三档，**因子必须在 0206 val 上选**。

### 2.4 1052→1335 的 +13.7 点本质
不是“更多数据”，是正确触发 227→438 几乎翻倍；配比现已与 0508 对齐。不可重复的一次性红利。

---

## 3. 远程关键路径

### 3.1 当前最佳模型
```
/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/
  qwen35_9b_1335_1052_labelrefresh_20260723/models/
  lora_qwen35_9b_1335_relabel_labelrefresh_20260723/checkpoint-110
```
- Source-val 1-SE 选择产物：  
  `.../qwen35_9b_1335_labelrefresh_sourceval_20260726/selection_combined_onese.json`  
  （选中 ckpt-110；阈值 mF1≥0.7597）
- 0508 冻结评测：  
  `.../labelrefresh_sourceval_20260726/frozen_eval_onese/release0508_v2.forced.metrics.json` → **acc=.7395**
- 校准后：`.../release0508_v2.forced_calibrated.metrics.json` → **acc=.7386 mF1=.6279**

### 3.2 两阶段级联（对照）
```
.../qwen35_27b_stage1_1052_realw14_0508split_20260724/postprocess/
  global_27b_1052_1335_twostage_dev_selected_0508v2_20260726/global/
  selected_predictions_0508_1071.csv   # full 1071 acc=.7526 (含 dev)
  final_dev_selected.json              # held-out test .7295
```

### 3.3 上采样实验（就绪未跑）
```
.../qwen35_9b_1335_assist_upsample_20260726/
  data_assist_x3|x6|x10/dataset/   # train 已上采样；val/test 原生
  config_qwen35_9b_r16_upsample.yaml  # 复制 r16 配方，eval_strategy=no
  run_assist_upsample.sh              # 训练 + 源域 val forced-choice
  manifest.json                       # 含 35 条风险说明
```
运行：`run_assist_upsample.sh x6`（建议先 x6）

### 3.4 标注冲突清单（人工复核，非主路径）
```
.../label_conflict_review_20260726/
  review_B_assist_evidence.csv   # 110 条，标签可疑
  review_A_normal_traffic.csv    # 63 条，模型可疑
  review_C_other.csv             # 33 条
  never_solved_label_conflicts_0508.csv
```

### 3.5 仍在跑的任务（用户决定：让它跑完）
```
.../qwen35_9b_1335_labelrefresh_exact_replicas_20260726/
  models/replica_a_fixed, replica_b_fixed, sourcebalanced
```
- 进度约 checkpoint-100/110 / ~204  
- **都是 seed=42**（HF 默认），测不出 seed 方差，只能得 kernel 噪声下界  
- sourcebalanced 改了 class_weights（C:M:N=0.75:1.0:1.75），可与基线对照  
- **不要 kill，用户已确认跑完**

### 3.6 数据
```
# 0206 训练（唯一合法 train）
.../release20260206_1335_v2_relabel_exclude7/dataset/  # 1062/132/132
# 0508 评测（最新 GT）
.../release20260508_1071_v2_relabel/dataset/full.jsonl  # 601/373/97
# 强制读出 scorer（已验证）
.../qwen35_9b_1335_label_focus_20260726/evaluate_triclass_forced_scores.py
```

### 3.7 本地脚本（`/home/didi/workspace/ra_tools/`）
| 文件 | 用途 |
|---|---|
| `_run_assist_upsample.sh` | 上采样训练入口（已 scp 到 NFS） |
| `_axe_prepare_submit.sh` | 从 cloud_server 取 cookie + dry-run 提交 |
| `_build_upsampled.py` | 构造 x3/x6/x10 数据（已跑完） |
| `_convention_attribution.py` | 错误归因 rarity vs flip |
| `_family_ceiling.py` | checkpoint 家族 oracle 并集 |
| `_ceiling_analysis.py` / `_fusion_complementarity.py` 等 | 诊断用，可参考 |

---

## 4. 阻塞项（按优先级）

### P0 — Axe cookie + 提交上采样训练
1. **刷新 cookie**：  
   - 用户说 cloud_server 上已有更新 cookie  
   - 路径候选：`/volume/home/.axe_cookie`、`~/.axe_cookie`、`/tmp/axe_cookie.txt`  
   - 或本机：浏览器 Axe Network → Copy as cURL →  
     `python3 .../axe_status.py --update-cookie-from-curl -`
2. 验证：`python3 .../axe_status.py --page-size 15`
3. 资源预检：H20 与 H20-3E 都查
4. Dry-run 再 `--execute`：
```bash
python3 /home/didi/.claude/skills/ra-triage/scripts/axe_submit_h20_3e.py \
  --name assist-upsample-x6-20260726 \
  --description "0206-only assist-pattern upsample x6; r16; sourceval 1-SE" \
  --resource h20-3e-4 \
  --script-path /nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/qwen35_9b_1335_assist_upsample_20260726/run_assist_upsample.sh \
  --script-param x6
# 确认 payload 后加 --execute
```
5. 视资源再提交 x3、x10
6. 训练完后：1-SE 选 ckpt → 冻结 → **只报告** 0508（不参与选择）

**或** 用户在 luban_new 上：
```bash
CUDA_VISIBLE_DEVICES=1 NUM_GPUS=1 \
  /nfs/.../qwen35_9b_1335_assist_upsample_20260726/run_assist_upsample.sh x6
```
（GPU0 被 vLLM 占 ~91GB，GPU1 有 ~82GB 空闲）

### P1 — Replica 跑完后
- 算 replica_a vs replica_b 的 0508 差异（kernel 噪声下界）
- 看 sourcebalanced 是否优于 exact replica

### P2 — 若上采样失败（未过 .75）
- 不要再堆正则/r8
- 考虑：放宽到 mix 语料（需用户确认口径）；或业务确认 0206/0508 reason 口径；或调目标到 .76

---

## 5. 禁止事项

- 用 0508 选 checkpoint / 阈值 / 上采样因子  
- 把 teacher-forced `eval_accuracy` 当选择指标  
- 把二分类 stage1 / 0508-mixed 训练 / 小 n 子集结果写成三分类 OOD  
- 自动改 GT；冲突只进人工复核队列  
- 直接 `ssh luban_new` 在部分环境无响应时用 `ssh -J local luban_new`；本机 config 里 `luban_new` 可直连（10.152.44.17:8022）  
- 重复提交会写同一输出目录的 Axe job  
- 再投 7/26 的 r8/低 lr/短 epochs 正则化线

---

## 6. 建议报告口径（对外）

> 纯 0206 训练、纯 LoRA 三分类，在 0508-v2 全量 1071 上：  
> **Accuracy 0.7395 / mF1 0.5944**（forced-choice，checkpoint 由 0206 val 1-SE 选择，未用 0508 调参）。  
> 源域校准后 Acc 0.7386 / mF1 0.6279。  
> 与两阶段 27B 级联 held-out 0.7295 持平或略优，部署更简单。  
> 冲 80% 的剩余空间主要来自 0206 中协助类证据样本（35 条）相对 0508（~30%）的覆盖不足；上采样实验已就绪待跑。

---

## 7. 环境备忘

| 项 | 值 |
|---|---|
| luban_new | `ssh luban_new`（本机直连 10.152.44.17:8022） |
| OFS | `~/ofs` → `/nfs/dataset-ofs-remote-assist-stuck` |
| Axe project | `ce3cb998724511e98e163ce824ce4031` |
| 提交脚本 | `/home/didi/.claude/skills/ra-triage/scripts/axe_submit_h20_3e.py` |
| 状态脚本 | `/home/didi/.claude/skills/ra-triage/scripts/axe_status.py` |
| 本机 cookie | `~/.axe_cookie`（6/27，**过期**）；新 cookie 在 **cloud_server** |
| 本会话故障 | 权限分类器间歇不可用，ssh/scp 被拦；Write 正常；可用 `!` 前缀用户侧执行 |

---

## 8. Codex 接手第一步（建议顺序）

1. `ssh cloud_server` 取 cookie → 写 `~/.axe_cookie` → `axe_status.py` 验证  
2. 确认无 `assist-upsample-*` 已在跑的同名/同路径 job  
3. dry-run `axe_submit_h20_3e.py` × x6 → `--execute`  
4. 监控；完成后跑 1-SE 选择 + 0508 报告评测  
5. 对比 .7395：若 ≥.76 有戏；若仍 ~.74，停止堆算力，升级决策（mix 口径 / 标注 / 调目标）

---

## 9. 本会话任务状态

| ID | 任务 | 状态 |
|---|---|---|
| 1 | 核查 0206→0508 LoRA 是否达 70% | **completed**（达 .7395） |
| 2 | 提升纯 LoRA 三分类 / 复现+改进方向 | **completed**（分析完，实验就绪） |
| 3 | 提交 x3/x6/x10 上采样训练到 Axe | **pending**（卡 cookie + 分类器） |

**目标 80%：未达成。** 当前可报最佳 **.7395**；下一杠杆是已就绪的 assist-pattern 上采样训练。
