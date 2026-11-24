from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from .static_assets import dashboard_static_app
from .response_compression import TextResponseCompressionMiddleware
from .middleware import (
    BasePathTimingAndSecurityMiddleware,
    IdentityDiagnosticsMiddleware,
    ProductionWriteGuardMiddleware,
    RequestSizeGuardMiddleware,
    evaluate_request_size_guard,
)
from .gt_sync import gt_refresh_due

from .support.baselines import (
    bootstrap_baseline,
    bootstrap_model_result,
)
from .support.gt_sync import (
    sync_authoritative_gt,
)
from .support.trail_models import (
    sync_trail_model_fields,
)
from .runtime import (
    EXAMPLE_CASES,
    _identity_diagnostic_observations,
    asset_index,
    batch_prediction_runner,
    database,
    issue_tag_sources,
    intent_dataset_registry,
    review_notification_dispatcher,
    settings,
    video_playback_cache,
    video_stream_cache,
)
from .routers import (
    analysis,
    artifacts,
    batch,
    case_annotations,
    case_comments,
    comment_mutations,
    issue_discussion,
    campaigns,
    cases,
    core,
    daily_cron,
    daily_review,
    imports,
    inference,
    labeling,
    reviews,
    runs,
    run_collections,
    trail_update,
    trail_history,
    intent_labeling,
    legacy_cutover,
    version_datasets,
    version_metrics,
    rd_results,
)

logger = logging.getLogger("ra_triage_dashboard")


async def _trail_sync_startup() -> None:
    """Best-effort Trail model-field probe; never blocks process startup."""

    try:
        await asyncio.to_thread(
            sync_trail_model_fields,
            create_run=False,
            requested_by="system",
            identity_source="service_startup",
            identity_verified=False,
            trigger="startup",
        )
    except Exception:
        logger.exception("background Trail model-field sync failed")


def _gt_sync_needs_remote_refresh() -> bool:
    """Whether the periodic worker should hit Trail now.

    Hot paths (page open, status) must only read local DB / baseline xlsx.
    Remote Trail is optional freshness, not a gate for serving GT.
    """

    from .support.gt_sync import gt_sync_status

    return gt_refresh_due(
        gt_sync_status(), interval_seconds=settings.gt_sync_interval_seconds
    )


async def _authoritative_gt_sync_loop() -> None:
    """Refresh Trail GT into local tables in the background only.

    Page-open GT labels are served from the database (baseline seed + last
    successful Trail snapshot). This worker may talk to Trail, but never
    blocks HTTP lifespan / first paint.
    """

    if settings.gt_sync_startup_delay_seconds:
        await asyncio.sleep(settings.gt_sync_startup_delay_seconds)
    while True:
        try:
            needs_remote = await asyncio.to_thread(_gt_sync_needs_remote_refresh)
        except Exception:
            logger.exception("failed to evaluate local GT freshness")
            needs_remote = True
        if needs_remote:
            sync_task = asyncio.create_task(
                asyncio.to_thread(
                    sync_authoritative_gt,
                    requested_by="system",
                    identity_source="service_periodic",
                    identity_verified=False,
                    trigger="periodic",
                )
            )
            try:
                await asyncio.shield(sync_task)
            except asyncio.CancelledError:
                # A worker thread cannot be cancelled safely. Wait for its current
                # transaction before lifespan closes the database pool.
                await sync_task
                raise
        else:
            logger.info(
                "skip periodic Trail GT refresh; snapshot is fresh or sync is running"
            )
        await asyncio.sleep(settings.gt_sync_interval_seconds)

@asynccontextmanager
async def lifespan(_: FastAPI):
    from .human_publisher import run_human_publisher
    human_label_task: asyncio.Task[None] | None = None
    gt_sync_task: asyncio.Task[None] | None = None
    trail_sync_task: asyncio.Task[None] | None = None
    review_notification_task: asyncio.Task[None] | None = None
    settings.ensure_directories()
    database.init()
    database.bootstrap_access_users(
        writers=settings.sso_write_users,
        administrators=settings.team_default_managers,
    )
    database.bootstrap_mention_users()
    human_label_task = asyncio.create_task(run_human_publisher(database, settings), name='human-label-publication')
    if settings.seed_examples_enabled:
        database.seed_examples(EXAMPLE_CASES)
    # Local-only seed from baseline workbooks / registry. No Trail I/O.
    bootstrap_baseline()
    # Historical spot-check tags are read-only form suggestions.  They do not
    # create Reviews, modify GT, or block startup when an optional file is
    # unavailable.
    issue_tag_sources.reload(settings.issue_tag_sources)
    asset_index.refresh(force=True)
    intent_dataset_registry.refresh()
    bootstrap_model_result()
    # Never await remote Trail during startup — it freezes first paint.
    if settings.trail_sync_on_start:
        trail_sync_task = asyncio.create_task(
            _trail_sync_startup(),
            name="trail-sync-startup",
        )
    if settings.gt_sync_enabled:
        gt_sync_task = asyncio.create_task(
            _authoritative_gt_sync_loop(),
            name="authoritative-gt-sync",
        )
    if settings.dchat_notifications_enabled:
        review_notification_task = asyncio.create_task(
            review_notification_dispatcher.run(),
            name="review-dchat-notifications",
        )
    batch_prediction_runner.resume_queued_predictions()
    try:
        yield
    finally:
        for task in (human_label_task, review_notification_task, gt_sync_task, trail_sync_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await asyncio.to_thread(batch_prediction_runner.shutdown)
        await asyncio.to_thread(video_playback_cache.shutdown)
        await asyncio.to_thread(video_stream_cache.shutdown)
        from .planning_constraints import shutdown as shutdown_planning_constraints
        await asyncio.to_thread(shutdown_planning_constraints)
        await asyncio.to_thread(database.close)


app = FastAPI(
    title="RA Triage Workbench",
    version="1.9.2",
    lifespan=lifespan,
)
# Pure ASGI middleware stack (Starlette wraps LIFO: last added runs outermost).
app.add_middleware(TextResponseCompressionMiddleware)
app.add_middleware(
    IdentityDiagnosticsMiddleware,
    get_settings=lambda: settings,
    get_observations=lambda: _identity_diagnostic_observations,
)
app.add_middleware(
    ProductionWriteGuardMiddleware,
    get_settings=lambda: settings,
    get_database=lambda: database,
)
app.add_middleware(RequestSizeGuardMiddleware)
app.add_middleware(
    BasePathTimingAndSecurityMiddleware,
    get_settings=lambda: settings,
)


async def request_size_guard(request: Request, call_next):
    """Compatibility wrapper preserving direct middleware-function tests."""
    error_response, _, _ = evaluate_request_size_guard(
        request.method,
        request.url.path,
        request.headers,
    )
    if error_response is not None:
        return error_response
    return await call_next(request)


app.mount(
    "/static",
    dashboard_static_app(settings.static_dir),
    name="static",
)

app.include_router(version_datasets.router)
app.include_router(version_metrics.router)
from .routers import human_publications
app.include_router(human_publications.router)
app.include_router(rd_results.router)
app.include_router(core.router)
app.include_router(artifacts.router)
app.include_router(daily_cron.router)
app.include_router(daily_review.router)
app.include_router(cases.router)
app.include_router(case_comments.router)
app.include_router(comment_mutations.router)
app.include_router(issue_discussion.router)
app.include_router(campaigns.router)
app.include_router(case_annotations.router)
app.include_router(reviews.router)
app.include_router(runs.router)
app.include_router(run_collections.router)
app.include_router(analysis.router)
app.include_router(imports.router)
app.include_router(batch.router)
app.include_router(inference.router)
app.include_router(labeling.router)
app.include_router(trail_update.router)
app.include_router(trail_history.router)
app.include_router(intent_labeling.router)
app.include_router(legacy_cutover.router)
