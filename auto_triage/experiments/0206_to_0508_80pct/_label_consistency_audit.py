#!/usr/bin/env python3
"""Model-independent audit: is each 0508 GT label consistent with its own reason?

The reason field often records the decisive evidence directly. Per
TRIAGE_DECISION_GUIDE:
  - 人工接管 / 路径下发(kFollowPath) / 方向控制 / waypoint / SWAG / 倒车 / MRC
      => human assistance was required to escape        => 正确触发
  - 车辆自行脱困 / 前车驶离 / 自行恢复 / 主系统恢复
      => the constraint cleared on its own              => 无需协助
  - 正常排队 / 红灯 / 拥堵 / 让行 / 道闸 / 泊入泊出 / 掉头 (and no assist evidence)
      => normal traffic pause, not a real stuck         => 误触发

This runs over ALL 1071 rows, independent of any model, and reports where GT
contradicts its own reason. Then it recomputes ckpt-110 accuracy under the
reason-implied labels to size the headroom that label correction would unlock.

STRICTLY DIAGNOSTIC. The reason-implied label is a hypothesis to be confirmed
by human review; it is not a corrected ground truth and must not be used to
train, select, or report a deployable metric.
"""
import json
import os
import re
from collections import Counter

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
LR = os.path.expanduser(
    "~/ofs/user/jasperchen/experiments/qwen35_9b_1335_1052_labelrefresh_20260723"
)
LABELS = ["误触发", "正确触发", "无需协助"]

ASSIST = re.compile(r"人工接管|路径下发|kFollowPath|方向控制|kLeft|kRight|kBackward|waypoint|SWAG|倒车|MRC|遥控")
SELFRES = re.compile(r"自行脱困|前车驶离|自行恢复|自行解除|主系统恢复|恢复规划")
NORMAL = re.compile(r"正常排队|排队|红灯|拥堵|跟车|让行|道闸|泊入|泊出|掉头|等待")


def implied(rs):
    """Label implied by the reason text alone, or None if it says nothing decisive.

    Assistance evidence dominates: if a human had to intervene to free the car,
    the trigger was correct regardless of what else the text mentions.
    """
    if ASSIST.search(rs):
        return "正确触发"
    if SELFRES.search(rs):
        return "无需协助"
    if NORMAL.search(rs):
        return "误触发"
    return None


rows = {}
with open(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl") as fh:
    for line in fh:
        d = json.loads(line)
        last = d["conversations"][-1]
        v = last.get("content") or last.get("value", "")
        try:
            o = json.loads(v)
            rows[d["id"]] = (o.get("label"), str(o.get("reason", "")))
        except Exception:
            rows[d["id"]] = (next((L for L in LABELS if L in v), None), "")

gt = {k: v[0] for k, v in rows.items()}
reason = {k: v[1] for k, v in rows.items()}
n = len(rows)

imp = {k: implied(reason[k]) for k in rows}
decisive = [k for k in rows if imp[k]]
conflict = [k for k in decisive if imp[k] != gt[k]]

print(f"## 0508 rows: {n}")
print(f"## reason is decisive for: {len(decisive)} ({len(decisive)/n:.1%})")
print(f"## GT contradicts its own reason: {len(conflict)} ({len(conflict)/n:.1%})\n")

print("## conflict transitions  GT -> reason-implied")
for k, c in Counter((gt[i], imp[i]) for i in conflict).most_common():
    print(f"   GT={k[0]:5s} but reason implies {k[1]:5s}: {c:>3}")

print("\n## examples per transition")
seen = set()
for i in conflict:
    key = (gt[i], imp[i])
    if key in seen:
        continue
    seen.add(key)
    print(f"   [{key[0]} -> {key[1]}] {i}: {reason[i][:100]}")

# ---- what would ckpt-110 score under reason-implied labels?
SAMPLE = re.compile(r"id=(\S+)\s+gt=(\S+)\s+pred=(\S+)")
RESULT = re.compile(r"评估结果 → \S*/(eval_0508/[^/]+)/checkpoint-(\d+)\.json")
runs = {}
for logname in sorted(os.listdir(f"{LR}/logs")):
    if not logname.endswith(".log"):
        continue
    cur = {}
    with open(f"{LR}/logs/{logname}", errors="replace") as fh:
        for line in fh:
            m = SAMPLE.search(line)
            if m:
                cur[m.group(1)] = m.group(3)
                continue
            r = RESULT.search(line)
            if r:
                if len(cur) >= 1000 and r.group(1).endswith("1335_relabel_labelrefresh_20260723"):
                    runs[int(r.group(2))] = dict(cur)
                cur = {}

ck = runs[110]
ids = sorted(set(ck) & set(gt))


def acc(labels):
    ok = sum(1 for i in ids if ck[i] == labels[i])
    return ok / len(ids), ok


a_now, k_now = acc(gt)
corrected = dict(gt)
for i in conflict:
    corrected[i] = imp[i]
a_fix, k_fix = acc(corrected)

# conservative variant: only trust ASSIST evidence (strongest, least ambiguous)
cons = dict(gt)
n_cons = 0
for i in conflict:
    if ASSIST.search(reason[i]):
        cons[i] = imp[i]
        n_cons += 1
a_cons, k_cons = acc(cons)

print(f"\n## ckpt-110 accuracy on {len(ids)} cases")
print(f"   as-labelled today                     : {a_now:.4f}  ({k_now})")
print(f"   if ALL reason-conflicts corrected     : {a_fix:.4f}  ({k_fix})   [{len(conflict)} rows changed]")
print(f"   if ONLY assist-evidence corrected     : {a_cons:.4f}  ({k_cons})   [{n_cons} rows changed]")
print(f"\n   delta (all)    = {a_fix - a_now:+.4f}")
print(f"   delta (assist) = {a_cons - a_now:+.4f}")
print("\n   NOTE: diagnostic only. reason-implied labels are review hypotheses,")
print("         not corrected ground truth. Do not train, select, or report on them.")
