"""Acyclic leaf reader for immutable historical planning-text SQLite snapshots."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import time

from .planning_contracts import (
    InvalidPlanningTime,
    MAX_OFFSET_MS,
    SOURCE,
    VERSION,
    query_offset,
)

INDEX_NAME = "history.sqlite3"
INDEX_VERSION = 1
APPLICATION_ID = 0x50434958  # PCIX
MAX_INDEX_BYTES = 2 * 1024**3
MAX_RESULT_BYTES = 2 * 1024**2
MAX_FRAME_BYTES = 32768
MAX_FRAMES = 1000
TOLERANCE_MS = 150


def _read_history_window(
    data_dir: Path,
    issue_id: str,
    offset_ms: int | None = None,
    timestamp_ms: int | None = None,
    *,
    trip_id: str | None = None,
    anchor_ms: int | None = None,
) -> dict | None:
    """None means a true miss; a damaged index fails closed without a Bag read."""
    path = Path(data_dir) / "planning_constraints" / INDEX_NAME
    try:
        if not path.exists():
            return None
        path.resolve().relative_to(Path(data_dir).resolve())
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
            raise ValueError("Invalid index file")
        deadline = time.monotonic() + 0.25
        with closing(
            sqlite3.connect(
                path.absolute().as_uri() + "?mode=ro&immutable=1",
                uri=True,
                timeout=0.1,
            )
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            if (
                conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or conn.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION
            ):
                raise ValueError("Unsupported index")
            identity = conn.execute(
                "SELECT extractor_version,source FROM configuration WHERE id=1"
            ).fetchone()
            if identity != (VERSION, SOURCE):
                raise ValueError("Incompatible extraction")
            row = conn.execute(
                "SELECT trip_id,anchor_ms,start_offset_ms,end_offset_ms,metadata_json "
                "FROM issues WHERE issue_id=?",
                (issue_id,),
            ).fetchone()
            if row is None:
                return None
            saved_trip, saved_anchor, begin, finish, raw_meta = row
            if (trip_id is not None and trip_id != saved_trip) or (
                anchor_ms is not None and anchor_ms != saved_anchor
            ):
                return None
            relative = query_offset(saved_anchor, offset_ms, timestamp_ms)
            bucket = relative // 8000
            start = saved_anchor + bucket * 8000 - 200
            end = start + 8400
            if end < saved_anchor + begin or start >= saved_anchor + finish:
                return None
            if len(raw_meta) > 65536:
                raise ValueError("Oversized metadata")
            meta = json.loads(raw_meta)
            if not isinstance(meta, dict) or not re.fullmatch(
                r"[0-9a-f]{64}", str(meta.get("source_result_sha256", ""))
            ):
                raise ValueError("Invalid source metadata")
            meta = {
                key: meta[key]
                for key in (
                    "source_version",
                    "source_status",
                    "source_result_sha256",
                    "source_membership_sha256",
                    "source_frame_count",
                    "source_gaps_ms",
                    "source_error_count",
                    "coverage_start_ms",
                    "coverage_end_ms",
                )
            }
            rows = conn.execute(
                "SELECT timestamp_ms,frame_json FROM frames "
                "WHERE issue_id=? AND timestamp_ms>=? AND timestamp_ms<=? "
                "ORDER BY timestamp_ms LIMIT ?",
                (issue_id, start, end, MAX_FRAMES + 1),
            ).fetchall()
            if len(rows) > MAX_FRAMES or sum(len(raw) for _, raw in rows) > MAX_RESULT_BYTES:
                raise ValueError("Oversized window")
            frames = []
            for published, raw in rows:
                if len(raw) > MAX_FRAME_BYTES:
                    raise ValueError("Oversized frame")
                frame = json.loads(raw)
                if not isinstance(frame, dict) or frame.get("timestamp_ms") != published:
                    raise ValueError("Invalid frame identity")
                frames.append(frame)
    except InvalidPlanningTime:
        raise
    except ValueError:
        return {
            "issue_id": issue_id,
            "status": "unavailable",
            "frames": [],
            "read_source": "historical_index",
            "reason": "index_unavailable",
        }
    except (OSError, sqlite3.Error, TypeError, KeyError):
        return {
            "issue_id": issue_id,
            "status": "unavailable",
            "frames": [],
            "read_source": "historical_index",
            "reason": "index_unavailable",
        }
    target = saved_anchor + relative
    before = [frame for frame in frames if frame["timestamp_ms"] <= target]
    matched = (
        before[-1]
        if begin <= relative < finish
        and before
        and target - before[-1]["timestamp_ms"] <= TOLERANCE_MS
        else None
    )
    return {
        "issue_id": issue_id,
        "trip_id": saved_trip,
        "anchor_ms": saved_anchor,
        "window_start_ms": start,
        "window_end_ms": end,
        "bucket": bucket,
        "source": SOURCE,
        "extractor_version": VERSION,
        "tolerance_ms": TOLERANCE_MS,
        "selection": "default_selected_candidate",
        "status": "ready",
        "frames": frames,
        "read_source": "historical_index",
        "query_timestamp_ms": target,
        "matched_frame": matched,
        **meta,
    }
