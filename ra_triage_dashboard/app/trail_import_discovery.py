"""Durable read-only Trail observations, independent of browser/request lifetime.

Only remote facts are cached. Local decisions and actor eligibility are projected
on every read; preview/commit never trust this cache. No business tables are written.
"""
import fcntl
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


_slots = threading.BoundedSemaphore(2)
_FAILED = "后台扫描未完成，请刷新差异重试 / Background scan incomplete; refresh differences to retry"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


class TrailImportDiscovery:
    def __init__(self, root, source):
        self.root = Path(root) / "trail_import_discovery"
        self.source = source

    def _path(self, scopes):
        return self.root / (_digest([1, self.source, sorted(set(scopes))]) + ".json")

    @staticmethod
    def _load(path):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("invalid discovery cache")
            return state
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError):
            # A broken cache is visible, not an excuse to silently requery Trail.
            return {"version": 1, "status": "failed", "error": _FAILED}

    @staticmethod
    def _save(path, state):
        fd, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read_or_start(self, *, scopes, members, read_remote, refresh=False):
        """Return immediately; first visit/explicit refresh starts one worker.

        A scope lock spans the entire scan, including across server workers.
        Failed/interrupted jobs require explicit retry. Completed snapshots have
        no automatic TTL: the UI shows their time and membership-change warning.
        """
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(scopes)
        lock = open(path.with_suffix(".lock"), "a")
        transferred = False
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self._load(path) or {"version": 1, "status": "running", "total": len(members)}
            state = self._load(path)
            if state and state.get("status") == "running":
                state.update(status="interrupted", error=_FAILED)
                self._save(path, state)
            if state is not None and not refresh:
                return state
            if not _slots.acquire(blocking=False):
                raise RuntimeError("扫描繁忙，请稍后重试 / Scanner busy; retry later")
            try:
                state = {"version": 1, "status": "running", "scanned": 0,
                         "total": len(members), "started_at": _now(),
                         "snapshot": (state or {}).get("snapshot"), "partial": [], "error": ""}
                self._save(path, state)
                worker = threading.Thread(target=self._scan,
                    args=(path, lock, state, list(members), read_remote),
                    name="trail-import-discovery", daemon=True)
                worker.start()
                transferred = True
            except BaseException:
                _slots.release()
                raise
            # Worker owns its own state copy so a response cannot race mutation.
            return {**state}
        finally:
            if not transferred:
                lock.close()

    def _scan(self, path, lock, initial, members, read_remote):
        state = dict(initial)
        observed = []
        try:
            for offset in range(0, len(members), 100):
                page = members[offset:offset + 100]
                ids = [row["issue_id"] for row in page]
                remote = read_remote(ids)
                if set(remote) != set(ids):
                    raise ValueError("incomplete observation")
                # Scan all members, even currently locally excluded ones: a later
                # local reversal must be visible without another remote scan.
                for member in page:
                    fact = remote[member["issue_id"]]
                    if fact.get("should_exclude") is True:
                        observed.append({**member, "remote": fact})
                state.update(scanned=offset + len(page), partial=list(observed))
                self._save(path, state)
            state.update(status="ready", error="", partial=[], snapshot={
                "checked_at": _now(), "membership": _digest(members),
                "total": len(members), "items": observed})
            self._save(path, state)
        except Exception:
            # Do not expose upstream exceptions, credentials or operational paths.
            # A failed refresh retains the previous complete snapshot.
            state.update(status="failed", error=_FAILED)
            self._save(path, state)
        finally:
            lock.close()
            _slots.release()

    @staticmethod
    def membership_changed(state, members):
        snapshot = state.get("snapshot")
        return bool(snapshot and snapshot["membership"] != _digest(members))
