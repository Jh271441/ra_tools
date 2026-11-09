"""Single-writer, per-capture daily index; requests never import or read Bags."""
from __future__ import annotations

from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time

from .planning_constraints import SOURCE, VERSION
from .planning_text_artifact import identity, load_artifact

APPLICATION_ID = 0x50434459  # PCDY; independent of the immutable historical index.
INDEX_VERSION = 1


def index_path(data_dir):
    return Path(data_dir) / "planning_constraints" / "daily.sqlite3"


def _initialize(db):
    app_id = db.execute("PRAGMA application_id").fetchone()[0]
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if app_id == 0:
        if version != 0 or db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
            raise ValueError("invalid_daily_planning_index")
    elif app_id != APPLICATION_ID or version != INDEX_VERSION:
        raise ValueError("invalid_daily_planning_index")
    db.execute(f"PRAGMA application_id={APPLICATION_ID}")
    db.execute(f"PRAGMA user_version={INDEX_VERSION}")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS captures(
            capture_key TEXT PRIMARY KEY, issue_id TEXT NOT NULL, trip_id TEXT NOT NULL,
            anchor_ms INTEGER NOT NULL, version TEXT NOT NULL, datasets_json TEXT NOT NULL,
            state TEXT NOT NULL, owner TEXT NOT NULL, receipt_sha256 TEXT,
            metadata_json TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS captures_issue ON captures(issue_id,trip_id,anchor_ms);
        CREATE TABLE IF NOT EXISTS frames(
            capture_key TEXT NOT NULL REFERENCES captures(capture_key),
            timestamp_ms INTEGER NOT NULL, publish_ns INTEGER NOT NULL,
            frame_json TEXT NOT NULL, PRIMARY KEY(capture_key,timestamp_ms,publish_ns)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS receipts(
            receipt_sha256 TEXT PRIMARY KEY, capture_key TEXT NOT NULL,
            state TEXT NOT NULL, imported_at REAL NOT NULL, producer_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS owner_events(
            id INTEGER PRIMARY KEY, capture_key TEXT NOT NULL, from_owner TEXT NOT NULL,
            to_owner TEXT NOT NULL, evidence_json TEXT NOT NULL, transferred_at REAL NOT NULL);
    """)


def _writer(data_dir, operation):
    path = index_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.resolve().relative_to(Path(data_dir).resolve())
    if path.is_symlink():
        raise ValueError("invalid_daily_planning_index")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with (path.parent / "daily-import.lock").open("a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(sqlite3.connect(path, timeout=.5)) as db:
            _initialize(db)
            with db:
                return operation(db)


def register_owner(data_dir, member, owner, *, context=None):
    """Unique capture owner, durable before submitting any original/retry task."""
    key = identity(member)
    if not isinstance(owner, str) or not 0 < len(owner) <= 200:
        raise ValueError("invalid_planning_owner")

    def register(db):
        existing = db.execute("SELECT owner,state FROM captures WHERE capture_key=?", (key,)).fetchone()
        if existing:
            return {"capture_key": key, "owner": existing[0], "state": existing[1], "claimed": existing[0] == owner}
        db.execute("INSERT INTO captures VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            key, member["issue_id"], member["trip_id"], member["anchor_ms"], member["version"],
            json.dumps(member["datasets"]), "pending", owner, None, json.dumps(context or {}), time.time()))
        return {"capture_key": key, "owner": owner, "state": "pending", "claimed": True}
    return _writer(data_dir, register)


def capture_owner(data_dir, member):
    if not index_path(data_dir).exists():
        return None
    with closing(_reader(data_dir)) as db:
        row = db.execute("SELECT owner,state,metadata_json FROM captures WHERE capture_key=?", (identity(member),)).fetchone()
        return dict(owner=row[0], state=row[1], context=json.loads(row[2])) if row else None


def transfer_owner(data_dir, member, previous, owner, context, evidence):
    """CAS only after a completed native attempt has no result at its exact key."""
    if (evidence.get('kind') != 'native_terminal_no_object' or evidence.get('job_state') != 2
            or evidence.get('task_status') not in {3, 4, 5} or evidence.get('missing_confirmed') is not True
            or not isinstance(evidence.get('task_id'), int) or not isinstance(evidence.get('job_id'), int)):
        raise ValueError('planning_owner_transfer_requires_native_evidence')
    def transfer(db):
        key = identity(member)
        row = db.execute("SELECT owner,state,receipt_sha256 FROM captures WHERE capture_key=?", (key,)).fetchone()
        if row != (previous, 'pending', None):
            return False
        db.execute("INSERT INTO owner_events VALUES(NULL,?,?,?,?,?)", (
            key, previous, owner, json.dumps(evidence, sort_keys=True), time.time()))
        db.execute("UPDATE captures SET owner=?,metadata_json=?,updated_at=? WHERE capture_key=?",
                   (owner, json.dumps(context), time.time(), key))
        return True
    return _writer(data_dir, transfer)


def import_artifact(data_dir, folder, expected, owner):
    result, receipt, receipt_sha = load_artifact(folder, expected)
    from .planning_constraint_index import _read_history_window
    prior_history = _read_history_window(Path(data_dir), result["issue_id"], 0,
                                        trip_id=result["trip_id"], anchor_ms=result["anchor_ms"])
    if prior_history is not None:
        raise ValueError("planning_history_already_authoritative")
    key = result["capture_key"]

    def ingest(db):
        prior = db.execute("SELECT owner,state,receipt_sha256 FROM captures WHERE capture_key=?", (key,)).fetchone()
        if prior is None or prior[0] != owner:
            raise ValueError("planning_owner_mismatch")
        existing = db.execute("SELECT state FROM receipts WHERE receipt_sha256=? AND capture_key=?", (receipt_sha, key)).fetchone()
        if existing:
            return {"capture_key": key, "receipt_sha256": receipt_sha, "state": existing[0], "reused": True}
        # Preserve a prior complete result; changed partials need explicit
        # independent coverage reconciliation, never last-write-wins merging.
        if prior[2] is not None:
            raise ValueError("planning_receipt_conflict_requires_review")
        metadata = {k: result[k] for k in (
            "extraction_status", "gaps_ms", "frame_count", "frame_statuses", "errors", "t0",
            "source_kind", "simulation_run", "input_stage", "extractor_version", "source")}
        metadata.update(source_result_sha256=receipt["files"]["result.json"]["sha256"],
                        receipt_sha256=receipt_sha, producer=receipt["producer"])
        db.execute("UPDATE captures SET state=?,receipt_sha256=?,metadata_json=?,updated_at=? WHERE capture_key=?", (
            result["extraction_status"], receipt_sha, json.dumps(metadata, ensure_ascii=False), time.time(), key))
        db.executemany("INSERT INTO frames VALUES(?,?,?,?)", [
            (key, f["timestamp_ms"], int(f["publish_ns"]), json.dumps(f, ensure_ascii=False, separators=(",", ":")))
            for f in result["frames"]])
        db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (
            receipt_sha, key, result["extraction_status"], time.time(), json.dumps(receipt["producer"])))
        return {"capture_key": key, "receipt_sha256": receipt_sha, "state": result["extraction_status"],
                "frame_count": result["frame_count"], "reused": False}
    return _writer(data_dir, ingest)


def _reader(data_dir):
    path = index_path(data_dir)
    path.resolve().relative_to(Path(data_dir).resolve())
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024**3:
        raise ValueError("invalid_daily_planning_index")
    db = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=.1)
    try:
        db.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + .25
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        if (db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION):
            raise ValueError("invalid_daily_planning_index")
        return db
    except Exception:
        db.close()
        raise


def read_daily_window(data_dir, issue_id, offset_ms=None, timestamp_ms=None, *, trip_id=None, anchor_ms=None):
    from .planning_constraint_index import query_offset, InvalidPlanningTime
    path = index_path(data_dir)
    if not path.exists() and not path.is_symlink():
        return None
    base = {"issue_id": issue_id, "frames": [], "read_source": "daily_index"}
    try:
        with closing(_reader(data_dir)) as db:
            query, parameters = "SELECT * FROM captures WHERE issue_id=?", [issue_id]
            for column, value in (("trip_id", trip_id), ("anchor_ms", anchor_ms)):
                if value is not None:
                    query += " AND " + column + "=?"
                    parameters.append(value)
            db.row_factory = sqlite3.Row
            captures = db.execute(query + " LIMIT 2", parameters).fetchall()
            if not captures:
                return None
            if len(captures) != 1:
                return {**base, "status": "unavailable", "reason": "identity_conflict"}
            capture = captures[0]
            anchor = capture["anchor_ms"]
            relative = query_offset(anchor, offset_ms, timestamp_ms)
            target, bucket = anchor + relative, relative // 8000
            start = anchor + bucket * 8000 - 200
            end = start + 8400
            base.update(trip_id=capture["trip_id"], anchor_ms=anchor, bucket=bucket,
                        window_start_ms=start, window_end_ms=end, tolerance_ms=150,
                        source=SOURCE, extractor_version=VERSION, query_timestamp_ms=target,
                        selection="default_selected_candidate")
            if capture["state"] == "pending":
                return {**base, "status": "pending", "reason": "registered_for_extraction"}
            if len(capture["metadata_json"]) > 65536:
                raise ValueError("oversized_planning_metadata")
            meta = json.loads(capture["metadata_json"])
            if meta.get("source") != SOURCE or meta.get("extractor_version") != VERSION:
                raise ValueError("incompatible_planning_extractor")
            rows = db.execute("SELECT frame_json FROM frames WHERE capture_key=? AND timestamp_ms>=? "
                              "AND timestamp_ms<=? ORDER BY timestamp_ms,publish_ns LIMIT 1001",
                              (capture["capture_key"], start, end)).fetchall()
            if len(rows) > 1000 or sum(len(row[0]) for row in rows) > 2 * 1024**2:
                raise ValueError("oversized_planning_window")
            frames = [json.loads(row[0]) for row in rows]
            before = [f for f in frames if f["timestamp_ms"] <= target < f["valid_until_ms"]]
            return {**base, "status": "ready", "frames": frames,
                    "matched_frame": before[-1] if before and -20000 <= relative < 20000 else None,
                    "source_status": meta["extraction_status"], "source_frame_count": meta["frame_count"],
                    "source_gaps_ms": meta["gaps_ms"], "source_error_count": len(meta["errors"]),
                    "source_result_sha256": meta["source_result_sha256"], "receipt_sha256": meta["receipt_sha256"],
                    "coverage_start_ms": anchor - 20000, "coverage_end_ms": anchor + 20000}
    except InvalidPlanningTime:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return {**base, "status": "unavailable", "reason": "index_unavailable"}


def _cohort_states(data_dir):
    """Read the bounded identity/status projection once for related cohorts."""
    by_identity = {}
    historical = Path(data_dir) / "planning_constraints/history.sqlite3"
    if historical.exists():
        historical.resolve().relative_to(Path(data_dir).resolve())
        if historical.is_symlink() or historical.stat().st_size > 2 * 1024**3:
            raise ValueError("invalid_planning_history")
        with closing(sqlite3.connect(historical.absolute().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=.1)) as db:
            deadline = time.monotonic() + .25
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            if (db.execute("PRAGMA application_id").fetchone()[0] != 0x50434958
                    or db.execute("PRAGMA user_version").fetchone()[0] != 1
                    or db.execute("SELECT extractor_version,source FROM configuration WHERE id=1").fetchone() != (VERSION, SOURCE)):
                raise ValueError("invalid_planning_history")
            rows = db.execute("SELECT issue_id,trip_id,anchor_ms,metadata_json FROM issues LIMIT 20001").fetchall()
            if len(rows) > 20000:
                raise ValueError("oversized_planning_cohort")
            for iid, trip, anchor, raw in rows:
                if len(raw) > 65536:
                    raise ValueError("oversized_planning_metadata")
                meta = json.loads(raw)
                by_identity[(iid, trip, anchor)] = (meta["source_status"], meta["source_frame_count"])
    if index_path(data_dir).exists():
        with closing(_reader(data_dir)) as db:
            rows = db.execute("SELECT issue_id,trip_id,anchor_ms,state,metadata_json FROM captures LIMIT 20001").fetchall()
            if len(rows) > 20000:
                raise ValueError("oversized_planning_cohort")
            for iid, trip, anchor, state, raw in rows:
                if len(raw) > 65536:
                    raise ValueError("oversized_planning_metadata")
                key = iid, trip, anchor
                if state != "pending" or key not in by_identity:
                    by_identity[key] = state, json.loads(raw).get("frame_count", 0)
    return by_identity


def cohort_counts_many(data_dir, cohorts, *, include_pipeline=False):
    """Project each scope independently from one read-only index snapshot."""
    results = {}
    active = {}
    for key, targets in cohorts.items():
        result = {"selected": len(targets), "status": "ready", "with_frames": 0,
                  "collected": 0, "partial_source": 0, "failed": 0, "pending": 0, "unknown": 0}
        if data_dir is None:
            result.update(status="not_activated", unknown=len(targets))
        elif targets:
            active[key] = targets
        results[key] = result
    if not active:
        if include_pipeline:
            from .cron_planning_text import TextPipeline
            pipeline = TextPipeline(data_dir, {})
            for key, targets in cohorts.items():
                results[key]["pipeline"] = pipeline.project(targets, results[key])
        return results
    try:
        by_identity = _cohort_states(data_dir)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        for key, targets in active.items():
            results[key] = {"selected": len(targets), "status": "unavailable"}
        return results
    for key, targets in active.items():
        result = results[key]
        try:
            for iid, expected in targets.items():
                anchor = expected.get("capture_timestamp_ms") or expected.get("ra_start_timestamp")
                found = by_identity.get((iid, expected.get("trip_id"), anchor))
                if not found:
                    result["unknown"] += 1
                    continue
                state, frames = found
                if state not in {"collected", "partial_source", "failed", "pending"} or type(frames) is not int or frames < 0:
                    raise ValueError("invalid_planning_cohort_state")
                result[state] += 1
                result["with_frames"] += int(frames > 0)
        except (ValueError, TypeError, KeyError):
            results[key] = {"selected": len(targets), "status": "unavailable"}
    if include_pipeline:
        from .cron_planning_text import TextPipeline
        pipeline = TextPipeline(data_dir, by_identity)
        for key, targets in cohorts.items():
            results[key]["pipeline"] = pipeline.project(targets, results[key])
    return results


def cohort_counts(data_dir, targets):
    """Reuse exact historical identities; never scan the frame tables for counts."""
    return cohort_counts_many(data_dir, {"cohort": targets})["cohort"]
