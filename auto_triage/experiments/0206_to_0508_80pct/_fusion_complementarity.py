#!/usr/bin/env python3
"""Complementarity between the pure-LoRA 1335 track and the 27B two-stage track.

Question: can any fusion of the existing systems reach 0.80 on 0508-full, or is
the union ceiling itself below 0.80 (in which case fusion is a dead end and new
training is required)?

Systems:
  A = pure-LoRA 1335 labelrefresh ckpt window {110,130,150} majority vote
      (hard labels recovered from sweep logs)
  B = frozen 27B two-stage candidate (predictions + pairwise probs CSV)

All numbers on release20260508_1071_v2_relabel GT. Fixed, predeclared fusion
rules only; anything selected on 0508 is labelled diagnostic. Read-only.
"""
import csv
import json
import os
import re
from collections import Counter

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
LR = os.path.expanduser("~/ofs/user/jasperchen/experiments/qwen35_9b_1335_1052_labelrefresh_20260723")
TS = os.path.expanduser(
    "~/ofs/user/jasperchen/experiments/qwen35_27b_stage1_1052_realw14_0508split_20260724/"
    "postprocess/global_27b_1052_1335_twostage_dev_selected_0508v2_20260726/global/"
    "selected_predictions_0508_1071.csv"
)
LABELS = ["误触发", "正确触发", "无需协助"]


def load_gt(path):
    m = {}
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            v = d["conversations"][-1].get("content") or d["conversations"][-1].get("value", "")
            try:
                lab = json.loads(v)["label"]
            except Exception:
                lab = next((L for L in LABELS if L in v), None)
            m[d["id"]] = lab
    return m


gt = load_gt(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl")

# --- system A: LoRA vote from logs
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

W = [110, 130, 150]
ids = set.intersection(*(set(runs[c]) for c in W))
A = {}
for i in ids:
    c = Counter(runs[c_][i] for c_ in W)
    top = c.most_common()
    tied = [lab for lab, k in top if k == top[0][1]]
    A[i] = tied[0] if len(tied) == 1 else next(L for L in LABELS if L in tied)

# --- system B: two-stage CSV
B, PB = {}, {}
with open(TS) as fh:
    for r in csv.DictReader(fh):
        B[r["issue_id"]] = r["prediction"]
        PB[r["issue_id"]] = (
            float(r["p_correct_pairwise"] or 0),
            float(r["p_noassist_pairwise"] or 0),
        )

common = sorted(set(A) & set(B) & set(gt))
print(f"n common = {len(common)}")


def acc(pred):
    k = sum(1 for i in common if pred[i] == gt[i])
    return k / len(common), k


aA, kA = acc(A)
aB, kB = acc(B)
print(f"A (LoRA vote {W}):      acc={aA:.4f} ({kA})")
print(f"B (two-stage frozen):   acc={aB:.4f} ({kB})")

# --- complementarity
both = onlyA = onlyB = neither = 0
for i in common:
    ra, rb = A[i] == gt[i], B[i] == gt[i]
    both += ra and rb
    onlyA += ra and not rb
    onlyB += rb and not ra
    neither += not ra and not rb
n = len(common)
print(f"\nboth right {both} ({both/n:.4f})  onlyA {onlyA}  onlyB {onlyB}  neither {neither}")
print(f"UNION CEILING (perfect selector): {(both+onlyA+onlyB)/n:.4f}")
print(f"agreement rate: {sum(1 for i in common if A[i]==B[i])/n:.4f}")
agree = [i for i in common if A[i] == B[i]]
print(f"acc when A==B: {sum(1 for i in agree if A[i]==gt[i])/len(agree):.4f} (n={len(agree)})")
dis = [i for i in common if A[i] != B[i]]
print(f"disagreements: {len(dis)};  A right {sum(1 for i in dis if A[i]==gt[i])}, "
      f"B right {sum(1 for i in dis if B[i]==gt[i])}, neither {sum(1 for i in dis if gt[i] not in (A[i],B[i]))}")

# error mode of each on disagreements
print("\ndisagreement transitions (gt, A, B) top10:")
for k, c in Counter((gt[i], A[i], B[i]) for i in dis).most_common(10):
    print(f"   gt={k[0]} A={k[1]} B={k[2]}: {c}")

# --- fixed predeclared fusion rules (no 0508 tuning)
def score_rule(name, fn):
    pred = {i: fn(i) for i in common}
    a, k = acc(pred)
    d = Counter(pred.values())
    print(f"   {name:44s} acc={a:.4f} ({k})  dist={dict(d)}")


print("\n## fixed fusion rules (predeclared, no 0508 tuning)")
score_rule("R1: B unless A==无需协助 -> 无需协助", lambda i: "无需协助" if A[i] == "无需协助" else B[i])
score_rule("R2: A unless B==误触发 -> 误触发", lambda i: "误触发" if B[i] == "误触发" else A[i])
score_rule("R3: agree->that; else B", lambda i: A[i] if A[i] == B[i] else B[i])
score_rule("R4: agree->that; else A", lambda i: A[i] if A[i] == B[i] else A[i] if True else B[i])
score_rule(
    "R5: agree->that; else stage1-conf gate (p_correct)",
    lambda i: A[i] if A[i] == B[i] else (B[i] if max(PB[i][0], 1 - PB[i][0]) >= 0.8 else A[i]),
)
score_rule(
    "R6: B; but B==正确触发 and A==误触发 -> A",
    lambda i: A[i] if (B[i] == "正确触发" and A[i] == "误触发") else B[i],
)
score_rule(
    "R7: B; but A==正确触发 and B==误触发 -> 正确触发",
    lambda i: "正确触发" if (B[i] == "误触发" and A[i] == "正确触发") else B[i],
)

# --- diagnostic: best possible per-disagreement-cell router (0508-selected, ceiling of rule fusion)
cells = {}
for i in dis:
    key = (A[i], B[i])
    cells.setdefault(key, []).append(i)
best_extra = 0
for key, items in cells.items():
    ra = sum(1 for i in items if A[i] == gt[i])
    rb = sum(1 for i in items if B[i] == gt[i])
    best_extra += max(ra, rb)
base_agree_correct = sum(1 for i in agree if A[i] == gt[i])
print(
    f"\n## DIAGNOSTIC cell-router ceiling (label-selected per (A,B) cell): "
    f"{(base_agree_correct+best_extra)/n:.4f}"
)
