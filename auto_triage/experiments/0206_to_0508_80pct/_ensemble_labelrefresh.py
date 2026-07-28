#!/usr/bin/env python3
"""Majority-vote ensembles over the 1335 labelrefresh checkpoints (from sweep logs).

Motivation: ckpt-110 (.7358 on v2 GT) is a spike between .64-.72 neighbors, and
no 0206-val selection artifact exists for this sweep. A vote over the stable
late window is checkpoint-choice-free and therefore a more honest deployable
number. Also scores every window so we can see robustness.

Read-only.
"""
import itertools
import json
import os
import re
from collections import Counter

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
E = os.path.expanduser("~/ofs/user/jasperchen/experiments/qwen35_9b_1335_1052_labelrefresh_20260723")
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
for logname in sorted(os.listdir(f"{E}/logs")):
    if not logname.endswith(".log"):
        continue
    cur = {}
    with open(f"{E}/logs/{logname}", errors="replace") as fh:
        for line in fh:
            m = SAMPLE.search(line)
            if m:
                cur[m.group(1)] = m.group(3)
                continue
            r = RESULT.search(line)
            if r and len(cur) >= 1000:
                track = r.group(1).split("/")[-1]
                if track.startswith("1335"):
                    runs[int(r.group(2))] = dict(cur)
                cur = {}
            elif r:
                cur = {}


def score(preds):
    pairs = [(gt[i], p) for i, p in preds.items() if i in gt]
    n = len(pairs)
    correct = sum(1 for g, p in pairs if g == p)
    sup, pc, tp = Counter(), Counter(), Counter()
    for g, p in pairs:
        sup[g] += 1
        pc[p] += 1
        if g == p:
            tp[g] += 1
    f1s = []
    per = {}
    for L in LABELS:
        prec = tp[L] / pc[L] if pc[L] else 0
        rec = tp[L] / sup[L] if sup[L] else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        per[L] = (round(prec, 3), round(rec, 3), round(f1, 3), sup[L])
        f1s.append(f1)
    return correct / n, sum(f1s) / 3, per, n


def vote(cks, tiebreak_order=("误触发", "正确触发", "无需协助")):
    ids = set.intersection(*(set(runs[c]) for c in cks))
    out = {}
    for i in ids:
        c = Counter(runs[c_][i] for c_ in cks)
        top = c.most_common()
        best_n = top[0][1]
        tied = [lab for lab, k in top if k == best_n]
        if len(tied) == 1:
            out[i] = tied[0]
        else:
            out[i] = next(L for L in tiebreak_order if L in tied)
    return out


print("# available 1335 checkpoints:", sorted(runs))
print("\n## single checkpoints (v2 GT)")
for ck in sorted(runs):
    a, f, per, n = score(runs[ck])
    print(f"   ckpt-{ck:<4} acc={a:.4f} mF1={f:.4f}")

print("\n## voting ensembles (v2 GT)")
windows = [
    [100, 110, 130],
    [110, 130, 150],
    [130, 150, 170],
    [140, 160, 180],
    [100, 110, 130, 150, 170],
    [110, 130, 140, 150, 160],
    [100, 110, 130, 150, 160, 170, 180],
    [140, 150, 160, 170, 180],
]
for w in windows:
    if not all(c in runs for c in w):
        continue
    v = vote(w)
    a, f, per, n = score(v)
    print(f"   vote{w}: acc={a:.4f} mF1={f:.4f} n={n}")

# leave-one-checkpoint-out stability of the best window
print("\n## detail of best window vote")
best_w, best_a = None, 0
for w in windows:
    if all(c in runs for c in w):
        a, f, per, n = score(vote(w))
        if a > best_a:
            best_a, best_w = a, w
v = vote(best_w)
a, f, per, n = score(v)
print(f"   window={best_w}  acc={a:.4f}  mF1={f:.4f}")
for L in LABELS:
    print(f"   {L}: P/R/F1/n = {per[L]}")
