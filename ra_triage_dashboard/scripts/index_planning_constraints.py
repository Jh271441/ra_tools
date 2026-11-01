"""Build an atomic, derived text index from saved results; never reads Bags.

Output can be staged in an independent directory before activating it as
DASHBOARD_DATA_DIR/planning_constraints/history.sqlite3. Repeat --source-root
to include multiple full memberships; conflicting Issue identities fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.planning_constraints import SOURCE, VERSION
from app.planning_constraint_index import (
    APPLICATION_ID, INDEX_VERSION, MAX_FRAME_BYTES, MAX_FRAMES,
    MAX_INDEX_BYTES, MAX_RESULT_BYTES, TOLERANCE_MS,
)


def document(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Invalid saved file: {path.name}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        raise ValueError("Source changed while reading")
    return json.loads(raw), hashlib.sha256(raw).hexdigest(), after


def validate_result(result, member):
    iid = member["issue_id"]
    if any(result.get(k) != member.get(k) for k in ("issue_id", "version", "datasets")):
        raise ValueError(f"Membership mismatch: {iid}")
    trip, anchor = result.get("trip_id"), result.get("anchor_ms")
    if not isinstance(trip, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", trip):
        raise ValueError(f"Invalid trip: {iid}")
    if type(anchor) is not int or not 0 < anchor <= 9007199254740991:
        raise ValueError(f"Invalid anchor: {iid}")
    # These historical windows are the frozen 40s recipe. Do not infer a
    # different window from a video, old frames, or missing metadata.
    if (result.get("start_offset_ms"), result.get("end_offset_ms"),
            result.get("duration_ms"), result.get("event_time_sec")) != (-20000, 20000, 40000, 20):
        raise ValueError(f"Invalid window: {iid}")
    capture = result.get("capture") or {}
    if capture.get("trip_id") != trip or capture.get("timestamp_ms") != anchor:
        raise ValueError(f"Capture identity mismatch: {iid}")
    frames = result.get("frames")
    if not isinstance(frames, list) or not 0 < len(frames) <= MAX_FRAMES or result.get("frame_count") != len(frames):
        raise ValueError(f"Invalid frame count: {iid}")
    previous = 0
    cursor = anchor - 20000
    gaps, encoded = [], []
    for frame in frames:
        published = frame.get("timestamp_ms")
        if (type(published) is not int or not anchor - 20150 <= published < anchor + 20000
                or published <= previous or type(frame.get("planning_timestamp_ms")) is not int
                or frame.get("status") not in {"ready", "no_constraint", "unresolved"}):
            raise ValueError(f"Invalid frame identity/order: {iid}")
        if not isinstance(frame.get("raw"), str) or len(frame["raw"]) > 16384:
            raise ValueError(f"Invalid raw field: {iid}")
        cid = frame.get("constraint_id")
        if ((frame["status"] == "ready" and (not isinstance(cid, str) or not cid))
                or (frame["status"] != "ready" and cid is not None)):
            raise ValueError(f"Invalid constraint state: {iid}")
        if frame.get("object_id") is not None and (type(frame["object_id"]) is not int or abs(frame["object_id"]) > 9007199254740991):
            raise ValueError(f"Invalid object ID: {iid}")
        raw = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode()) > MAX_FRAME_BYTES:
            raise ValueError(f"Oversized frame: {iid}")
        encoded.append((iid, published, raw))
        if published > cursor:
            gaps.append([cursor - anchor, published - anchor])
        cursor = max(cursor, published + TOLERANCE_MS)
        previous = published
    if cursor < anchor + 20000:
        gaps.append([cursor - anchor, 20000])
    t0 = [f for f in frames if 0 <= anchor - f["timestamp_ms"] <= TOLERANCE_MS]
    errors = result.get("errors")
    if (gaps != result.get("gaps_ms") or result.get("frame_statuses") != dict(Counter(f["status"] for f in frames))
            or result.get("t0") != (t0[-1] if t0 else None) or not isinstance(errors, list)):
        raise ValueError(f"Coverage/t0 audit mismatch: {iid}")
    expected_status = "failed" if errors else "partial_source" if gaps else "collected"
    if result.get("extraction_status") != expected_status:
        raise ValueError(f"Source classification mismatch: {iid}")
    return encoded


def build_index(source_roots, output, expected_membership_sha256=None):
    output = Path(output)
    if output.suffix != ".sqlite3" or output.is_symlink():
        raise ValueError("Output must be a derived .sqlite3 file")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".planning-index-", suffix=".sqlite3", dir=output.parent)
    os.close(fd)
    staged = Path(staged)
    started = time.monotonic()
    sources, input_stats, seen = [], [], {}
    totals = defaultdict(Counter)
    ledger = hashlib.sha256()
    try:
        with closing(sqlite3.connect(staged)) as db:
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={INDEX_VERSION}")
            db.execute(f"PRAGMA max_page_count={MAX_INDEX_BYTES // 4096}")
            db.executescript("""
                CREATE TABLE configuration(id INTEGER PRIMARY KEY CHECK(id=1),
                    extractor_version TEXT NOT NULL, source TEXT NOT NULL, manifest_json TEXT NOT NULL);
                CREATE TABLE issues(issue_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, anchor_ms INTEGER NOT NULL,
                    start_offset_ms INTEGER NOT NULL, end_offset_ms INTEGER NOT NULL, metadata_json TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE frames(issue_id TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, frame_json TEXT NOT NULL,
                    PRIMARY KEY(issue_id,timestamp_ms), FOREIGN KEY(issue_id) REFERENCES issues(issue_id)) WITHOUT ROWID;
            """)
            for root in source_roots:
                root = Path(root).resolve()
                membership_path = root / "membership.json"
                manifest, member_sha, member_stat = document(membership_path, 16 * 1024**2)
                if expected_membership_sha256 and member_sha != expected_membership_sha256:
                    raise ValueError("Unexpected membership file SHA256")
                if manifest.get("extractor_version") != VERSION or manifest.get("source") != SOURCE:
                    raise ValueError("Incompatible membership extractor/source")
                members = manifest.get("issues")
                if not isinstance(members, list) or not 0 < len(members) <= 20000:
                    raise ValueError("Invalid membership size")
                ids = [m.get("issue_id") for m in members]
                if any(not isinstance(iid, str) or not re.fullmatch(r"cn[0-9]{1,20}", iid) for iid in ids) or len(set(ids)) != len(ids):
                    raise ValueError("Invalid/duplicate membership")
                input_stats.append((membership_path, member_stat))
                sources.append({"membership_file_sha256": member_sha,
                                "membership_sha256": manifest.get("membership_sha256"), "member_count": len(members)})
                for member in sorted(members, key=lambda m: m["issue_id"]):
                    iid = member["issue_id"]
                    path = root / "cases" / iid / "result.json"
                    path.resolve().relative_to(root)
                    result, result_sha, result_stat = document(path, MAX_RESULT_BYTES)
                    encoded = validate_result(result, member)
                    if iid in seen:
                        if seen[iid] != result_sha:
                            raise ValueError(f"Conflicting saved Issue: {iid}")
                        continue
                    seen[iid] = result_sha
                    if len(seen) > 20000:
                        raise ValueError("Oversized combined membership")
                    input_stats.append((path, result_stat))
                    meta = {"source_version": result["version"], "source_status": result["extraction_status"],
                            "source_result_sha256": result_sha, "source_membership_sha256": sources[-1]["membership_sha256"],
                            "source_frame_count": len(encoded), "source_gaps_ms": result["gaps_ms"],
                            "source_error_count": len(result["errors"]),
                            "coverage_start_ms": result["anchor_ms"] - 20000, "coverage_end_ms": result["anchor_ms"] + 20000}
                    db.execute("INSERT INTO issues VALUES(?,?,?,?,?,?)", (iid, result["trip_id"], result["anchor_ms"],
                               -20000, 20000, json.dumps(meta, separators=(",", ":"))))
                    db.executemany("INSERT INTO frames VALUES(?,?,?)", encoded)
                    totals[result["version"]].update(issues=1, frames=len(encoded), **{result["extraction_status"]: 1})
                    ledger.update(f"{iid}:{result_sha}\n".encode())
            for path, before in input_stats:
                after = path.stat()
                if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
                    raise ValueError("Source changed during import; index was not activated")
            report = {"schema_version": INDEX_VERSION, "extractor_version": VERSION, "source": SOURCE,
                      "created_at": time.time(), "issues": len(seen), "frames": sum(v["frames"] for v in totals.values()),
                      "versions": dict(totals), "sources": sources, "result_ledger_sha256": ledger.hexdigest()}
            db.execute("INSERT INTO configuration VALUES(1,?,?,?)", (VERSION, SOURCE, json.dumps(report)))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Index integrity check failed")
            actual = db.execute("SELECT COUNT(*),COUNT(DISTINCT issue_id) FROM frames").fetchone()
            if actual != (report["frames"], report["issues"]):
                raise ValueError("Index count audit failed")
        with staged.open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                digest.update(chunk)
            report["sha256"] = digest.hexdigest()
            os.fsync(stream.fileno())
        report.update(bytes=staged.stat().st_size, elapsed_seconds=round(time.monotonic() - started, 3))
        staged.replace(output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return report
    finally:
        staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-membership-sha256")
    args = parser.parse_args()
    print(json.dumps(build_index(args.source_root, args.output, args.expected_membership_sha256), indent=2))


if __name__ == "__main__":
    main()
