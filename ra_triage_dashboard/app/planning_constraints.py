"""Bounded, single-flight, on-demand planning facts. Never on first paint."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import fcntl

SOURCE = "/studio_node/planning/speed_table_raw.dominantConstraint"
VERSION = "ares-default-8c071689-v2"
_lock = threading.Lock()
_active: set[str] = set()
_failures: dict[str, float] = {}
_processes: set[subprocess.Popen] = set()
_stopping = False


def _stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def shutdown():
    global _stopping
    with _lock:
        _stopping = True
        processes = list(_processes)
    for process in processes:
        _stop(process)


def read_window(data_dir: Path, issue_id: str, trip_id: str, anchor_ms: int, offset_ms: int):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", trip_id):
        return {"status": "unavailable", "frames": []}
    bucket = offset_ms // 8000
    start = anchor_ms + bucket * 8000 - 200
    end = start + 8400
    key = hashlib.sha256(f"{VERSION}:{issue_id}:{trip_id}:{anchor_ms}:{bucket}".encode()).hexdigest()
    root = Path(data_dir) / "planning_constraints"
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{key}.json"
    base = {"issue_id": issue_id, "anchor_ms": anchor_ms, "window_start_ms": start,
            "window_end_ms": end, "bucket": bucket, "source": SOURCE, "tolerance_ms": 150,
            "selection": "default_selected_candidate", "extractor_version": VERSION}
    try:
        if dest.is_file() and dest.stat().st_size <= 2 * 1024**2:
            saved = json.loads(dest.read_text())
            if saved.get("key") == key and isinstance(saved.get("frames"), list):
                return {**base, "status": "ready", "frames": saved["frames"]}
    except (OSError, ValueError):
        pass
    with _lock:
        if _stopping:
            return {**base, "status": "unavailable", "frames": []}
        if key in _active:
            return {**base, "status": "loading", "frames": []}
        if time.monotonic() - _failures.get(key, -1e9) < 60:
            return {**base, "status": "error", "frames": []}
        if _active:
            return {**base, "status": "busy", "frames": []}
        if shutil.disk_usage(root).free < 2 * 1024**3:
            return {**base, "status": "unavailable", "frames": []}
        _active.add(key)
    threading.Thread(target=_extract, args=(root, dest, key, trip_id, start, end), daemon=True).start()
    return {**base, "status": "loading", "frames": []}


def _extract(root, dest, key, trip_id, start, end):
    process = None
    try:
        with (root / "worker.lock").open("a") as guard, tempfile.TemporaryDirectory(prefix="window-", dir=root) as temp:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            work = Path(temp)
            request = {"trip_id": trip_id, "start_ms": start, "end_ms": end, "work_dir": temp}
            launcher = Path(__file__).resolve().parents[1] / "scripts/run_planning_constraint_worker.sh"
            # Bounded logs/output, timeout and process group; no shared source bags.
            with (work / "out.json").open("wb") as out, (work / "worker.log").open("wb") as err:
                with _lock:
                    if _stopping:
                        raise RuntimeError("shutting down")
                    process = subprocess.Popen(["bash", str(launcher)], stdin=subprocess.PIPE,
                                               stdout=out, stderr=err, start_new_session=True)
                    _processes.add(process)
                try:
                    process.communicate(json.dumps(request).encode(), timeout=120)
                finally:
                    # Stop before TemporaryDirectory removes an in-use bag.
                    _stop(process)
                    with _lock:
                        _processes.discard(process)
            if process.returncode or (work / "out.json").stat().st_size > 2 * 1024**2:
                raise ValueError("extraction failed")
            result = json.loads((work / "out.json").read_text())
            frames = result["frames"]
            if not isinstance(frames, list) or len(frames) > 1000:
                raise ValueError("invalid frames")
            for frame in frames:
                if not start <= frame["timestamp_ms"] <= end:
                    raise ValueError("frame outside request")
                if len(str(frame.get("raw", ""))) > 16384:
                    raise ValueError("oversized raw field")
            pending = work / "result.json"
            pending.write_text(json.dumps({"key": key, "frames": frames}))
            pending.replace(dest)
            # Regenerable facts only; never touch source bags or other caches.
            cached = sorted(root.glob("[0-9a-f]" * 64 + ".json"), key=lambda p: p.stat().st_mtime, reverse=True)
            total = 0
            for ix, old in enumerate(cached):
                total += old.stat().st_size
                if ix >= 2048 or total > 64 * 1024**2:
                    old.unlink(missing_ok=True)
    except Exception:
        with _lock:
            if len(_failures) > 256:
                _failures.clear()
            _failures[key] = time.monotonic()
    finally:
        with _lock:
            _active.discard(key)
