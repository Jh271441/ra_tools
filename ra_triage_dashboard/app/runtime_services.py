"""Explicit construction of shared runtime services; no import-time instances."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from .assets import AssetIndex, CameraIndex, VideoIndex
from .auth import validate_identity_settings
from .autotriage_source import AutoTriageSource
from .baseline_registry import (
    BaselineRegistry,
    legacy_registry_from_settings,
    load_baseline_registry,
)
from .batch_prediction_runner import BatchPredictionRunner
from .db import Database
from .issue_tag_sources import IssueTagSourceIndex
from .intent_dataset_registry import IntentDatasetIndex
from .media_registry import MediaRegistry, build_media_registry
from .model_catalog import ModelCatalog
from .prompt_catalog import PromptCatalog
from .settings import Settings
from .review_notification_dispatcher import ReviewNotificationDispatcher

@dataclass(frozen=True)
class RuntimeServices:
    database: Database
    asset_index: AssetIndex
    camera_index: CameraIndex
    video_index: VideoIndex
    intent_dataset_registry: IntentDatasetIndex
    baseline_registry: BaselineRegistry
    media_registry: MediaRegistry
    model_catalog: ModelCatalog
    prompt_catalog: PromptCatalog
    autotriage_source: AutoTriageSource
    batch_prediction_runner: BatchPredictionRunner
    review_notification_dispatcher: ReviewNotificationDispatcher
    issue_tag_sources: IssueTagSourceIndex


def load_active_baseline_registry(settings: Settings) -> BaselineRegistry:
    path = settings.baselines_file
    if path is not None and Path(path).is_file():
        return load_baseline_registry(
            Path(path),
            ra_auto_triage_root=settings.ra_auto_triage_root,
        )
    return legacy_registry_from_settings(
        baseline_id="0508",
        label="0508",
        scope=settings.baseline_scope,
        dataset=settings.baseline_dataset,
        xlsx=settings.baseline_label_xlsx,
        layout_id=settings.baseline_scope,
    )


def build_runtime_services(settings: Settings) -> RuntimeServices:
    """Construct each dependency once, in the established startup order."""
    validate_identity_settings(settings)
    database = Database(
        settings.database_url,
        postgres_migrations_dir=settings.postgres_migrations_dir,
        pool_size=10,
    )
    asset_index = AssetIndex(
        ra_root=settings.ares_ra_root,
        manifest_path=settings.ares_manifest,
        base_path=settings.base_path,
    )
    camera_index = CameraIndex(settings.camera_root, base_path=settings.base_path)
    video_index = VideoIndex(settings.ares_video_root, base_path=settings.base_path)
    intent_dataset_registry = IntentDatasetIndex.from_file(
        Path(
            os.getenv(
                "DASHBOARD_INTENT_DATASETS_FILE",
                str(settings.app_root / "config" / "intent_datasets.json"),
            )
        ).expanduser().resolve(),
        base_path=settings.base_path,
    )

    baseline_registry = load_active_baseline_registry(settings)
    media_registry = build_media_registry(
        baseline_registry,
        base_path=settings.base_path,
        product_asset_index=asset_index,
        product_camera_index=camera_index,
        product_video_index=video_index,
        data_dir=settings.data_dir,
        ra_root=settings.ra_auto_triage_root,
    )
    model_catalog = ModelCatalog(settings)
    prompt_catalog = PromptCatalog(settings.ra_auto_triage_root)
    autotriage_source = AutoTriageSource(settings.autotriage_api_base_url)
    batch_prediction_runner = BatchPredictionRunner(settings, database)
    review_notification_dispatcher = ReviewNotificationDispatcher(settings, database)
    issue_tag_sources = IssueTagSourceIndex()
    return RuntimeServices(
        database=database,
        asset_index=asset_index,
        camera_index=camera_index,
        video_index=video_index,
        intent_dataset_registry=intent_dataset_registry,
        baseline_registry=baseline_registry,
        media_registry=media_registry,
        model_catalog=model_catalog,
        prompt_catalog=prompt_catalog,
        autotriage_source=autotriage_source,
        batch_prediction_runner=batch_prediction_runner,
        review_notification_dispatcher=review_notification_dispatcher,
        issue_tag_sources=issue_tag_sources,
    )
