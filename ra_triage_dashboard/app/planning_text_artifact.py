"""Small, independently verifiable outputs from original road PlanningDebug.

This module does not open Bags, run a planner, or write an application database.
Workers and the single-writer importer share this versioned artifact contract.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re

from .planning_constraints import SOURCE, VERSION

ARTIFACT_VERSION = 1
MAX_BYTES = 2 * 1024**2
HEX = re.compile(r"[0-9a-f]{64}")
OBJECT_PREFIX = "all_data/value_files/planning_text_v1/"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def identity(member):
    iid, trip, anchor = (member.get(k) for k in ("issue_id", "trip_id", "anchor_ms"))
    if (not isinstance(iid, str) or not re.fullmatch(r"cn[0-9]{1,20}", iid)
            or not isinstance(trip, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", trip)
            or type(anchor) is not int or not 0 < anchor <= 9223372016854):
        raise ValueError("invalid_planning_identity")
    raw = json.dumps([iid, trip, anchor, -20000, 20000, VERSION], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def object_key(member, job_id, task_id, task_version):
    """A task attempt owns one immutable, directly discoverable small result."""
    if (any(type(value) is not int or value <= 0 for value in (job_id, task_id))
            or type(task_version) is not int or task_version < 0):
        raise ValueError("invalid_planning_native_identity")
    return f"{OBJECT_PREFIX}{job_id}/{task_id}_v{task_version}/{identity(member)}.tgz"


def _frame(value, ns):
    if (not isinstance(value, dict) or value.get("timestamp_ms") != ns // 1000000
            or type(value.get("planning_timestamp_ms")) is not int
            or value.get("status") not in {"ready", "no_constraint", "unresolved"}
            or not isinstance(value.get("raw"), str) or len(value["raw"]) > 16384):
        raise ValueError("invalid_planning_frame")
    cid = value.get("constraint_id")
    if ((value["status"] == "ready" and (not isinstance(cid, str) or not cid))
            or (value["status"] != "ready" and cid is not None)):
        raise ValueError("invalid_planning_constraint")
    obj = value.get("object_id")
    if obj is not None and (type(obj) is not int or abs(obj) > 9007199254740991):
        raise ValueError("invalid_planning_object")
    if len(json.dumps(value, ensure_ascii=False).encode()) > 32768:
        raise ValueError("oversized_planning_frame")


def build_result(member, observations, *, errors=()):
    key = identity(member)
    version, datasets = member.get("version"), member.get("datasets")
    if (not isinstance(version, str) or not re.fullmatch(r"(?:20)?[0-9]{4,6}", version)
            or not isinstance(datasets, list) or len(datasets) > 100
            or any(not isinstance(d, str) or len(d) > 200 for d in datasets)):
        raise ValueError("invalid_planning_membership")
    if len(observations) > 2000 or len(errors) > 100:
        raise ValueError("oversized_planning_observations")
    anchor = member["anchor_ms"]
    unique = {}
    for observation in observations:
        stamp = observation.get("publish_ns")
        if not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{1,19}", stamp):
            raise ValueError("invalid_planning_native_time")
        ns = int(stamp)
        if ns > 9223372036854775807:
            raise ValueError("invalid_planning_native_time")
        if not (anchor - 20150) * 1000000 <= ns < (anchor + 20000) * 1000000:
            raise ValueError("planning_message_outside_window")
        if (not HEX.fullmatch(str(observation.get("raw_sha256", "")))
                or not HEX.fullmatch(str(observation.get("schema_sha256", "")))
                or type(observation.get("raw_bytes")) is not int or observation["raw_bytes"] < 4):
            raise ValueError("invalid_planning_message_fingerprint")
        if ns in unique:
            if unique[ns] != observation:
                raise ValueError("conflicting_planning_native_time")
            continue
        decode = observation.get("decode")
        if decode == "passed":
            if observation.get("full_protobuf_decode") is not True:
                raise ValueError("planning_full_decode_required")
            _frame(observation.get("frame"), ns)
        elif decode != "failed" or observation.get("frame") is not None:
            raise ValueError("invalid_planning_decode_state")
        unique[ns] = observation
    ordered = [unique[stamp] for stamp in sorted(unique)]
    frames, gaps = [], []
    failures = [dict(e) for e in errors]
    cursor = anchor - 20000
    for index, observation in enumerate(ordered):
        ns = int(observation["publish_ns"])
        published = ns // 1000000
        if observation["decode"] == "failed":
            failures.append({"publish_ns": str(ns), "code": "source_message_decode_failed"})
            continue
        # A later damaged observation ends the previous frame's validity.
        # Never carry an old constraint across a known decode failure.
        next_ms = (int(ordered[index + 1]["publish_ns"]) // 1000000
                   if index + 1 < len(ordered) else anchor + 20000)
        end = min(published + 150, next_ms, anchor + 20000)
        frame = {**observation["frame"], "publish_ns": str(ns),
                 "source_message_sha256": observation["raw_sha256"],
                 "source_schema_sha256": observation["schema_sha256"],
                 "valid_until_ms": end}
        frames.append(frame)
        if published > cursor:
            gaps.append([cursor - anchor, published - anchor])
        cursor = max(cursor, end)
    if cursor < anchor + 20000:
        gaps.append([cursor - anchor, 20000])
    t0 = [f for f in frames if f["timestamp_ms"] <= anchor < f["valid_until_ms"]]
    return {"schema_version": ARTIFACT_VERSION, "capture_key": key,
            **{k: member[k] for k in ("issue_id", "trip_id", "anchor_ms", "version", "datasets")},
            "source": SOURCE, "extractor_version": VERSION, "source_kind": "road",
            "simulation_run": False, "input_stage": "original_before_reduction",
            "start_offset_ms": -20000, "end_offset_ms": 20000,
            "duration_ms": 40000, "event_time_sec": 20,
            "frames": frames, "frame_count": len(frames), "observation_count": len(ordered),
            "frame_statuses": dict(Counter(f["status"] for f in frames)),
            "gaps_ms": gaps, "t0": t0[-1] if t0 else None,
            "errors": failures, "worker_errors": list(errors),
            "extraction_status": "failed" if failures else "partial_source" if gaps else "collected"}


def load_artifact(folder, expected=None):
    """Check all bytes, native sequence, classification, coverage and t0."""
    root = Path(folder).resolve()

    def document(name, limit=MAX_BYTES):
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError("invalid_planning_artifact_file")
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("planning_artifact_changed")
        return raw

    receipt_raw = document("receipt.json", 65536)
    receipt = json.loads(receipt_raw)
    if (receipt.get("status") != "verified" or receipt.get("schema_version") != ARTIFACT_VERSION
            or not isinstance(receipt.get("producer"), dict)
            or set(receipt.get("files", {})) != {"frames.jsonl", "result.json"}):
        raise ValueError("invalid_planning_receipt")
    files = {}
    for name, entry in receipt["files"].items():
        raw = document(name)
        if entry != {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}:
            raise ValueError("planning_artifact_sha_mismatch")
        files[name] = raw
    result = json.loads(files["result.json"])
    observations = [json.loads(line) for line in files["frames.jsonl"].splitlines()]
    if expected is not None and any(result.get(k) != expected.get(k)
                                    for k in ("issue_id", "trip_id", "anchor_ms", "version", "datasets")):
        raise ValueError("planning_artifact_identity_mismatch")
    checked = build_result(result, observations, errors=result.get("worker_errors", ()))
    if result != checked or receipt.get("capture_key") != checked["capture_key"]:
        raise ValueError("planning_artifact_audit_mismatch")
    return result, receipt, hashlib.sha256(receipt_raw).hexdigest()


def write_artifact(folder, member, observations, producer, *, errors=()):
    """Publish a complete small artifact by directory rename, before reduction."""
    destination = Path(folder)
    result = build_result(member, observations, errors=errors)
    if destination.exists():
        previous, receipt, _ = load_artifact(destination, member)
        if previous != result or receipt["producer"] != producer:
            raise ValueError("planning_artifact_conflict")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".planning-", dir=destination.parent) as tmp:
        staging = Path(tmp) / "artifact"
        staging.mkdir(mode=0o700)
        content = {
            "frames.jsonl": b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n" for row in observations),
            "result.json": json.dumps(result, ensure_ascii=False, sort_keys=True).encode() + b"\n",
        }
        if any(len(raw) > MAX_BYTES for raw in content.values()):
            raise ValueError("oversized_planning_artifact")
        receipt = {"schema_version": ARTIFACT_VERSION, "capture_key": result["capture_key"],
                   "status": "verified", "producer": producer,
                   "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                             for name, raw in content.items()}}
        content["receipt.json"] = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode() + b"\n"
        if len(content["receipt.json"]) > 65536:
            raise ValueError("oversized_planning_receipt")
        for name, raw in content.items():
            with (staging / name).open("xb") as stream:
                os.chmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        load_artifact(staging, member)
        staging.rename(destination)
        fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return destination
