#!/usr/bin/env python3
"""Information ceiling of the 0206-trained 1335 checkpoint family on 0508.

Decisive question for the 80% goal: across every checkpoint of the 0206-only
1335 run, how many 0508 cases are solved by AT LEAST ONE checkpoint?

  - If the union is well above .80, the information exists inside the family and
    a better selector/ensemble could in principle reach the target.
  - If the union is near or below .80, no selection or ensembling over this
    family can ever reach it, and the goal requires different training data or
    a different model class.

Also reports the per-case "how many checkpoints got it right" histogram, which
separates genuinely-hard cases (0 correct) from selection-limited ones.

Read-only. The union is an ORACLE quantity and is never a deployable number.
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


def load_gt(path):
    m = {}
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            last = d["conversations"][-1]
            v = last.get("content") or last.get("value", "")
            try:
                lab = json.loads(v)["label"]
            except Exception:
                lab = next((L for L in LABELS if L in v), None)
            m[d["id"]] = lab
    return m


gt = load_gt(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl")

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

steps = sorted(runs)
print(f"# 1335 checkpoints with 0508 predictions: {steps}")
ids = sorted(set.intersection(*(set(runs[s]) for s in steps)) & set(gt))
n = len(ids)
print(f"# cases: {n}\n")

# per-checkpoint accuracy
print("## per-checkpoint 0508 accuracy (generative)")
for s in steps:
    a = sum(1 for i in ids if runs[s][i] == gt[i]) / n
    print(f"   ckpt-{s:<4} {a:.4f}")

# union / histogram
hits = {i: sum(1 for s in steps if runs[s][i] == gt[i]) for i in ids}
union = sum(1 for i in ids if hits[i] > 0)
allc = sum(1 for i in ids if hits[i] == len(steps))
print(f"\n## ORACLE UNION (>=1 checkpoint correct): {union}/{n} = {union/n:.4f}")
print(f"## unanimous correct (all {len(steps)}):      {allc}/{n} = {allc/n:.4f}")
print(f"## never correct (0 of {len(steps)}):          {n-union}/{n} = {(n-union)/n:.4f}")

print("\n## histogram: #checkpoints correct -> #cases")
h = Counter(hits.values())
for k in sorted(h):
    print(f"   {k:>2}/{len(steps)}: {h[k]:>4}")

# per-class breakdown of the never-correct set
never = [i for i in ids if hits[i] == 0]
print(f"\n## composition of the {len(never)} never-solved cases")
c = Counter(gt[i] for i in never)
tot = Counter(gt[i] for i in ids)
for L in LABELS:
    share = c[L] / tot[L] if tot[L] else 0
    print(f"   {L}: {c[L]}/{tot[L]} = {share:.3f} of that class is unsolvable by any checkpoint")

# what the family predicts on never-solved cases (is it systematically wrong?)
print("\n## on never-solved cases, the family's modal prediction vs truth")
mode_tr = Counter()
for i in never:
    modal = Counter(runs[s][i] for s in steps).most_common(1)[0][0]
    mode_tr[(gt[i], modal)] += 1
for k, v in mode_tr.most_common(8):
    print(f"   gt={k[0]:5s} -> family says {k[1]:5s}: {v}")

# majority-vote-over-all and best-single for reference
maj = {}
for i in ids:
    cc = Counter(runs[s][i] for s in steps).most_common()
    tied = [l for l, k in cc if k == cc[0][1]]
    maj[i] = tied[0] if len(tied) == 1 else next(L for L in LABELS if L in tied)
print(f"\n## majority vote over all {len(steps)} ckpts: {sum(1 for i in ids if maj[i]==gt[i])/n:.4f}")
best = max(steps, key=lambda s: sum(1 for i in ids if runs[s][i] == gt[i]))
print(f"## best single checkpoint (ckpt-{best}): "
      f"{sum(1 for i in ids if runs[best][i]==gt[i])/n:.4f}")
print(f"\n## GAP: union {union/n:.4f} - best single {sum(1 for i in ids if runs[best][i]==gt[i])/n:.4f} "
      f"= {union/n - sum(1 for i in ids if runs[best][i]==gt[i])/n:.4f} recoverable by perfect per-case routing")
