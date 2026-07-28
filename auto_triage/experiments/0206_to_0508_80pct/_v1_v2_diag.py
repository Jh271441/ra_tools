#!/usr/bin/env python3
"""Why isn't v2-relabel better than v1 for pure 3-class LoRA?

Two confounds must be separated before concluding the model regressed:
  (A) the 0508 EVAL GT changed (v1_te_priority -> v2_relabel), so old and new
      accuracies are not measured against the same answer key;
  (B) the 0206 TRAIN labels changed.

This quantifies both, and hunts for the historical ~.66 pure-3-class result.
Read-only.
"""
import collections
import glob
import json
import os

OFS = os.path.expanduser("~/ofs")
DS = f"{OFS}/dataset/stuck_auto_triage_vlm_finetune_dataset"
LABELS = ["误触发", "正确触发", "无需协助"]


def load_labels(path):
    """id -> label, tolerant of the conversations schema."""
    m = {}
    try:
        with open(path) as fh:
            for line in fh:
                d = json.loads(line)
                conv = d.get("conversations")
                if not conv:
                    continue
                last = conv[-1]
                v = last.get("content") or last.get("value", "")
                try:
                    lab = json.loads(v).get("label")
                except Exception:
                    lab = next((L for L in LABELS if L in v), None)
                if d.get("id"):
                    m[d["id"]] = lab
    except FileNotFoundError:
        return None
    return m


def find_split(root):
    """Collect id->label across whatever splits exist under a release dir."""
    out = {}
    for pat in ("dataset/full.jsonl", "dataset/*.jsonl", "*.jsonl"):
        for p in sorted(glob.glob(os.path.join(root, pat))):
            if os.path.basename(p).startswith("_"):
                continue
            m = load_labels(p)
            if m:
                out.update(m)
        if out:
            break
    return out


print("=" * 78)
print("A. 0508 EVAL GT: v1_te_priority  vs  v2_relabel")
print("=" * 78)
v1 = find_split(f"{DS}/release20260508_1071_v1_te_priority")
v2 = find_split(f"{DS}/release20260508_1071_v2_relabel")
print(f"v1 n={len(v1)}  dist={dict(collections.Counter(v1.values()))}")
print(f"v2 n={len(v2)}  dist={dict(collections.Counter(v2.values()))}")
common = set(v1) & set(v2)
diff = [(i, v1[i], v2[i]) for i in common if v1[i] != v2[i]]
print(f"common={len(common)}  changed={len(diff)}  ({len(diff)/max(1,len(common))*100:.1f}%)")
print("transitions v1 -> v2:")
for k, c in collections.Counter((a, b) for _, a, b in diff).most_common():
    print(f"   {k[0]:5s} -> {k[1]:5s} : {c}")
print(
    "\n>> Any accuracy measured on v1 GT is NOT comparable to one measured on v2 GT."
)

print()
print("=" * 78)
print("B. 0206 TRAIN labels: v1_humanreason vs v2_relabel")
print("=" * 78)
t1 = find_split(f"{DS}/release20260206_1052_v1_humanreason")
t2 = find_split(f"{DS}/release20260206_1052_v2_relabel_exclude7_fixedsplit")
t3 = find_split(f"{DS}/release20260206_1335_v2_relabel_exclude7")
print(f"0206 1052 v1        n={len(t1)} dist={dict(collections.Counter(t1.values()))}")
print(f"0206 1052 v2 relabel n={len(t2)} dist={dict(collections.Counter(t2.values()))}")
print(f"0206 1335 v2 relabel n={len(t3)} dist={dict(collections.Counter(t3.values()))}")
c12 = set(t1) & set(t2)
d12 = [(i, t1[i], t2[i]) for i in c12 if t1[i] != t2[i]]
print(f"\n1052 common={len(c12)} changed={len(d12)} ({len(d12)/max(1,len(c12))*100:.1f}%)")
for k, c in collections.Counter((a, b) for _, a, b in d12).most_common():
    print(f"   {k[0]:5s} -> {k[1]:5s} : {c}")

print()
print("=" * 78)
print("C. Hunt every full-1071 3-class result in 0.60-0.70, any GT version")
print("=" * 78)
hits = []
for root in (f"{OFS}/user/jasperchen", f"{OFS}/../stuck_auto_triage_vlm"):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        continue
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in ("__pycache__", "model", "images", "checkpoint")
        ]
        depth = dirpath[len(root) :].count(os.sep)
        if depth > 6:
            dirnames[:] = []
            continue
        for fn in filenames:
            if not fn.endswith(".json"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 4_000_000:
                    continue
                obj = json.load(open(p))
            except Exception:
                continue

            def scan(o, path=""):
                if isinstance(o, dict):
                    acc = o.get("accuracy")
                    n = o.get("n")
                    cm = o.get("confusion_matrix")
                    if (
                        isinstance(acc, float)
                        and n == 1071
                        and isinstance(cm, list)
                        and len(cm) == 3
                        and 0.58 <= acc <= 0.72
                    ):
                        hits.append((acc, o.get("macro_f1"), p, path))
                    for k, v in o.items():
                        scan(v, path + "/" + str(k))
                elif isinstance(o, list):
                    for idx, v in enumerate(o[:60]):
                        scan(v, path + f"[{idx}]")

            scan(obj)

hits.sort(reverse=True)
seen = set()
print(f"{'acc':>7} {'mF1':>7}  file :: key")
for acc, mf1, p, key in hits:
    sig = (round(acc, 5), p)
    if sig in seen:
        continue
    seen.add(sig)
    mf1s = "%.4f" % mf1 if isinstance(mf1, float) else "  ?   "
    print(f"{acc:>7.4f} {mf1s:>7}  {p.replace(OFS,'~ofs')} :: {key}")
print(f"\ntotal distinct 3-class full-1071 results in range: {len(seen)}")
