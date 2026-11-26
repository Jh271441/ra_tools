from __future__ import annotations

from .runtime_services import build_runtime_services
from .runtime_catalogs import MISSING_EVIDENCE_CATALOG, REVIEW_TAG_CATALOG, REVIEW_TAG_KEYS, REVIEW_TAG_MANAGED_GROUPS, REVIEW_TAG_SCENE_GROUPS, REVIEW_TAG_ALIASES, EXAMPLE_CASES

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .observability import BoundedObservationSet
from .settings import Settings
from .video_playback import VideoPlaybackCache
from .video_stream import VideoStreamCache
from .vite_assets import render_vite_assets_json
from .web_paths import render_index_html, with_base_path


logger = logging.getLogger("ra_triage_dashboard")
_identity_diagnostic_observations = BoundedObservationSet[
    tuple[str, tuple[tuple[str, str], ...]]
](max_entries=1024)
settings = Settings.from_env()
video_playback_cache = VideoPlaybackCache(settings.data_dir / "video_playback")
video_stream_cache = VideoStreamCache(settings.data_dir / "video_stream")
_services = build_runtime_services(settings)
database = _services.database
asset_index = _services.asset_index
camera_index = _services.camera_index
video_index = _services.video_index
intent_dataset_registry = _services.intent_dataset_registry
baseline_registry = _services.baseline_registry
media_registry = _services.media_registry
model_catalog = _services.model_catalog
prompt_catalog = _services.prompt_catalog
autotriage_source = _services.autotriage_source
batch_prediction_runner = _services.batch_prediction_runner
review_notification_dispatcher = _services.review_notification_dispatcher
issue_tag_sources = _services.issue_tag_sources
artifact_store = _services.artifact_store

class _LoopScopedSemaphore:
    """Lazily bind one asyncio.Semaphore per running event loop (Python 3.9 safe)."""

    def __init__(self, value: int) -> None:
        self._value = value
        self._by_loop: dict[int, asyncio.Semaphore] = {}

    def _current(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        key = id(loop)
        sem = self._by_loop.get(key)
        if sem is None:
            if len(self._by_loop) > 16:
                self._by_loop.clear()
            sem = asyncio.Semaphore(self._value)
            self._by_loop[key] = sem
        return sem

    async def __aenter__(self) -> bool:
        return await self._current().__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return await self._current().__aexit__(exc_type, exc, tb)

    async def acquire(self) -> bool:
        return await self._current().acquire()

    def release(self) -> None:
        self._current().release()


trail_sync_lock = threading.Lock()
gt_sync_lock = threading.Lock()
review_image_semaphore = _LoopScopedSemaphore(2)
# Gallery pages request many thumbs; allow more parallel JPEG encodes once the
# source path is resolved. Cache hits never take this semaphore.
thumbnail_image_semaphore = _LoopScopedSemaphore(8)
trail_detail_semaphore = _LoopScopedSemaphore(2)
APP_STARTED_AT = datetime.now(timezone.utc)
APP_STARTED_MONOTONIC = time.monotonic()
INDEX_HTML = render_index_html(
    (settings.static_dir / "index.html").read_text(encoding="utf-8"),
    settings.base_path,
    vite_assets_json=render_vite_assets_json(settings.static_dir),
)

def _public_path(path: str) -> str:
    return with_base_path(settings.base_path, path)




runtime_state: dict[str, Any] = {
    "baseline": {"status": "not_loaded", "message": "等待加载 0508 baseline。", "count": 0},
    "baselines": [],
    "baseline_conflicts": [],
    "trail_sync": {
        "status": "not_started",
        "message": "尚未检查 Trail 模型字段。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
    },
    # Process-local in-flight state keyed by baseline scope. Persisted sync
    # state remains authoritative and survives restarts in gt_sync_state.
    "gt_sync": {},
}
