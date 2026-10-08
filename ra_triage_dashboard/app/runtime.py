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
from .web_paths import render_index_html, with_base_path


logger = logging.getLogger("ra_triage_dashboard")
_identity_diagnostic_observations = BoundedObservationSet[
    tuple[str, tuple[tuple[str, str], ...]]
](max_entries=1024)
settings = Settings.from_env()
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

trail_sync_lock = threading.Lock()
gt_sync_lock = threading.Lock()
review_image_semaphore = asyncio.Semaphore(2)
# Gallery pages request many thumbs; allow more parallel JPEG encodes once the
# source path is resolved. Cache hits never take this semaphore.
thumbnail_image_semaphore = asyncio.Semaphore(8)
trail_detail_semaphore = asyncio.Semaphore(2)
APP_STARTED_AT = datetime.now(timezone.utc)
APP_STARTED_MONOTONIC = time.monotonic()
INDEX_HTML = render_index_html(
    (settings.static_dir / "index.html").read_text(encoding="utf-8"),
    settings.base_path,
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
