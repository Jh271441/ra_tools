#!/usr/bin/env python3
"""Decompose the 0508 error budget of the frozen 27B two-stage candidate.

Answers: where do the 265 errors live, and what is the accuracy ceiling if we
fix Stage1 (misfire vs real) alone, Stage2 (correct vs no-assist) alone, or
recalibrate thresholds on the *source* domain only.

Read-only.
"""
import csv
import json
import os
from collections import Counter, defaultdict

BASE = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
G = os.path.expanduser(
    "~/ofs/user/jasperchen/experiments/qwen35_27b_stage1_1052_realw14_0508split_20260724/"
    "postprocess/global_27b_1052_1335_twostage_dev_selected_0508v2_20260726/global"
)
PRED = f"{G}/selected_predictions_0508_1071.csv"
LABELS = ["误触发", "正确触发", "无需协助"]
REAL = {"正确触发", "无需协助"}


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


gt = load_gt(f"{BASE}/release20260508_1071_v2_relabel/dataset/full.jsonl")
rows = list(csv.DictReader(open(PRED)))
print(f"n={len(rows)}  cols={list(rows[0].keys())}\n")

# ---- 1. error decomposition
err = Counter()
for r in rows:
    g, p = gt[r["issue_id"]], r["prediction"]
    if g != p:
        err[(g, p)] += 1
tot_err = sum(err.values())
print(f"## total errors = {tot_err} / {len(rows)}  (acc={1-tot_err/len(rows):.4f})")
for (g, p), c in err.most_common():
    print(f"   GT={g:5s} -> PRED={p:5s} : {c:4d}   ({c/len(rows)*100:.1f} pts of accuracy)")

# ---- 2. stage-wise ceiling
# Stage1 = misfire vs real. Stage2 = correct vs no-assist among predicted-real.
s1_gt = {i: ("误触发" if gt[i] == "误触发" else "real") for i in gt}
s1_pred = {r["issue_id"]: ("误触发" if r["prediction"] == "误触发" else "real") for r in rows}
s1_err = sum(1 for i in s1_pred if s1_gt[i] != s1_pred[i])
print(f"\n## Stage1 (misfire vs real) errors = {s1_err}  acc={1-s1_err/len(rows):.4f}")
c = Counter((s1_gt[i], s1_pred[i]) for i in s1_pred)
for k, v in c.most_common():
    print(f"   {k[0]:6s} -> {k[1]:6s} : {v}")

# oracle Stage1: fix stage1, keep stage2 decision among real
oracle_s1 = 0
for r in rows:
    i = r["issue_id"]
    g = gt[i]
    if g == "误触发":
        oracle_s1 += 1  # oracle routes it correctly
    else:
        # routed to real by oracle; stage2 decides. use model's own correct/noassist call
        p = r["prediction"]
        sub = p if p in REAL else None
        if sub is None:
            # model said misfire; we need stage2's opinion from pairwise score
            pn = float(r.get("p_noassist_pairwise") or 0)
            sub = "无需协助" if pn >= 0.5 else "正确触发"
        oracle_s1 += 1 if sub == g else 0
print(f"\n## ORACLE Stage1 + model Stage2  ->  acc={oracle_s1/len(rows):.4f}")

# oracle Stage2: keep model's misfire/real routing, perfect correct-vs-noassist
oracle_s2 = 0
for r in rows:
    i = r["issue_id"]
    g, p = gt[i], r["prediction"]
    if p == "误触发":
        oracle_s2 += 1 if g == "误触发" else 0
    else:
        oracle_s2 += 1 if g in REAL else 0
print(f"## model Stage1 + ORACLE Stage2  ->  acc={oracle_s2/len(rows):.4f}")

# ---- 3. what if we never predict 无需协助 at all
never_na = sum(
    1
    for r in rows
    if gt[r["issue_id"]] == (r["prediction"] if r["prediction"] != "无需协助" else "正确触发")
)
print(f"\n## collapse 无需协助 -> 正确触发 in predictions: acc={never_na/len(rows):.4f}")

# upper bound if 无需协助 were perfectly recalled without hurting others
na_missed = sum(1 for r in rows if gt[r["issue_id"]] == "无需协助" and r["prediction"] != "无需协助")
print(f"## 无需协助 currently missed: {na_missed}/97  -> recovering all = +{na_missed/len(rows)*100:.1f} pts")

# ---- 4. score availability for a better threshold search
pc = [float(r["p_correct_pairwise"]) for r in rows if r.get("p_correct_pairwise")]
pn = [float(r["p_noassist_pairwise"]) for r in rows if r.get("p_noassist_pairwise")]
print(f"\n## p_correct_pairwise: n={len(pc)} min={min(pc):.3f} max={max(pc):.3f}")
print(f"## p_noassist_pairwise: n={len(pn)} min={min(pn):.3f} max={max(pn):.3f}")

# how separable is 无需协助 by p_noassist among GT-real cases?
real_rows = [r for r in rows if gt[r["issue_id"]] in REAL]
na = sorted(float(r["p_noassist_pairwise"]) for r in real_rows if gt[r["issue_id"]] == "无需协助")
co = sorted(float(r["p_noassist_pairwise"]) for r in real_rows if gt[r["issue_id"]] == "正确触发")


def q(a, p):
    return a[int(p * (len(a) - 1))] if a else float("nan")


print(f"\n## among GT-real (n={len(real_rows)}), p_noassist distribution:")
print(f"   无需协助 (n={len(na)}): p10={q(na,.1):.3f} med={q(na,.5):.3f} p90={q(na,.9):.3f}")
print(f"   正确触发 (n={len(co)}): p10={q(co,.1):.3f} med={q(co,.5):.3f} p90={q(co,.9):.3f}")

# best achievable binary split on this score (diagnostic only, uses labels)
best = (0, None)
for t in [i / 100 for i in range(101)]:
    acc = sum(1 for x in na if x >= t) + sum(1 for x in co if x < t)
    if acc > best[0]:
        best = (acc, t)
print(
    f"   ORACLE threshold on p_noassist: t={best[1]} -> {best[0]}/{len(real_rows)} "
    f"= {best[0]/len(real_rows):.4f} within-real acc (diagnostic, label-selected)"
)
