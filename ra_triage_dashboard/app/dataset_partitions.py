"""Frozen operational partitions; original source/GT/media scopes never move."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

SOURCE_IDS = ("0821", "0821-review-extra", "0821-trail-extra")
SOURCE_SCOPES = ("release0821_1242_20260908", "manual_sidecar_0821-review-extra", "manual_sidecar_0821-trail-extra")
PARTITION_IDS = ("0821-odd2", "0821-nonodd2")


@lru_cache(maxsize=4)
def _read(path: str, mtime: int, size: int):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema") != "0821-odd-partitions-v1":
        raise ValueError("Invalid 0821 partition schema")
    cohorts = raw.get("partitions", {})
    if set(cohorts) != set(PARTITION_IDS):
        raise ValueError("Incomplete 0821 partitions")
    seen = set()
    result = {}
    for key in PARTITION_IDS:
        ids = cohorts[key]
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i.startswith("cn") for i in ids):
            raise ValueError("Invalid partition members")
        members = frozenset(ids)
        if len(members) != len(ids) or seen.intersection(members):
            raise ValueError("Duplicate or overlapping partition members")
        seen.update(members)
        result[key] = members
    digest = hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest()
    if len(seen) != 2005 or raw.get("membership_sha256") != digest:
        raise ValueError("0821 partition membership mismatch")
    return result


def load_partitions(data_dir):
    path = Path(data_dir) / "dataset_partitions" / "0821.json"
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    return dict(_read(str(path), stat.st_mtime_ns, stat.st_size))


def partition_summaries(partitions):
    return [dict(id=key, label="0821 · ODD2" if key == PARTITION_IDS[0] else "0821 · 非ODD2",
                 label_en="0821 · ODD2" if key == PARTITION_IDS[0] else "0821 · Non-ODD2",
                 scope="partition_" + key, source_scopes=list(SOURCE_SCOPES), source_ids=list(SOURCE_IDS),
                 count=len(partitions[key]), source_rows=len(partitions[key]),
                 loader="membership_partition", operational=True, default_selected=False,
                 status="registered", registration_status="registered", gt_mode="sparse",
                 membership=dict(frozen=True, registered_count=len(partitions[key])))
            for key in PARTITION_IDS if key in partitions]
