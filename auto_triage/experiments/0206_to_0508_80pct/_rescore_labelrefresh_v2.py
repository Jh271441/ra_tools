#!/usr/bin/env python3
"""Rescore the 2026-07-23 paired labelrefresh checkpoints against the v2 0508 GT.

The sweep logs contain per-sample lines:
    ... id=cn32020661  gt=误触发  pred=误触发
grouped per checkpoint by the '评估结果 → .../checkpoint-N.json' marker.
The stored metrics JSONs were computed on the v1 te_priority GT; here we
rebuild each checkpoint's predictions from the log and score them against the
newer release20260508_1071_v2_relabel GT so the numbers are comparable with
the current two-stage canonical.

Read-only.
"""
import json
import os
import re
from collections import Counter, defaultdict

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


gt_v2 = load_gt(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl")
gt_v1 = load_gt(f"{DS}/release20260508_1071_v1_te_priority/dataset/full.jsonl")

SAMPLE = re.compile(r"id=(\S+)\s+gt=(\S+)\s+pred=(\S+)")
RESULT = re.compile(r"评估结果 → \S*/(eval_0508/[^/]+)/checkpoint-(\d+)\.json")

runs = {}  # (track, ckpt) -> {id: pred}
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
            if r:
                track = r.group(1).split("/")[-1]
                key = (track, int(r.group(2)))
                if len(cur) >= 1000:
                    runs[key] = dict(cur)
                cur = {}

print(f"# recovered checkpoint prediction sets: {len(runs)}")
for k in sorted(runs):
    print(f"   {k[0]} ckpt-{k[1]}: n={len(runs[k])}")


def score(preds, gt):
    pairs = [(gt[i], p) for i, p in preds.items() if i in gt]
    n = len(pairs)
    correct = sum(1 for g, p in pairs if g == p)
    sup, pc, tp = Counter(), Counter(), Counter()
    for g, p in pairs:
        sup[g] += 1
        pc[p] += 1
        if g == p:
            tp[g] += 1
    f1s, recs = [], []
    per = {}
    for L in LABELS:
        prec = tp[L] / pc[L] if pc[L] else 0
        rec = tp[L] / sup[L] if sup[L] else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        per[L] = (prec, rec, f1, sup[L])
        f1s.append(f1)
        recs.append(rec)
    return {
        "n": n,
        "acc": correct / n if n else 0,
        "correct": correct,
        "mf1": sum(f1s) / 3,
        "mrec": sum(recs) / 3,
        "per": per,
    }


print("\n## v1 GT (te_priority, original sweep metric) vs v2 GT (relabel)")
print(f"{'track':34s} {'ckpt':>5} {'acc_v1':>7} {'acc_v2':>7} {'mF1_v2':>7} {'mRec_v2':>8} {'n':>5}")
table = []
for (track, ck), preds in sorted(runs.items()):
    s1 = score(preds, gt_v1)
    s2 = score(preds, gt_v2)
    table.append((track, ck, s1, s2, preds))
    print(
        f"{track:34s} {ck:>5} {s1['acc']:>7.4f} {s2['acc']:>7.4f} "
        f"{s2['mf1']:>7.4f} {s2['mrec']:>8.4f} {s2['n']:>5}"
    )

best = max(table, key=lambda r: r[3]["acc"])
track, ck, s1, s2, preds = best
print(f"\n## best under v2 GT: {track} ckpt-{ck}  acc={s2['acc']:.4f} ({s2['correct']}/{s2['n']})")
for L in LABELS:
    prec, rec, f1, sup = s2["per"][L]
    print(f"   {L}: P={prec:.4f} R={rec:.4f} F1={f1:.4f} n={sup}")
print(f"   pred dist: {dict(Counter(preds.values()))}")
