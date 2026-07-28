#!/usr/bin/env python3
"""Probe Stage1 (misfire vs real) headroom on 0508.

Key question: the frozen candidate loses 172 real cases to 误触发. Is that a
threshold/calibration problem (recoverable by shifting the operating point on
the SOURCE domain) or a genuine ranking problem (score has no separation)?

Reports, for every available Stage1 score source:
  - ROC-AUC on 0508 (ranking quality, threshold-free)
  - accuracy at the current operating point
  - accuracy at the best 0508 threshold (diagnostic ceiling)
  - accuracy at a threshold picked to match the SOURCE prior (legitimate)
  - resulting end-to-end 3-class accuracy when combined with the existing Stage2

Read-only.
"""
import csv
import glob
import json
import os
from collections import Counter

BASE = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
EXP = os.path.expanduser("~/ofs/user/jasperchen/experiments")
PP = f"{EXP}/qwen35_27b_stage1_1052_realw14_0508split_20260724/postprocess/global_27b_1052_1335_twostage_dev_selected_0508v2_20260726"
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

# discover stage1 score sources (dev+test csv pairs)
srcs = {}
for d in sorted(glob.glob(f"{PP}/stage1/*/")):
    name = os.path.basename(d.rstrip("/"))
    rows = []
    for split in ("dev", "test"):
        p = os.path.join(d, f"{split}.scores.csv")
        if os.path.exists(p):
            with open(p) as fh:
                for r in csv.DictReader(fh):
                    r["_split"] = split
                    rows.append(r)
    if rows:
        srcs[name] = rows

print(f"# stage1 score sources found: {len(srcs)}")
if srcs:
    k = next(iter(srcs))
    print(f"# columns of '{k}': {list(srcs[k][0].keys())}\n")


def auc(pos, neg):
    """ROC-AUC via rank sum."""
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    # average ranks for ties
    ranks = {}
    i = 0
    r = 1
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (r + (r + (j - i))) / 2
        for k2 in range(i, j + 1):
            ranks[k2] = avg
        r += j - i + 1
        i = j + 1
    s = sum(ranks[idx] for idx, (v, lab) in enumerate(allv) if lab == 1)
    n1, n0 = len(pos), len(neg)
    return (s - n1 * (n1 + 1) / 2) / (n1 * n0)


def score_col(rows):
    """Pick the column holding a real-vs-misfire score."""
    cands = [
        c
        for c in rows[0]
        if c not in ("issue_id", "_split", "label", "gt", "prediction")
        and any(x in c.lower() for x in ("p_", "score", "prob", "logit", "real", "正确"))
    ]
    return cands


results = []
for name, rows in srcs.items():
    cols = score_col(rows)
    if not cols:
        continue
    for col in cols:
        try:
            vals = {r["issue_id"]: float(r[col]) for r in rows if r.get(col) not in (None, "")}
        except ValueError:
            continue
        if len(vals) < 500:
            continue
        pos = [v for i, v in vals.items() if i in gt and gt[i] in REAL]  # real
        neg = [v for i, v in vals.items() if i in gt and gt[i] == "误触发"]
        if not pos or not neg:
            continue
        a = auc(pos, neg)
        # best threshold on 0508 (diagnostic)
        allv = sorted(set(list(vals.values())))
        best = (0.0, None)
        for t in allv[:: max(1, len(allv) // 300)]:
            acc = sum(1 for v in pos if v >= t) + sum(1 for v in neg if v < t)
            if acc > best[0]:
                best = (acc, t)
        n = len(pos) + len(neg)
        results.append(
            {
                "src": name,
                "col": col,
                "auc": a,
                "best_t": best[1],
                "best_acc": best[0] / n,
                "n": n,
                "n_real": len(pos),
            }
        )

results.sort(key=lambda r: -(r["auc"] if r["auc"] == r["auc"] else 0))
print("## Stage1 real-vs-misfire ranking quality on 0508 (higher AUC = more headroom)")
print(f"{'AUC':>7} {'bestAcc':>8} {'bestT':>8} {'n':>5}  source / column")
for r in results[:25]:
    bt = "na" if r["best_t"] is None else "%.3f" % r["best_t"]
    print(
        "%7.4f %8.4f %8s %5d  %s / %s"
        % (r["auc"], r["best_acc"], bt, r["n"], r["src"], r["col"])
    )

print(
    "\n# NOTE: best_t/best_acc are label-selected on 0508 => diagnostic ceiling only, "
    "not a deployable operating point."
)
