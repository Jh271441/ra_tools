#!/usr/bin/env python3
"""Split the never-solved 0508 cases into review buckets by GT-reason evidence.

The decision-relevant split inside the "model unanimously disagrees with GT"
set is whether the GT reason itself records unstuck-assistance evidence:

  B_assist_evidence : reason mentions 人工接管 / kFollowPath / waypoint / SWAG /
                      倒车 / MRC etc.  Per TRIAGE_DECISION_GUIDE these are
                      正确触发 evidence, so a GT of 误触发 is internally
                      inconsistent -> LABEL is the prime suspect.
  A_normal_traffic  : reason says 排队 / 红灯 / 让行 / 拥堵 etc.  GT of 误触发
                      is consistent -> the MODEL is the prime suspect.
  C_other           : anything else, needs a look.

Read-only apart from writing the review CSVs.
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

# Assistance / unstuck evidence: per the decision guide these support 正确触发.
ASSIST = re.compile(
    r"人工接管|接管|kFollowPath|路径下发|waypoint|WAYPOINT|SWAG|方向键|倒车|MRC|遥控|脱困"
)
# Normal traffic pauses: these support 误触发.
NORMAL = re.compile(r"排队|红灯|拥堵|跟车|让行|道闸|等待|泊入|泊出|掉头|正常")


def load_full(path):
    m = {}
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            last = d["conversations"][-1]
            v = last.get("content") or last.get("value", "")
            try:
                obj = json.loads(v)
                m[d["id"]] = (obj.get("label"), str(obj.get("reason", "")))
            except Exception:
                m[d["id"]] = (next((L for L in LABELS if L in v), None), "")
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
        continue
    c = Counter(preds)
    modal, modal_n = c.most_common(1)[0]
    rs = reason.get(i, "")
    has_assist = bool(ASSIST.search(rs))
    has_normal = bool(NORMAL.search(rs))
    if has_assist:
        bucket = "B_assist_evidence"      # label suspect
    elif has_normal:
        bucket = "A_normal_traffic"       # model suspect
    else:
        bucket = "C_other"
    rows.append(
        {
            "bucket": bucket,
            "issue_id": i,
            "gt_label": gt[i],
            "model_label": modal,
            "agreement": f"{modal_n}/{len(preds)}",
            "has_assist_evidence": int(has_assist),
            "has_normal_traffic": int(has_normal),
            "gt_reason": rs[:220],
        }
    )

order = {"B_assist_evidence": 0, "A_normal_traffic": 1, "C_other": 2}
rows.sort(key=lambda r: (order[r["bucket"]], r["gt_label"], r["issue_id"]))

os.makedirs(OUT, exist_ok=True)
for b in order:
    sub = [r for r in rows if r["bucket"] == b]
    if not sub:
        continue
    p = f"{OUT}/review_{b}.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sub[0].keys()))
        w.writeheader()
        w.writerows(sub)
    print(f"wrote {len(sub):>3} rows -> {p}")

n_all = 1071
print(f"\n## bucket totals (of {len(rows)} never-solved, out of {n_all} cases)")
for b, v in sorted(Counter(r['bucket'] for r in rows).items(), key=lambda kv: order[kv[0]]):
    print(f"   {b:20s} {v:>3}   = {v/n_all*100:.2f} accuracy pts if all were relabelled")

print("\n## B_assist_evidence detail (label is the prime suspect)")
B = [r for r in rows if r["bucket"] == "B_assist_evidence"]
for k, v in Counter((r["gt_label"], r["model_label"]) for r in B).most_common():
    print(f"   gt={k[0]:5s} -> model says {k[1]:5s}: {v}")
print("\n   sample rows:")
for r in B[:12]:
    print(f"     {r['issue_id']}  gt={r['gt_label']:5s} model={r['model_label']:5s}  {r['gt_reason'][:95]}")

print("\n## A_normal_traffic detail (model is the prime suspect)")
A = [r for r in rows if r["bucket"] == "A_normal_traffic"]
for k, v in Counter((r["gt_label"], r["model_label"]) for r in A).most_common():
    print(f"   gt={k[0]:5s} -> model says {k[1]:5s}: {v}")
print("\n   sample rows:")
for r in A[:8]:
    print(f"     {r['issue_id']}  gt={r['gt_label']:5s} model={r['model_label']:5s}  {r['gt_reason'][:95]}")

C = [r for r in rows if r["bucket"] == "C_other"]
if C:
    print(f"\n## C_other ({len(C)}) sample rows")
    for r in C[:8]:
        print(f"     {r['issue_id']}  gt={r['gt_label']:5s} model={r['model_label']:5s}  {r['gt_reason'][:95]}")
