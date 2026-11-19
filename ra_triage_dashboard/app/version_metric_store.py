"""Immutable local metric snapshots and a bounded, explicit read-only refresh job."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .version_metrics import POLICY, digest, validate_snapshot, is_trail_snapshot


def now():
    return datetime.now(timezone.utc).isoformat()


class VersionMetricStore:
    def __init__(self, directory):
        self.root = Path(directory) / "version_metric_snapshots"

    def _folder(self, family):
        if not re.fullmatch(r"20\d{6}", str(family)):
            raise ValueError("Invalid release")
        return self.root / family

    @staticmethod
    def _read(path):
        if path.is_symlink():
            raise ValueError("Invalid metric snapshot path")
        try:
            with path.open("rb") as stream:
                raw = stream.read(64*1024*1024+1)
        except FileNotFoundError:
            return None
        if len(raw) > 64*1024*1024:
            raise ValueError("Metric snapshot too large")
        return json.loads(raw)

    @staticmethod
    def _save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix="metric-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def latest(self, family, snapshot_id=""):
        folder = self._folder(family)
        index = self._read(folder / "index.json") or {"items": []}
        sid = snapshot_id or (index["items"][0]["id"] if index["items"] else "")
        if not sid:
            return None
        if not re.fullmatch(r"[a-f0-9]{64}", sid) or not any(x["id"] == sid for x in index["items"]):
            raise ValueError("Unknown metric snapshot")
        saved = self._read(folder / (sid+".json"))
        if not saved:
            raise ValueError("Metric snapshot unavailable")
        check = {k: v for k, v in saved.items() if k != "id"}
        if digest(check) != sid or saved["family"] != family:
            raise ValueError("Metric snapshot checksum mismatch")
        return validate_snapshot(saved)

    def history(self, family):
        return (self._read(self._folder(family) / "index.json") or {"items": []})["items"]

    def latest_trail(self, family, snapshot_id=""):
        saved = self.latest(family, snapshot_id)
        return saved if saved and is_trail_snapshot(saved) else None

    def publish(self, family, source):
        """Called only with a complete, validated server-owned source receipt."""
        previous = self.latest(family)
        rows = source["rows"]
        old_rows = {r["issue_id"]: r for r in (previous or {}).get("rows", [])}
        new_rows = {r["issue_id"]: r for r in rows}
        common = set(old_rows) & set(new_rows)
        changes = dict(added=len(set(new_rows)-set(old_rows)), removed=len(set(old_rows)-set(new_rows)),
                       references=sum(old_rows[i]["references"] != new_rows[i]["references"] for i in common),
                       predictions=sum(any(old_rows[i].get(k) != new_rows[i].get(k) for k in ("label", "source", "confidence")) for i in common),
                       exclusions=sum(old_rows[i]["excluded"] != new_rows[i]["excluded"] for i in common))
        saved = dict(source, schema_version=1, policy=POLICY, family=family, changes=changes)
        saved.pop("id", None)
        validate_snapshot(saved)
        saved["id"] = digest(saved)
        folder = self._folder(family)
        self._save(folder / (saved["id"]+".json"), saved)
        index = self.history(family)
        item = dict(id=saved["id"], observed_at=saved["observed_at"],
                    sample_total=sum(r["sample"] and r["published"] for r in rows),
                    registry_revision=saved.get("registry_revision"), changes=changes)
        self._save(folder / "index.json", {"items": [item, *[x for x in index if x["id"] != saved["id"]]]})
        return saved

    def job(self):
        state = self._read(self.root / "refresh.json") or dict(status="idle", completed=0, total=0)
        if state["status"] == "running":
            # Detect a lost worker without retrying an interrupted remote scan.
            lock = open(self.root / "refresh.lock", "a")
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return state
                # The worker may finish after the first read and release its lock.
                state = self._read(self.root / "refresh.json") or state
                if state["status"] != "running":
                    return state
                state = dict(state, status="interrupted", error="refresh_interrupted")
                self._save(self.root / "refresh.json", state)
            finally:
                lock.close()
        return state

    def refresh(self, families, factory):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = open(self.root / "refresh.lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError("指标正在更新 / Metric refresh is already running") from None
        initial = dict(status="running", families=families, completed=0, total=len(families), started_at=now(), error="")
        try:
            self._save(self.root / "refresh.json", initial)
            thread = threading.Thread(target=self._refresh, args=(families, factory, initial, lock), daemon=True,
                                      name="version-metric-refresh")
            thread.start()
        except BaseException:
            lock.close()
            raise
        return initial

    def _refresh(self, families, factory, initial, lock):
        state = dict(initial)
        try:
            for family in families:
                collected = factory(family)
                if not is_trail_snapshot(collected):
                    raise ValueError("A complete Trail snapshot is required")
                self.publish(family, collected)
                state["completed"] += 1
                self._save(self.root / "refresh.json", state)
            state.update(status="ready", finished_at=now())
        except Exception:
            # Never return credentials, SDK exceptions, or partial reference rows.
            state.update(status="failed", error="source_read_failed", finished_at=now())
        finally:
            self._save(self.root / "refresh.json", state)
            lock.close()
