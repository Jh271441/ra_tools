"""Verified, disposable short-GOP playback copies of indexed MP4 assets.

HTTP never waits for an encode. A cold/missing/invalid copy serves the original
and queues bounded background work; originals and capture receipts are immutable.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from fractions import Fraction
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time

RECIPE = "short-gop-v1"
logger = logging.getLogger(__name__)


def source_identity(source: Path) -> tuple[Path, str]:
    path = source.resolve(strict=True)
    stat = path.stat()
    if path.suffix.lower() != ".mp4" or not path.is_file() or not 0 < stat.st_size <= 1024**3:
        raise ValueError("unsupported playback source")
    key = hashlib.sha256(json.dumps(
        [RECIPE, str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns],
        separators=(",", ":"),
    ).encode()).hexdigest()
    return path, key


class VideoPlaybackCache:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._retry_after: dict[str, float] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._processes: set[subprocess.Popen] = set()
        self._stopped = False

    def _folder(self, key: str) -> Path:
        folder = (self.root / key[:2] / key).resolve()
        folder.relative_to(self.root)
        return folder

    def get(self, source: Path) -> Path | None:
        try:
            _, key = source_identity(source)
            folder = self._folder(key)
            receipt = folder / "receipt.json"
            receipt.resolve().relative_to(self.root)
            if receipt.stat().st_size > 8192:
                return None
            row = json.loads(receipt.read_text())
            output = (folder / "video.mp4").resolve()
            output.relative_to(folder)
            stat = output.stat()
            if (row.get("recipe") == RECIPE and row.get("source_key") == key
                    and row.get("verified") is True and output.is_file()
                    and row.get("size_bytes") == stat.st_size > 0
                    and row.get("mtime_ns") == stat.st_mtime_ns):
                return output
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def request(self, source: Path) -> Path | None:
        """Return a ready copy or schedule one without blocking an HTTP worker."""
        ready = self.get(source)
        if ready:
            return ready
        try:
            path, key = source_identity(source)
        except (OSError, ValueError):
            return None
        with self._lock:
            if (self._stopped or key in self._pending or len(self._pending) >= 32
                    or self._retry_after.get(key, 0) > time.monotonic()):
                return None
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-playback")
            self._pending.add(key)
            self._executor.submit(self._background_build, path, key)
        return None

    def _background_build(self, source: Path, key: str) -> None:
        try:
            self.build(source)
        except Exception:
            # Paths, subprocess stderr and media metadata stay out of public logs.
            logger.warning("playback copy unavailable: %s", key[:12])
        finally:
            with self._lock:
                self._pending.discard(key)
                if len(self._retry_after) >= 4000:
                    self._retry_after.clear()
                self._retry_after[key] = time.monotonic() + 60

    def _run(self, args: list[str], timeout: int = 180) -> str:
        with self._lock:
            if self._stopped:
                raise RuntimeError("playback worker stopped")
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, start_new_session=True)
            self._processes.add(process)
        try:
            output, _ = process.communicate(timeout=timeout)
            if process.returncode:
                raise RuntimeError("playback tool failed")
            return output
        finally:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            with self._lock:
                self._processes.discard(process)

    def _probe(self, path: Path) -> dict:
        return json.loads(self._run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_packets",
            "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,duration:packet=pts_time,flags",
            "-of", "json", str(path),
        ], timeout=60))

    def build(self, source: Path) -> Path | None:
        """Offline/background only; publish atomically after full validation."""
        ready = self.get(source)
        if ready:
            return ready
        path, key = source_identity(source)
        folder = self._folder(key)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "build.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None
            ready = self.get(path)
            if ready:
                return ready
            # No eviction or deletion of source/other caches under pressure.
            if shutil.disk_usage(folder).free < max(5 * 1024**3, path.stat().st_size * 4):
                return None
            before = self._probe(path)
            stream = before["streams"][0]
            fps = float(Fraction(stream["r_frame_rate"]))
            total = float(stream["duration"])
            if (stream["codec_name"] != "h264" or stream["pix_fmt"] != "yuv420p"
                    or not 1 <= fps <= 60 or not 0 < total <= 120):
                return None
            temp = folder / "pending.mp4"
            receipt_temp = folder / "pending.json"
            try:
                self._run([
                    "nice", "-n", "10", "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(path),
                    "-map", "0:v:0", "-map", "0:a?", "-c:a", "copy", "-c:v", "libx264",
                    "-preset", "fast", "-crf", "21", "-threads", "2", "-vsync", "0",
                    "-g", str(max(1, round(fps * 2))), "-keyint_min", "1", "-sc_threshold", "0",
                    "-force_key_frames", f"expr:gte(t,n_forced*2)+eq(t,{total / 2:g})",
                    "-movflags", "+faststart", str(temp),
                ])
                after = self._probe(temp)
                self._validate(before, after, temp)
                # Decode every frame; ffprobe alone does not detect bad media.
                self._run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-threads", "2",
                           "-i", str(temp), "-map", "0:v:0", "-f", "null", "-"])
                if source_identity(path)[1] != key:
                    return None
                output = folder / "video.mp4"
                temp.replace(output)
                stat = output.stat()
                row = {"recipe": RECIPE, "source_key": key, "verified": True,
                       "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       "width": stream["width"], "height": stream["height"],
                       "frame_count": len(after["packets"]), "duration_sec": total,
                       "max_keyframe_gap_sec": 2, "crf": 21}
                receipt_temp.write_text(json.dumps(row, separators=(",", ":")))
                receipt_temp.replace(folder / "receipt.json")
                return output
            finally:
                temp.unlink(missing_ok=True)
                receipt_temp.unlink(missing_ok=True)

    @staticmethod
    def _validate(before: dict, after: dict, path: Path) -> None:
        source, output = before["streams"][0], after["streams"][0]
        for field in ("codec_name", "width", "height", "pix_fmt", "r_frame_rate"):
            if source[field] != output[field]:
                raise ValueError("playback geometry/format changed")
        old_times = sorted(float(p["pts_time"]) for p in before["packets"])
        times = sorted(float(p["pts_time"]) for p in after["packets"])
        if len(times) != len(old_times) or any(abs(a - b) > .000001 for a, b in zip(times, old_times)):
            raise ValueError("playback timeline changed")
        total = float(source["duration"])
        if abs(total - float(output["duration"])) > .001:
            raise ValueError("playback duration changed")
        keys = sorted(float(p["pts_time"]) for p in after["packets"] if "K" in p.get("flags", ""))
        step = 1 / float(Fraction(source["r_frame_rate"]))
        if (not keys or keys[0] > .001
                or any(b - a > 2 + step + .001 for a, b in zip(keys, [*keys[1:], total]))
                or min(abs(t - total / 2) for t in keys) > step + .001):
            raise ValueError("playback keyframes invalid")
        # Verify actual top-level boxes, not incidental strings in video data.
        boxes = []
        with path.open("rb") as handle:
            while handle.tell() < path.stat().st_size:
                at = handle.tell()
                header = handle.read(8)
                if len(header) != 8:
                    raise ValueError("invalid MP4 box")
                size = int.from_bytes(header[:4], "big")
                if size == 1:
                    size = int.from_bytes(handle.read(8), "big")
                if size < 8:
                    raise ValueError("invalid MP4 box size")
                boxes.append(header[4:])
                handle.seek(at + size)
        if b"moov" not in boxes or b"mdat" not in boxes or boxes.index(b"moov") > boxes.index(b"mdat"):
            raise ValueError("playback index is not first")

    def shutdown(self) -> None:
        with self._lock:
            self._stopped = True
            for process in self._processes:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            executor = self._executor
        if executor:
            executor.shutdown(wait=True, cancel_futures=True)
