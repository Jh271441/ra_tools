"""Read-only historical Trail exclusion inventory, with source fingerprints.

The snapshot supplies search membership only. Current exclusion is always read
from Trail separately. No historical note becomes a proposed reason or a vote.
"""
from hashlib import sha256
import json
from pathlib import Path

from .contracts import ISSUE_ID_RE
from .timed_cache import TimedSingleFlightCache

_SOURCES = (("0508", "reports/0508_rule_review_ui_20261022/HISTORICAL_16.json",
             "reports/0508_gt_update_20260930/trail_snapshot_20260930T040459Z/trail_gt_0508_full1071.jsonl",
             "2026-09-30T04:04:59Z"),)
_cache = TimedSingleFlightCache(ttl_seconds=60, max_entries=16)


def load_historical_trail_exclusions(root, baseline_ids):
    selected = set(baseline_ids)
    def load():
        items, sources = [], []
        for baseline, subset_path, snapshot_path, captured_at in _SOURCES:
            if baseline not in selected:
                continue
            source = {"kind":"historical_trail_snapshot", "baseline_id":baseline,
                      "filename":subset_path, "snapshot_filename":snapshot_path,
                      "captured_at":captured_at, "available":False, "coverage_count":0}
            try:
                if max((Path(root) / subset_path).stat().st_size, (Path(root) / snapshot_path).stat().st_size) > 16 * 1024 * 1024:
                    raise ValueError("Source too large")
                subset_bytes = (Path(root) / subset_path).read_bytes()
                snapshot_bytes = (Path(root) / snapshot_path).read_bytes()
                if max(len(subset_bytes),len(snapshot_bytes)) > 16 * 1024 * 1024:
                    raise ValueError("Source too large")
                subset = json.loads(subset_bytes)
                snapshot = [json.loads(line) for line in snapshot_bytes.splitlines() if line.strip()]
                if not isinstance(subset,list) or not subset:
                    raise ValueError("Invalid historical inventory")
                if any(not isinstance(row, dict) for row in subset + snapshot):
                    raise ValueError("Invalid source row")
                ids = [row.get("issue_id") for row in subset]
                historical_ids = {row["issue_id"] for row in snapshot if row.get("should_exclude") is True}
                if len(ids) != len(set(ids)) or set(ids) != historical_ids or any(
                    not isinstance(issue,str) or not ISSUE_ID_RE.fullmatch(issue) for issue in ids
                ) or any(row.get("should_exclude") is not True for row in subset):
                    raise ValueError("Historical membership mismatch")
                source.update(available=True,coverage_count=len(ids),snapshot_population=len(snapshot),
                              sha256=sha256(subset_bytes).hexdigest(),snapshot_sha256=sha256(snapshot_bytes).hexdigest())
                for row in subset:
                    items.append({"issue_id":row["issue_id"],"baseline_id":baseline,
                                  "source":dict(source),"historical_excluded":True})
            except (OSError,ValueError,TypeError,KeyError):
                source["error"]="Historical source missing or inconsistent"
            sources.append(source)
        return {"items":items,"sources":sources,"available":any(s["available"] for s in sources)}
    return _cache.get_or_load((str(root),tuple(sorted(selected))),load)


def merge_reconciliation_items(local_items, historical_items, evidence):
    merged = {(item.get("baseline_id", ""), item["issue_id"]): {
        **item, "local_selected":True, "readonly":False, "source_kind":"local",
        "row_key":f'{item.get("baseline_id", "")}|{item["issue_id"]}',
    } for item in local_items}
    for historical in historical_items:
        issue, baseline = historical["issue_id"], historical["baseline_id"]
        key = (baseline,issue)
        current = merged.get(key)
        if current:
            current.update(source_kind="both", historical_source=historical["source"], local_evidence=evidence.get(issue, {}))
            continue
        local = evidence.get(issue, {})
        merged[key] = {"issue_id":issue,"baseline_id":baseline,"row_key":f"{baseline}|{issue}",
            "local_selected":local.get("local_excluded"),"readonly":True,"source_kind":"historical",
            "historical_source":historical["source"],"local_evidence":local,
            "comment":"", "trail_update_status":"querying", "reason_source":{},
            "title":local.get("title", ""),"review":{},"model":{}}
    return list(sorted(merged.values(),key=lambda item:(item["baseline_id"],item["issue_id"])))
