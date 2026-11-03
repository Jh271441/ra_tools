"""Durable, allowlisted Trail display snapshots; no business-data writes.

One small atomic JSON record per source/view/Issue lives on the application data
volume. flock coordinates workers and service restarts without a database schema
change. Completed events never expire; explicit refresh replaces the snapshot.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .trail_sync import TRAIL_DETAIL_FIELDS, _safe_detail_value, ares_playback_metadata

MAX_SNAPSHOT_BYTES = 128 * 1024
FAILURE_RETRY_SECONDS = 30
INCOMPLETE_RETRY_SECONDS = 300


def _allowlisted_metadata(value: Any, issue_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("issue_id", issue_id) != issue_id:
        return {}
    result: dict[str, Any] = {}
    for field in TRAIL_DETAIL_FIELDS:
        if field in value:
            safe = _safe_detail_value(field, value[field])
            if safe not in (None, "", []):
                result[field] = safe
    if not result:
        return {}
    result["issue_id"] = issue_id
    marker = value.get("dashboard_should_exclude")
    if isinstance(marker, bool):
        result["dashboard_should_exclude"] = marker
    version = value.get("te_task_version_disabe_ra")
    if type(version) is int and 0 <= version <= 32:
        result["te_task_version_disabe_ra"] = version
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_SNAPSHOT_BYTES - 2048:
        raise ValueError("Trail metadata exceeds snapshot limit")
    return result


def _complete(metadata: dict[str, Any]) -> bool:
    events = metadata.get("ra_event") or []
    playback = ares_playback_metadata(metadata, events)
    ended = (metadata.get("ra_end_timestamp") or 0) > 0 or any(
        event.get("event") == "exit" and (event.get("timestamp") or 0) > 0
        for event in events
    )
    return bool(events and playback["ares_trip_id"] and
                (playback["ares_timestamp_ms"] or 0) > 0 and ended)


class TrailMetadataStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def _identity(ra_root: Path, view_id: int, issue_id: str) -> str:
        raw = json.dumps([str(Path(ra_root).resolve()), int(view_id), issue_id])
        return hashlib.sha256(raw.encode()).hexdigest()

    def _read(self, path: Path, identity: str, issue_id: str) -> dict[str, Any]:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                return {}
            record = json.loads(raw)
            if (not isinstance(record, dict) or record.get("schema") != 1 or
                    record.get("identity") != identity or record.get("issue_id") != issue_id):
                return {}
            record["metadata"] = _allowlisted_metadata(record.get("metadata"), issue_id)
            for field in ("observed_at", "attempted_at", "retry_after"):
                number = record.get(field, 0)
                if type(number) not in (int, float) or not 0 <= number < 1e12:
                    return {}
            return record
        except (OSError, ValueError, TypeError, OverflowError):
            return {}

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False).encode()
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Trail snapshot exceeds size limit")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".trail-", delete=False) as stream:
                temporary = stream.name
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _result(record: dict[str, Any], source: str) -> dict[str, Any]:
        metadata = dict(record.get("metadata") or {})
        observed = record.get("observed_at", 0)
        # An old display snapshot cannot suggest a current exclusion decision.
        # Its marker remains in the receipt; Trail write previews/readback use
        # their independent live source and never consume this cache.
        if observed < time.time() - 300:
            metadata.pop("dashboard_should_exclude", None)
        return {
            "metadata": metadata,
            "status": "ready" if metadata else "unavailable",
            "metadata_source": source,
            "metadata_fetched_at": datetime.fromtimestamp(observed, timezone.utc).isoformat() if observed else None,
            "refresh_status": record.get("refresh_status", "ready"),
        }

    def get_or_fetch(
        self, *, ra_root: Path, issue_id: str, view_id: int,
        reader: Callable[..., dict[str, Any]],
        resolver: Callable[..., int | None] | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        started = time.time()
        identity = self._identity(ra_root, view_id, issue_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / f"{identity}.json"
        record = self._read(path, identity, issue_id)
        # Atomic publication permits lock-free warm reads, even while an
        # explicit refresh is waiting on Trail. Keep the previous data usable.
        if record and not refresh and (
            record.get("retry_after", 0) > started or
            (record.get("metadata") and record.get("retry_after") == 0)
        ):
            return self._result(record, "snapshot")
        lock_fd = os.open(self.root / f"{identity}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            record = self._read(path, identity, issue_id)
            now = time.time()
            metadata = record.get("metadata") or {}
            # A concurrent explicit refresh that completed while this caller
            # waited already satisfies its request. Ordinary hits never refresh.
            shared_refresh = record.get("attempted_at", 0) >= started
            reusable = bool(record) and (
                shared_refresh or (not refresh and (
                    record.get("retry_after", 0) > now or
                    (metadata and record.get("retry_after") == 0)
                ))
            )
            if reusable:
                return self._result(record, "snapshot")
            try:
                fetched = _allowlisted_metadata(reader(
                    ra_root=Path(ra_root), issue_id=issue_id, view_id=view_id,
                    cache_seconds=0,
                ), issue_id)
                if fetched and resolver is not None and str(fetched.get("te_task_id_disabe_ra") or "").isdigit():
                    try:
                        version = resolver(fetched["te_task_id_disabe_ra"], cache_seconds=0)
                        if type(version) is int and 0 <= version <= 32:
                            fetched["te_task_version_disabe_ra"] = version
                    except Exception:
                        pass  # Optional Ares failure cannot discard valid events.
            except Exception:
                fetched = {}
            if metadata and _complete(metadata) and fetched and not _complete(fetched):
                fetched = {}  # A truncated/partial response cannot erase complete events.
            now = time.time()
            # Missing/failed refreshes retain the last successful snapshot.
            record = {
                "schema": 1, "identity": identity, "issue_id": issue_id,
                "view_id": int(view_id), "metadata": fetched or metadata,
                "observed_at": now if fetched else record.get("observed_at", 0),
                "attempted_at": now,
                "retry_after": 0 if fetched and _complete(fetched) else now + (
                    INCOMPLETE_RETRY_SECONDS if fetched else FAILURE_RETRY_SECONDS
                ),
                "refresh_status": "ready" if fetched else "unavailable",
            }
            if not fetched and metadata and _complete(metadata):
                record["retry_after"] = 0
            self._write(path, record)
            return self._result(record, "trail" if fetched else "snapshot")
