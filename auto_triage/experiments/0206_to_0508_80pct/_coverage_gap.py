#!/usr/bin/env python3
"""Does the 0206 training corpus actually teach the patterns 0508 fails on?

The never-solved 0508 set is dominated by two concrete, trainable defects:
  D1  "正常排队" / queuing  -> GT 误触发, model says 正确触发   (over-triggering)
  D2  "前车驶离" / lead vehicle left -> GT 无需协助, model mislabels
      (post-trigger recovery signal not learned)

If 0206 under-represents these reason patterns relative to 0508, the failures
are a coverage gap that targeted work inside 0206-only can still close, and the
.8077 family ceiling is a property of this recipe, not a hard limit.

Read-only.
"""
import json
import os
import re
from collections import Counter

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
LABELS = ["误触发", "正确触发", "无需协助"]

PATTERNS = {
    "D1_queuing": re.compile(r"排队"),
    "D2_lead_left": re.compile(r"前车驶离"),
    "self_unstuck": re.compile(r"自行脱困|自行恢复|自行解除"),
    "human_takeover": re.compile(r"人工接管"),
    "path_issue": re.compile(r"路径下发|kFollowPath"),
    "red_light": re.compile(r"红灯"),
    "yield": re.compile(r"让行"),
    "congestion": re.compile(r"拥堵|跟车"),
}


def load(path):
    out = {}
    if not os.path.exists(path):
        return out
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


corpora = {
    "0206_train(1062)": f"{DS}/release20260206_1335_v2_relabel_exclude7/dataset/train.jsonl",
    "0206_full(1326)": f"{DS}/release20260206_1335_v2_relabel_exclude7/dataset/full.jsonl",
    "0508_full(1071)": f"{DS}/release20260508_1071_v2_relabel/dataset/full.jsonl",
}

data = {k: load(v) for k, v in corpora.items()}
for k, v in data.items():
    print(f"# {k}: {len(v)} rows")
print()

print("## reason-pattern prevalence (share of corpus)")
name_w = max(len(p) for p in PATTERNS)
hdr = "pattern".ljust(name_w)
for k in corpora:
    hdr += f"  {k:>18}"
print(hdr)
for pname, rx in PATTERNS.items():
    line = pname.ljust(name_w)
    for k in corpora:
        rows = data[k]
        if not rows:
            line += f"  {'--':>18}"
            continue
        c = sum(1 for _, (lab, rs) in rows.items() if rx.search(rs))
        line += f"  {c:>6} ({c/len(rows):>6.1%})"
    print(line)

print("\n## for each pattern, the label distribution it carries")
for pname, rx in PATTERNS.items():
    print(f"\n   [{pname}]")
    for k in corpora:
        rows = data[k]
        if not rows:
            continue
        sub = [lab for _, (lab, rs) in rows.items() if rx.search(rs)]
        if not sub:
            print(f"      {k:>18}: none")
            continue
        c = Counter(sub)
        tot = len(sub)
        parts = "  ".join(f"{L}={c.get(L,0)} ({c.get(L,0)/tot:.0%})" for L in LABELS)
        print(f"      {k:>18}: n={tot:>4}  {parts}")

# The decisive comparison for D1/D2: train-vs-target prevalence ratio
print("\n## coverage gap: 0508 prevalence / 0206_train prevalence")
tr = data["0206_train(1062)"]
te = data["0508_full(1071)"]
if tr and te:
    for pname, rx in PATTERNS.items():
        a = sum(1 for _, (l, r) in tr.items() if rx.search(r)) / len(tr)
        b = sum(1 for _, (l, r) in te.items() if rx.search(r)) / len(te)
        ratio = (b / a) if a else float("inf")
        flag = ""
        if a == 0 and b > 0:
            flag = "   <-- ABSENT from training"
        elif ratio >= 2:
            flag = "   <-- under-represented in training"
        print(f"   {pname:<16} 0206={a:>6.2%}  0508={b:>6.2%}  ratio={ratio:>5.2f}x{flag}")
