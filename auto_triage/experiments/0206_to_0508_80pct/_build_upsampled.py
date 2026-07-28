#!/usr/bin/env python3
"""Build 0206-only training sets that upsample the assistance-evidence patterns.

Rationale (from _convention_attribution.py): 90 of ckpt-110's 283 errors on
0508 sit on patterns that carry the SAME label in both corpora but are almost
absent from 0206 training:

    路径下发/kFollowPath   0206 1.3%  vs  0508 28.1%
    人工接管               0206 3.3%  vs  0508 33.9%

Fixing that rarity bounds out at 0.8198 accuracy. This builds several upsample
factors so the factor itself can be chosen on the 0206 source-val split, never
on 0508.

Val and test splits are left untouched: they are the selection and held-out
sets and must keep the native 0206 distribution.

Honest caveat recorded in the manifest: only ~40 unique rows carry these
patterns, so a high factor risks memorising them rather than learning the
pattern. That is exactly why several factors are produced and swept.
"""
import hashlib
import json
import os
import re
import shutil

DS = os.path.expanduser("~/ofs/dataset/stuck_auto_triage_vlm_finetune_dataset")
SRC = f"{DS}/release20260206_1335_v2_relabel_exclude7/dataset"
OUT_ROOT = os.path.expanduser(
    "~/ofs/user/jasperchen/experiments/qwen35_9b_1335_assist_upsample_20260726"
)
LABELS = ["误触发", "正确触发", "无需协助"]

ASSIST = re.compile(r"人工接管|路径下发|kFollowPath")
FACTORS = [3, 6, 10]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def label_reason(row):
    last = row["conversations"][-1]
    v = last.get("content") or last.get("value", "")
    try:
        o = json.loads(v)
        return o.get("label"), str(o.get("reason", ""))
    except Exception:
        return next((L for L in LABELS if L in v), None), ""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


train = read(f"{SRC}/train.jsonl")
val = read(f"{SRC}/val.jsonl")
test = read(f"{SRC}/test.jsonl")

marked = []
for r in train:
    lab, rs = label_reason(r)
    marked.append((r, lab, bool(ASSIST.search(rs))))

assist_rows = [m for m in marked if m[2]]
print(f"# 0206 train rows: {len(train)}")
print(f"# rows carrying assistance evidence: {len(assist_rows)} "
      f"({len(assist_rows)/len(train):.2%})")
from collections import Counter
print(f"# their label distribution: {dict(Counter(m[1] for m in assist_rows))}")
print(f"# 0508 target prevalence for these patterns: ~28-34%\n")

os.makedirs(OUT_ROOT, exist_ok=True)
manifest = {
    "contract": (
        "0206-only assistance-pattern upsampling. Only train.jsonl is modified; "
        "val/test keep the native 0206 distribution. Upsample factor must be "
        "selected on 0206 source-val, never on 0508."
    ),
    "source_dataset": SRC,
    "source_train_rows": len(train),
    "assist_pattern": "人工接管|路径下发|kFollowPath",
    "assist_rows": len(assist_rows),
    "assist_share_original": round(len(assist_rows) / len(train), 4),
    "assist_label_counts": dict(Counter(m[1] for m in assist_rows)),
    "caveat": (
        f"only {len(assist_rows)} unique rows carry the pattern; high factors risk "
        "memorisation rather than pattern learning, hence the factor sweep"
    ),
    "variants": {},
}

for f in FACTORS:
    out_dir = f"{OUT_ROOT}/data_assist_x{f}/dataset"
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for r, lab, is_assist in marked:
        rows.append(r)
        if is_assist:
            rows.extend([r] * (f - 1))
    p = f"{out_dir}/train.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for name, data in (("val", val), ("test", test)):
        q = f"{out_dir}/{name}.jsonl"
        with open(q, "w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    share = len(assist_rows) * f / len(rows)
    manifest["variants"][f"x{f}"] = {
        "train_rows": len(rows),
        "assist_share": round(share, 4),
        "train_sha256": sha256(p),
        "label_counts": dict(Counter(label_reason(r)[0] for r in rows)),
    }
    print(f"x{f}: train={len(rows):>5} rows, assist share {share:.1%}, "
          f"labels {dict(Counter(label_reason(r)[0] for r in rows))}")

with open(f"{OUT_ROOT}/manifest.json", "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
print(f"\nwrote manifest -> {OUT_ROOT}/manifest.json")
