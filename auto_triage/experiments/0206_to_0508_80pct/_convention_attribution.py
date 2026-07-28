#!/usr/bin/env python3
"""How much of ckpt-110's 0508 error is explained by the 0206->0508 labelling
convention flip, versus by genuine rarity of a pattern in training?

This separates two very different fixes:
  - CONVENTION FLIP  : the same reason pattern carries a different majority
                       label in the two corpora. Upsampling CANNOT fix this;
                       only relabelling / convention alignment can.
  - RARITY           : the pattern is labelled the same way in both, but is
                       scarce in 0206. Upsampling CAN help here.

For each error made by ckpt-110 on 0508, attribute it to whichever bucket its
reason pattern falls in, and report how many accuracy points each fix could
address at most.

Read-only, diagnostic.
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

PATTERNS = {
    "queuing": re.compile(r"排队"),
    "lead_left": re.compile(r"前车驶离"),
    "self_unstuck": re.compile(r"自行脱困|自行恢复|自行解除"),
    "human_takeover": re.compile(r"人工接管"),
    "path_issue": re.compile(r"路径下发|kFollowPath"),
    "yield": re.compile(r"让行"),
}


def load(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            last = d["conversations"][-1]
            v = last.get("content") or last.get("value", "")
            try:
                o = json.loads(v)
                out[d["id"]] = (o.get("label"), str(o.get("reason", "")))
            except Exception:
                out[d["id"]] = (next((L for L in LABELS if L in v), None), "")
    return out


tr = load(f"{DS}/release20260206_1335_v2_relabel_exclude7/dataset/train.jsonl")
te = load(f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl")


def majority(corpus, rx):
    sub = [l for _, (l, r) in corpus.items() if rx.search(r)]
    if not sub:
        return None, 0, 0.0
    c = Counter(sub)
    lab, k = c.most_common(1)[0]
    return lab, len(sub), k / len(sub)


print("## per-pattern majority label in each corpus")
print(f"{'pattern':<16} {'0206 train':<28} {'0508':<28} verdict")
verdict = {}
for p, rx in PATTERNS.items():
    a, na, fa = majority(tr, rx)
    b, nb, fb = majority(te, rx)
    if a and b and a != b:
        v = "CONVENTION FLIP"
    elif a and b and na / max(1, len(tr)) * 3 < nb / max(1, len(te)):
        v = "rarity"
    else:
        v = "consistent"
    verdict[p] = v
    print(
        f"{p:<16} {str(a)+f' {fa:.0%} (n={na})':<28} "
        f"{str(b)+f' {fb:.0%} (n={nb})':<28} {v}"
    )

# ckpt-110 predictions
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
ids = sorted(set(ck) & set(te))
n = len(ids)
errs = [i for i in ids if ck[i] != te[i][0]]
print(f"\n## ckpt-110: {len(errs)} errors / {n} = acc {1-len(errs)/n:.4f}")

# attribute each error
attr = Counter()
flip_hit = Counter()
for i in errs:
    rs = te[i][1]
    tags = [p for p, rx in PATTERNS.items() if rx.search(rs)]
    if not tags:
        attr["no_pattern"] += 1
        continue
    # priority: a flip tag dominates the attribution
    flips = [t for t in tags if verdict[t] == "CONVENTION FLIP"]
    if flips:
        attr["convention_flip"] += 1
        for t in flips:
            flip_hit[t] += 1
    elif any(verdict[t] == "rarity" for t in tags):
        attr["rarity"] += 1
    else:
        attr["consistent_pattern"] += 1

print("\n## error attribution")
for k, v in attr.most_common():
    print(f"   {k:<20} {v:>4}  = {v/n*100:>5.2f} accuracy pts")

print("\n## which flipped patterns the convention errors touch")
for k, v in flip_hit.most_common():
    print(f"   {k:<16} {v}")

# Does the model follow the 0206 convention on flipped patterns?
print("\n## on flipped patterns: does the model follow 0206's majority?")
for p, rx in PATTERNS.items():
    if verdict[p] != "CONVENTION FLIP":
        continue
    a, _, _ = majority(tr, rx)
    b, _, _ = majority(te, rx)
    sub = [i for i in ids if rx.search(te[i][1])]
    follows_0206 = sum(1 for i in sub if ck[i] == a)
    follows_0508 = sum(1 for i in sub if ck[i] == b)
    corr = sum(1 for i in sub if ck[i] == te[i][0])
    print(
        f"   {p:<16} n={len(sub):>4}  model says 0206-label({a})={follows_0206:>4}  "
        f"0508-label({b})={follows_0508:>4}  actually correct={corr:>4} ({corr/max(1,len(sub)):.0%})"
    )

print(
    "\n## MAX headroom if convention were aligned (all convention_flip errors fixed): "
    f"{(1-len(errs)/n) + attr['convention_flip']/n:.4f}"
)
print(
    f"## MAX headroom if rarity were fixed by upsampling: "
    f"{(1-len(errs)/n) + attr['rarity']/n:.4f}"
)
