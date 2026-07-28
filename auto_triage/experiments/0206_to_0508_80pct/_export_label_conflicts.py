#!/usr/bin/env python3
"""Export 0508 cases where the whole 0206-trained checkpoint family agrees
against the ground-truth label.

These are the highest-value human-review candidates: the model is not
uncertain, it is unanimously and confidently on the other side. That pattern
usually means a labelling-criteria conflict rather than a capability gap.

Priority tiers:
  T1  all checkpoints agree on ONE wrong label            (strongest signal)
  T2  no checkpoint correct, modal wrong label >= 80%     (strong)
  T3  no checkpoint correct, mixed wrong labels           (weaker - genuinely hard)

Output: CSV to stdout-adjacent path, plus a per-tier summary.
Read-only with respect to all datasets; writes one CSV under the experiment dir.
"""
import csv
import json
import os
import re
from collections import Counter

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
LR = os.path.expanduser(
    "~/ofs/user/jasperchen/experiments/qwen35_9b_1335_1052_labelrefresh_20260723"
)
OUT = os.path.expanduser("~/ofs/user/jasperchen/experiments/label_conflict_review_20260726")
LABELS = ["误触发", "正确触发", "无需协助"]


def load_full(path):
    """id -> (label, reason)"""
    m = {}
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            last = d["conversations"][-1]
            v = last.get("content") or last.get("value", "")
            lab, reason = None, ""
            try:
                obj = json.loads(v)
                lab, reason = obj.get("label"), str(obj.get("reason", ""))
            except Exception:
                lab = next((L for L in LABELS if L in v), None)
            m[d["id"]] = (lab, reason)
    return m


full = load_full(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl")
gt = {k: v[0] for k, v in full.items()}
reason = {k: v[1] for k, v in full.items()}

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
ids = sorted(set.intersection(*(set(runs[s]) for s in steps)) & set(gt))

rows = []
for i in ids:
    preds = [runs[s][i] for s in steps]
    if any(p == gt[i] for p in preds):
        continue  # solved by at least one checkpoint
    c = Counter(preds)
    modal, modal_n = c.most_common(1)[0]
    frac = modal_n / len(preds)
    if len(c) == 1:
        tier = "T1_unanimous"
    elif frac >= 0.8:
        tier = "T2_dominant"
    else:
        tier = "T3_mixed"
    rows.append(
        {
            "issue_id": i,
            "tier": tier,
            "gt_label": gt[i],
            "model_label": modal,
            "model_agreement": f"{modal_n}/{len(preds)}",
            "agreement_frac": f"{frac:.2f}",
            "distinct_wrong_labels": len(c),
            "gt_reason": reason.get(i, "")[:200],
        }
    )

order = {"T1_unanimous": 0, "T2_dominant": 1, "T3_mixed": 2}
rows.sort(key=lambda r: (order[r["tier"]], r["gt_label"], r["issue_id"]))

os.makedirs(OUT, exist_ok=True)
path = f"{OUT}/never_solved_label_conflicts_0508.csv"
with open(path, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"# checkpoints used: {steps}")
print(f"# never-solved cases exported: {len(rows)}")
print(f"# written to: {path}\n")

print("## tier x (gt -> model) breakdown")
t = Counter((r["tier"], r["gt_label"], r["model_label"]) for r in rows)
for k, v in sorted(t.items(), key=lambda kv: (order[kv[0][0]], -kv[1])):
    print(f"   {k[0]:14s} gt={k[1]:5s} -> model={k[2]:5s}: {v:>3}")

print("\n## tier totals")
for k, v in sorted(Counter(r["tier"] for r in rows).items(), key=lambda kv: order[kv[0]]):
    print(f"   {k}: {v}")

print("\n## T1 unanimous, GT=误触发 model=正确触发  (largest single conflict bucket)")
t1 = [r for r in rows if r["tier"] == "T1_unanimous" and r["gt_label"] == "误触发"
      and r["model_label"] == "正确触发"]
print(f"   count={len(t1)}")
print("   first 30 issue ids for human review:")
for chunk_start in range(0, min(30, len(t1)), 10):
    print("     " + " ".join(r["issue_id"] for r in t1[chunk_start:chunk_start + 10]))
print("\n   sample GT reasons (what the label says):")
for r in t1[:8]:
    print(f"     {r['issue_id']}: {r['gt_reason'][:110]}")
