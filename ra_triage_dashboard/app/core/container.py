"""Application dependency container mounted on app.state.container."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import runtime as _runtime


@dataclass
class AppContainer:
    """Explicit holder for shared Dashboard runtime services."""

    settings: Any
    database: Any
    asset_index: Any
    camera_index: Any
    video_index: Any
    intent_dataset_registry: Any
    baseline_registry: Any
    media_registry: Any
    model_catalog: Any
    prompt_catalog: Any
    autotriage_source: Any
    batch_prediction_runner: Any
    review_notification_dispatcher: Any
    issue_tag_sources: Any
    video_playback_cache: Any
    video_stream_cache: Any
    runtime_state: dict[str, Any]

    @classmethod
    def from_runtime(cls) -> AppContainer:
        """Bind to the active runtime module instances without duplicating pools."""
        return cls(
            settings=_runtime.settings,
            database=_runtime.database,
            asset_index=_runtime.asset_index,
            camera_index=_runtime.camera_index,
            video_index=_runtime.video_index,
            intent_dataset_registry=_runtime.intent_dataset_registry,
            baseline_registry=_runtime.baseline_registry,
            media_registry=_runtime.media_registry,
            model_catalog=_runtime.model_catalog,
            prompt_catalog=_runtime.prompt_catalog,
            autotriage_source=_runtime.autotriage_source,
            batch_prediction_runner=_runtime.batch_prediction_runner,
            review_notification_dispatcher=_runtime.review_notification_dispatcher,
            issue_tag_sources=_runtime.issue_tag_sources,
            video_playback_cache=_runtime.video_playback_cache,
            video_stream_cache=_runtime.video_stream_cache,
            runtime_state=_runtime.runtime_state,
        )
