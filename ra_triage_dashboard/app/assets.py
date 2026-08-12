from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .web_paths import with_base_path


class AssetIndex:
    """Read-only index over Ares Capture manifest/meta files.

    Only paths present in the manifest are served, so the asset endpoint cannot
    be used to browse arbitrary files on cloud_server.
    """

    def __init__(
        self,
        *,
        ra_root: Path,
        manifest_path: Path,
        base_path: str = "",
    ):
        self.ra_root = ra_root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.base_path = base_path
        self._lock = threading.RLock()
        self._manifest_mtime_ns = -1
        self._meta_paths: dict[str, Path] = {}
        self._assets: dict[str, dict[str, Path]] = {}

    def refresh(self, force: bool = False) -> int:
        try:
            stat = self.manifest_path.stat()
        except FileNotFoundError:
            with self._lock:
                self._meta_paths = {}
                self._assets = {}
            return 0
        if not force and stat.st_mtime_ns == self._manifest_mtime_ns:
            return len(self._meta_paths)

        parsed: dict[str, Path] = {}
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    issue_id = str(row.get("issue_id") or "").strip()
                    meta_path = str(row.get("meta_path") or "").strip()
                except (TypeError, ValueError):
                    continue
                if not issue_id or not meta_path:
                    continue
                candidate = (self.ra_root / meta_path).resolve()
                if self._within_root(candidate):
                    parsed[issue_id] = candidate
        with self._lock:
            self._manifest_mtime_ns = stat.st_mtime_ns
            self._meta_paths = parsed
            self._assets = {}
        return len(parsed)

    def indexed_count(self) -> int:
        """Return the in-memory index size without touching the filesystem.

        Startup performs one forced refresh.  Lightweight health probes should
        report that last known-good snapshot rather than turning every probe
        into a manifest stat/parse operation on network storage.
        """

        with self._lock:
            return len(self._meta_paths)

    def has_issue(self, issue_id: str) -> bool:
        """Return whether an indexed Ares manifest entry exists for an issue.

        Uses the in-memory index only (no per-issue ``is_file``). Gallery list
        traffic calls this once per row; rare missing files fail at thumbnail
        fetch instead of slowing every list response.
        """

        self.refresh()
        with self._lock:
            return issue_id in self._meta_paths

    def get_thumbnail_source(self, issue_id: str) -> dict[str, Any] | None:
        """Resolve the t0/nearest BEV frame used to build a lightweight thumbnail.

        The returned path is consumed only by the dashboard backend.  Browser
        responses continue to expose opaque asset/thumbnail URLs.

        This path intentionally avoids building the full multi-frame asset list
        used by Issue detail; homepage gallery traffic is thumbnail-heavy.
        """

        self.refresh()
        with self._lock:
            meta_path = self._meta_paths.get(issue_id)
        if not meta_path or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

        candidates: list[tuple[float, int, str, Path, Any, Any]] = []
        variants = ((meta.get("capture_plan") or {}).get("variants") or [])
        for variant_index, variant in enumerate(variants):
            for frame_index, frame in enumerate(variant.get("frames") or []):
                if not isinstance(frame, dict):
                    continue
                relative_path = str(frame.get("relative_path") or "")
                path = self._resolve_asset(meta_path.parent, relative_path)
                if not path or not path.is_file():
                    continue
                raw = frame.get("offset_ms")
                if raw is None and frame.get("offset_sec") is not None:
                    try:
                        raw = float(frame["offset_sec"]) * 1000
                    except (TypeError, ValueError):
                        raw = None
                try:
                    distance = abs(float(raw))
                except (TypeError, ValueError):
                    distance = float("inf")
                candidates.append(
                    (
                        distance,
                        frame_index,
                        f"frame-{variant_index}-{frame_index}",
                        path,
                        frame.get("offset_ms"),
                        frame.get("offset_sec"),
                    )
                )
        if not candidates:
            return None
        _distance, _idx, asset_id, path, offset_ms, offset_sec = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        return {
            "path": path,
            "asset_id": asset_id,
            "offset_ms": offset_ms,
            "offset_sec": offset_sec,
        }

    def get_assets(self, issue_id: str) -> dict[str, Any]:
        self.refresh()
        with self._lock:
            meta_path = self._meta_paths.get(issue_id)
        if not meta_path or not meta_path.is_file():
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "video": None,
                "capture": {},
            }

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "video": None,
                "capture": {},
            }

        base = meta_path.parent
        assets: dict[str, Path] = {}
        frames: list[dict[str, Any]] = []
        variants = ((meta.get("capture_plan") or {}).get("variants") or [])
        for variant_index, variant in enumerate(variants):
            for frame_index, frame in enumerate(variant.get("frames") or []):
                relative_path = str(frame.get("relative_path") or "")
                path = self._resolve_asset(base, relative_path)
                if not path or not path.is_file():
                    continue
                asset_id = f"frame-{variant_index}-{frame_index}"
                assets[asset_id] = path
                frames.append(
                    {
                        "id": asset_id,
                        "offset_ms": frame.get("offset_ms"),
                        "offset_sec": frame.get("offset_sec"),
                        "url": with_base_path(
                            self.base_path,
                            f"/api/assets/{quote(issue_id)}/{asset_id}",
                        ),
                        "size_bytes": path.stat().st_size,
                    }
                )

        video: dict[str, Any] | None = None
        for variant_index, variant in enumerate(variants):
            relative_path = str(variant.get("video_relative_path") or "")
            path = self._resolve_asset(base, relative_path)
            if not path or not path.is_file():
                continue
            asset_id = f"video-{variant_index}"
            assets[asset_id] = path
            video = {
                "id": asset_id,
                "url": with_base_path(
                    self.base_path,
                    f"/api/assets/{quote(issue_id)}/{asset_id}",
                ),
                "size_bytes": path.stat().st_size,
            }
            break

        with self._lock:
            self._assets[issue_id] = assets
        source_row = meta.get("source_row") or {}
        return {
            "available": bool(frames or video),
            "issue_id": issue_id,
            "frames": frames,
            "video": video,
            "capture": {
                "status": meta.get("status", ""),
                "layout": (meta.get("ares_layout") or {}).get("name", ""),
                "timestamp_ms": source_row.get("capture_timestamp_ms"),
                "trip_id": source_row.get("trip_id", ""),
                "rendered_files": meta.get("rendered_files") or [],
            },
        }

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None:
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        self.get_assets(issue_id)
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        return None

    def _resolve_asset(self, base: Path, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        candidate = (base / relative_path).resolve()
        if not self._within_root(candidate):
            return None
        return candidate

    def _within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.ra_root)
            return True
        except ValueError:
            return False


class CameraIndex:
    """Read-only index for camera JPEGs cached alongside Ares Capture.

    The current 0508 baseline has one ``after_compress`` directory per issue.
    We still resolve each directory defensively and only serve files under the
    configured cache root.
    """

    _numbered_image = re.compile(r"^(?P<index>\d+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)
    _default_offsets = (-19, -14, -9, -4, 0, 4, 9, 14, 19)

    def __init__(self, camera_root: Path, base_path: str = ""):
        self.camera_root = camera_root.resolve()
        self.base_path = base_path
        self._lock = threading.RLock()
        self._assets: dict[str, dict[str, Path]] = {}

    def get_assets(self, issue_id: str, timestamp_ms: Any = None) -> dict[str, Any]:
        folder = self._select_folder(issue_id, timestamp_ms)
        if folder is None:
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "capture": {},
            }
        source = folder / "after_compress"
        if not source.is_dir():
            source = folder / "before_compress"
        if not source.is_dir():
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "capture": {"cache_dir": folder.name},
            }
        numbered: list[tuple[int, Path]] = []
        for child in source.iterdir():
            match = self._numbered_image.match(child.name)
            if child.is_file() and match:
                numbered.append((int(match.group("index")), child.resolve()))
        numbered.sort(key=lambda item: item[0])
        assets: dict[str, Path] = {}
        frames: list[dict[str, Any]] = []
        for position, (frame_number, path) in enumerate(numbered):
            if not self._within_root(path):
                continue
            asset_id = f"camera-{position}"
            assets[asset_id] = path
            offset = self._default_offsets[position] if position < len(self._default_offsets) else None
            frames.append(
                {
                    "id": asset_id,
                    "frame_number": frame_number,
                    "offset_sec": offset,
                    "url": with_base_path(
                        self.base_path,
                        f"/api/assets/{quote(issue_id)}/{asset_id}",
                    ),
                    "size_bytes": path.stat().st_size,
                }
            )
        with self._lock:
            self._assets[issue_id] = assets
        return {
            "available": bool(frames),
            "issue_id": issue_id,
            "frames": frames,
            "capture": {
                "cache_dir": folder.name,
                "variant": source.name,
                "timestamp_ms": self._timestamp_from_folder(folder, issue_id),
            },
        }

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None:
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        self.get_assets(issue_id)
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        return None

    def _select_folder(self, issue_id: str, timestamp_ms: Any) -> Path | None:
        if not self.camera_root.is_dir():
            return None
        timestamp = str(timestamp_ms or "").strip()
        if timestamp:
            exact = (self.camera_root / f"{issue_id}_{timestamp}").resolve()
            if exact.is_dir() and self._within_root(exact):
                return exact
        candidates = [
            path.resolve()
            for path in self.camera_root.glob(f"{issue_id}_*")
            if path.is_dir() and self._within_root(path)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)

    @staticmethod
    def _timestamp_from_folder(folder: Path, issue_id: str) -> str:
        prefix = f"{issue_id}_"
        return folder.name[len(prefix) :] if folder.name.startswith(prefix) else ""

    def _within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.camera_root)
            return True
        except ValueError:
            return False


class VideoIndex:
    """Resolve captured Ares playback videos without exposing server paths.

    Video batches are written below shard directories and may still be growing.
    Resolve an Issue on demand from its captured ``meta.json`` rather than
    trusting a partial shard manifest or allowing arbitrary path input.
    """

    _issue_id = re.compile(r"^[A-Za-z0-9_-]{3,128}$")

    def __init__(self, video_root: Path, base_path: str = ""):
        self.video_root = video_root.resolve()
        self.base_path = base_path
        self._lock = threading.RLock()
        self._assets: dict[str, dict[str, Path]] = {}

    def get_video(self, issue_id: str) -> dict[str, Any] | None:
        if not self._issue_id.fullmatch(issue_id) or not self.video_root.is_dir():
            return None
        # Support both shard layout and flat aggregate layout:
        #   shard-*-of-*/{issue_id}_{ts}/meta.json
        #   {issue_id}_{ts}/meta.json
        #   issues/{issue_id}/meta.json (materialized merged capture layout)
        # Match only by issue_id prefix; pick the newest captured meta.
        meta_paths = {
            path.resolve()
            for pattern in (
                f"shard-*-of-*/{issue_id}_*/meta.json",
                f"{issue_id}_*/meta.json",
                f"issues/{issue_id}/meta.json",
            )
            for path in self.video_root.glob(pattern)
            if path.is_file() and self._within_root(path)
        }
        ordered = sorted(
            meta_paths, key=lambda path: path.stat().st_mtime_ns, reverse=True
        )
        for meta_path in ordered:
            video = self._video_from_meta(issue_id, meta_path)
            if video is not None:
                return video
        return None

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None:
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        self.get_video(issue_id)
        with self._lock:
            path = self._assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within_root(path):
            return path
        return None

    def _video_from_meta(
        self, issue_id: str, meta_path: Path
    ) -> dict[str, Any] | None:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (
            str(meta.get("issue_id") or "") != issue_id
            or str(meta.get("status") or "") != "captured"
        ):
            return None
        variants = ((meta.get("capture_plan") or {}).get("variants") or [])
        rendered_videos = (meta.get("render_metadata") or {}).get("videos") or []
        for variant_index, variant in enumerate(variants):
            relative_path = str(variant.get("video_relative_path") or "")
            path = self._resolve_asset(meta_path.parent, relative_path)
            if not path or not path.is_file() or path.suffix.lower() != ".mp4":
                continue
            render_meta = next(
                (
                    item
                    for item in rendered_videos
                    if str(item.get("relative_path") or "") == relative_path
                ),
                {},
            )
            asset_id = f"bev-video-{variant_index}"
            with self._lock:
                self._assets[issue_id] = {asset_id: path}
            start_offset_sec = _number_or_none(
                variant.get("video_start_offset_sec")
            )
            duration_ms = _number_or_none(
                render_meta.get("visible_duration_ms")
                or variant.get("video_duration_ms")
            )
            frame_step_ms = _number_or_none(
                render_meta.get("frame_step_ms")
                or variant.get("video_frame_step_ms")
            )
            frame_count = _number_or_none(render_meta.get("frame_count"))
            size = variant.get("video_size") or {}
            return {
                "id": asset_id,
                "url": with_base_path(
                    self.base_path,
                    f"/api/assets/{quote(issue_id)}/{asset_id}",
                ),
                "size_bytes": path.stat().st_size,
                "source": "ares_capture_video",
                "duration_ms": duration_ms,
                "start_offset_sec": start_offset_sec,
                "event_time_sec": (
                    max(0.0, -start_offset_sec)
                    if start_offset_sec is not None
                    else None
                ),
                "frame_step_ms": frame_step_ms,
                "frame_count": frame_count,
                "capture_mode": str(
                    render_meta.get("capture_mode")
                    or variant.get("video_capture_mode")
                    or ""
                ),
                "width": _number_or_none(size.get("width")),
                "height": _number_or_none(size.get("height")),
            }
        return None

    def _resolve_asset(self, base: Path, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        candidate = (base / relative_path).resolve()
        if not self._within_root(candidate):
            return None
        return candidate

    def _within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.video_root)
            return True
        except ValueError:
            return False


def _number_or_none(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number
