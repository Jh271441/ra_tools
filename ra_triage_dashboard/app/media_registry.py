"""Per-baseline media providers with root-confined asset resolution.

Public browser URLs remain opaque ``/api/assets/...`` paths. Providers only
expose filesystem paths to the dashboard process.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from .assets import AssetIndex, CameraIndex, VideoIndex
from .baseline_registry import BaselineEntry, BaselineRegistry
from .web_paths import with_base_path


class MediaProvider(Protocol):
    def has_issue(self, issue_id: str) -> bool: ...

    def get_assets(self, issue_id: str) -> dict[str, Any]: ...

    def get_thumbnail_source(self, issue_id: str) -> dict[str, Any] | None: ...

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None: ...

    def get_camera_assets(
        self, issue_id: str, timestamp_ms: Any = None
    ) -> dict[str, Any]: ...

    def get_video(self, issue_id: str) -> dict[str, Any] | None: ...

    def media_ready_summary(self) -> dict[str, Any]: ...


class ProductLayoutProvider:
    """Wrap existing product-layout Asset/Camera/Video indexes for one baseline."""

    def __init__(
        self,
        *,
        asset_index: AssetIndex,
        camera_index: CameraIndex,
        video_index: VideoIndex,
        label: str = "product_layout",
    ):
        self.asset_index = asset_index
        self.camera_index = camera_index
        self.video_index = video_index
        self.label = label

    def has_issue(self, issue_id: str) -> bool:
        return self.asset_index.has_issue(issue_id)

    def get_assets(self, issue_id: str) -> dict[str, Any]:
        return self.asset_index.get_assets(issue_id)

    def get_thumbnail_source(self, issue_id: str) -> dict[str, Any] | None:
        return self.asset_index.get_thumbnail_source(issue_id)

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None:
        path = self.asset_index.get_asset_path(issue_id, asset_id)
        if path is not None:
            return path
        path = self.camera_index.get_asset_path(issue_id, asset_id)
        if path is not None:
            return path
        return self.video_index.get_asset_path(issue_id, asset_id)

    def get_camera_assets(
        self, issue_id: str, timestamp_ms: Any = None
    ) -> dict[str, Any]:
        return self.camera_index.get_assets(issue_id, timestamp_ms)

    def get_video(self, issue_id: str) -> dict[str, Any] | None:
        return self.video_index.get_video(issue_id)

    def media_ready_summary(self) -> dict[str, Any]:
        indexed = self.asset_index.refresh()
        return {
            "provider": "product_layout",
            "label": self.label,
            "bev_indexed_issues": indexed,
            "camera_root_available": self.camera_index.camera_root.is_dir(),
            "video_root_available": self.video_index.video_root.is_dir(),
        }


class BagsAresAnimationProvider:
    """0626 bag layout: frames_v2 BEV + animation job videos + optional camera."""

    _offset_name = re.compile(
        r"^bev_(?P<sign>[+-]?)(?P<ms>\d+)ms\.(?:jpg|jpeg|png)$", re.IGNORECASE
    )
    _issue_dir = re.compile(r"^(?P<issue>[A-Za-z0-9_-]{3,128})(?:_.*)?$")

    def __init__(
        self,
        *,
        bev_frames_root: Path,
        animation_root: Path,
        animation_job_ids: tuple[int, ...] = (),
        camera_root: Path | None = None,
        base_path: str = "",
    ):
        self.bev_frames_root = Path(bev_frames_root).resolve()
        self.animation_root = Path(animation_root).resolve()
        self.animation_job_ids = tuple(int(x) for x in animation_job_ids)
        self.camera_root = Path(camera_root).resolve() if camera_root else None
        self.base_path = base_path
        self._lock = threading.RLock()
        self._bev_assets: dict[str, dict[str, Path]] = {}
        self._video_assets: dict[str, dict[str, Path]] = {}
        self._camera = (
            CameraIndex(self.camera_root, base_path=base_path)
            if self.camera_root
            else None
        )
        self._video_by_issue: dict[str, dict[str, Any]] | None = None

    def has_issue(self, issue_id: str) -> bool:
        return bool(self._find_bev_dir(issue_id)) or self.get_video(issue_id) is not None

    def get_assets(self, issue_id: str) -> dict[str, Any]:
        folder = self._find_bev_dir(issue_id)
        if folder is None:
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "capture": {},
            }
        frames: list[dict[str, Any]] = []
        assets: dict[str, Path] = {}
        for child in sorted(folder.iterdir(), key=lambda p: p.name):
            if not child.is_file():
                continue
            match = self._offset_name.match(child.name)
            if not match:
                continue
            sign = match.group("sign") or "+"
            ms = int(match.group("ms"))
            if sign == "-":
                ms = -ms
            path = child.resolve()
            if not self._within(self.bev_frames_root, path):
                continue
            asset_id = f"frame-0-{len(frames)}"
            assets[asset_id] = path
            frames.append(
                {
                    "id": asset_id,
                    "offset_ms": ms,
                    "offset_sec": ms / 1000.0,
                    "url": with_base_path(
                        self.base_path,
                        f"/api/assets/{quote(issue_id)}/{asset_id}",
                    ),
                    "size_bytes": path.stat().st_size,
                }
            )
        frames.sort(key=lambda item: (abs(int(item["offset_ms"])), int(item["offset_ms"])))
        # Re-number after sort so asset_ids stay stable by presentation order.
        renumbered: list[dict[str, Any]] = []
        renumbered_assets: dict[str, Path] = {}
        for index, frame in enumerate(frames):
            asset_id = f"frame-0-{index}"
            old_id = str(frame["id"])
            path = assets[old_id]
            renumbered_assets[asset_id] = path
            renumbered.append(
                {
                    **frame,
                    "id": asset_id,
                    "url": with_base_path(
                        self.base_path,
                        f"/api/assets/{quote(issue_id)}/{asset_id}",
                    ),
                }
            )
        with self._lock:
            self._bev_assets[issue_id] = renumbered_assets
        return {
            "available": bool(renumbered),
            "issue_id": issue_id,
            "frames": renumbered,
            "capture": {
                "source": "bags_ares_animation",
                "frames_dir": folder.name,
            },
        }

    def get_thumbnail_source(self, issue_id: str) -> dict[str, Any] | None:
        assets = self.get_assets(issue_id)
        frames = assets.get("frames") if isinstance(assets, dict) else None
        if not isinstance(frames, list) or not frames:
            return None

        def distance(frame: dict[str, Any]) -> tuple[float, int]:
            try:
                return abs(float(frame.get("offset_ms"))), frames.index(frame)
            except (TypeError, ValueError):
                return float("inf"), frames.index(frame)

        selected = min(
            (frame for frame in frames if isinstance(frame, dict)),
            key=distance,
            default=None,
        )
        if selected is None:
            return None
        asset_id = str(selected.get("id") or "")
        path = self.get_asset_path(issue_id, asset_id)
        if path is None:
            return None
        return {
            "path": path,
            "asset_id": asset_id,
            "offset_ms": selected.get("offset_ms"),
            "offset_sec": selected.get("offset_sec"),
        }

    def get_asset_path(self, issue_id: str, asset_id: str) -> Path | None:
        with self._lock:
            path = self._bev_assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within(self.bev_frames_root, path):
            return path
        self.get_assets(issue_id)
        with self._lock:
            path = self._bev_assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within(self.bev_frames_root, path):
            return path
        with self._lock:
            path = self._video_assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within(self.animation_root, path):
            return path
        self.get_video(issue_id)
        with self._lock:
            path = self._video_assets.get(issue_id, {}).get(asset_id)
        if path and path.is_file() and self._within(self.animation_root, path):
            return path
        if self._camera is not None:
            return self._camera.get_asset_path(issue_id, asset_id)
        return None

    def get_camera_assets(
        self, issue_id: str, timestamp_ms: Any = None
    ) -> dict[str, Any]:
        if self._camera is None:
            return {
                "available": False,
                "issue_id": issue_id,
                "frames": [],
                "capture": {},
            }
        return self._camera.get_assets(issue_id, timestamp_ms)

    def get_video(self, issue_id: str) -> dict[str, Any] | None:
        index = self._ensure_video_index()
        meta = index.get(issue_id)
        if not meta:
            return None
        animation_path = str(meta.get("animation_path") or meta.get("path") or "").strip()
        if not animation_path:
            return None
        candidate = (self.animation_root / animation_path).resolve()
        if not candidate.is_file() or not self._within(self.animation_root, candidate):
            # Some manifests store absolute-ish paths under job dirs.
            for job_id in self.animation_job_ids:
                alt = (self.animation_root / f"job_{job_id}" / animation_path).resolve()
                if alt.is_file() and self._within(self.animation_root, alt):
                    candidate = alt
                    break
            else:
                return None
        asset_id = "video-0"
        with self._lock:
            self._video_assets[issue_id] = {asset_id: candidate}
        duration = meta.get("duration_sec")
        try:
            duration_sec = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None
        return {
            "available": True,
            "issue_id": issue_id,
            "id": asset_id,
            "source": "ares_animation",
            "url": with_base_path(
                self.base_path, f"/api/assets/{quote(issue_id)}/{asset_id}"
            ),
            "duration_sec": duration_sec,
            "size_bytes": candidate.stat().st_size,
        }

    def media_ready_summary(self) -> dict[str, Any]:
        bev_dirs = 0
        if self.bev_frames_root.is_dir():
            bev_dirs = sum(1 for path in self.bev_frames_root.iterdir() if path.is_dir())
        video_index = self._ensure_video_index()
        return {
            "provider": "bags_ares_animation",
            "bev_dirs": bev_dirs,
            "video_issues": len(video_index),
            "camera_root_available": bool(
                self.camera_root and self.camera_root.is_dir()
            ),
            "animation_job_ids": list(self.animation_job_ids),
        }

    def _find_bev_dir(self, issue_id: str) -> Path | None:
        if not self.bev_frames_root.is_dir():
            return None
        exact = (self.bev_frames_root / f"{issue_id}_0").resolve()
        if exact.is_dir() and self._within(self.bev_frames_root, exact):
            return exact
        candidates = [
            path.resolve()
            for path in self.bev_frames_root.glob(f"{issue_id}_*")
            if path.is_dir() and self._within(self.bev_frames_root, path)
        ]
        if not candidates:
            # Also accept bare issue_id directory names.
            bare = (self.bev_frames_root / issue_id).resolve()
            if bare.is_dir() and self._within(self.bev_frames_root, bare):
                return bare
            return None
        return sorted(candidates, key=lambda path: path.name)[0]

    def _ensure_video_index(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self._video_by_issue is not None:
                return self._video_by_issue
        mapping: dict[str, dict[str, Any]] = {}
        registry = self.animation_root / "registry.jsonl"
        if registry.is_file():
            self._ingest_jsonl(registry, mapping)
        for job_id in self.animation_job_ids:
            for name in ("manifest.jsonl", "registry.jsonl"):
                candidate = self.animation_root / f"job_{job_id}" / name
                if candidate.is_file():
                    self._ingest_jsonl(candidate, mapping)
        with self._lock:
            self._video_by_issue = mapping
            return self._video_by_issue

    def _ingest_jsonl(self, path: Path, mapping: dict[str, dict[str, Any]]) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    issue_id = str(row.get("issue_id") or "").strip()
                    if not issue_id:
                        continue
                    # Prefer first hit; later files can override if newer keys present.
                    mapping[issue_id] = row
        except OSError:
            return

    @staticmethod
    def _within(root: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False


class MediaRegistry:
    def __init__(
        self,
        *,
        by_id: dict[str, MediaProvider],
        by_scope: dict[str, MediaProvider],
        default_provider: MediaProvider | None = None,
    ):
        self._by_id = dict(by_id)
        self._by_scope = dict(by_scope)
        self._default = default_provider

    def for_baseline_id(self, baseline_id: str) -> MediaProvider | None:
        return self._by_id.get(str(baseline_id or "").strip())

    def for_scope(self, scope: str) -> MediaProvider | None:
        return self._by_scope.get(str(scope or "").strip())

    def resolve_for_issue(
        self, issue_id: str, *, baseline_scope: str = ""
    ) -> MediaProvider | None:
        if baseline_scope:
            provider = self.for_scope(baseline_scope)
            if provider is not None:
                return provider
        return self._default

    def media_ready_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            key: provider.media_ready_summary()
            for key, provider in self._by_id.items()
        }


def build_media_registry(
    registry: BaselineRegistry,
    *,
    base_path: str,
    product_asset_index: AssetIndex,
    product_camera_index: CameraIndex,
    product_video_index: VideoIndex,
    data_dir: Path | None = None,
    ra_root: Path | None = None,
) -> MediaRegistry:
    """Construct providers for each registry entry.

    ``product_layout`` reuses the process-global 0508 indexes built from Settings
    env (current production path). bags providers are constructed per entry.
    """

    by_id: dict[str, MediaProvider] = {}
    by_scope: dict[str, MediaProvider] = {}
    product = ProductLayoutProvider(
        asset_index=product_asset_index,
        camera_index=product_camera_index,
        video_index=product_video_index,
        label="product_layout",
    )
    for entry in registry.entries:
        provider: MediaProvider
        if entry.media.provider == "bags_ares_animation":
            if entry.media.bev_frames_root is None or entry.media.animation_root is None:
                # Misconfigured entry: fall back to empty product so calls are safe.
                provider = product
            else:
                provider = BagsAresAnimationProvider(
                    bev_frames_root=entry.media.bev_frames_root,
                    animation_root=entry.media.animation_root,
                    animation_job_ids=entry.media.animation_job_ids,
                    camera_root=entry.media.camera_root,
                    base_path=base_path,
                )
        else:
            provider = product
        by_id[entry.id] = provider
        by_scope[entry.scope] = provider
    default = by_id.get(registry.default_ids()[0]) if registry.entries else product
    return MediaRegistry(by_id=by_id, by_scope=by_scope, default_provider=default or product)
