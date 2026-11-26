"""Standalone background worker daemon for RA Triage Workbench.

Run separately from web uvicorn workers when scaling horizontally:
    DASHBOARD_EMBEDDED_WORKERS=false uvicorn app.main:app --workers 4
    python -m app.workers.main

All external side-effect tasks coordinate via PostgreSQL/SQLite `worker_leases`
so overlapping restarts or multi-worker deployments never duplicate Trail writes,
GT syncs, or DChat notifications.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from .leases import WorkerLeaseManager, make_worker_owner_id, run_with_lease

logger = logging.getLogger("ra_triage_dashboard.workers")


async def run_standalone_worker() -> None:
    """Boot runtime dependencies and run all Workbench background workers."""
    from ..human_publisher import run_human_publisher
    from ..main import _authoritative_gt_sync_loop, _trail_sync_startup
    from ..runtime import (
        batch_prediction_runner,
        database,
        review_notification_dispatcher,
        settings,
    )

    settings.ensure_directories()
    database.init(recover_interrupted_jobs=False)
    batch_prediction_runner.set_lease_gating(True, held=False)
    lease_manager = WorkerLeaseManager(database, owner_id=make_worker_owner_id("standalone"))

    async def _batch_prediction_leader() -> None:
        await asyncio.to_thread(
            database.recover_interrupted_jobs,
            exclude_job_ids=batch_prediction_runner.active_job_ids(),
        )
        batch_prediction_runner.set_lease_held(True)
        try:
            while True:
                await asyncio.to_thread(batch_prediction_runner.resume_queued_work)
                await asyncio.sleep(5.0)
        finally:
            await asyncio.to_thread(batch_prediction_runner.revoke_lease)

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            run_with_lease(
                lease_manager,
                "human-label-publication",
                lambda: run_human_publisher(database, settings),
            ),
            name="human-label-publication",
        ),
        asyncio.create_task(
            run_with_lease(
                lease_manager,
                "batch-prediction-runner",
                _batch_prediction_leader,
                ttl_seconds=60.0,
                retry_seconds=5.0,
            ),
            name="batch-prediction-runner",
        ),
    ]
    if settings.trail_sync_on_start:
        tasks.append(
            asyncio.create_task(
                run_with_lease(
                    lease_manager,
                    "trail-sync-startup",
                    _trail_sync_startup,
                    ttl_seconds=120.0,
                ),
                name="trail-sync-startup",
            )
        )
    if settings.gt_sync_enabled:
        tasks.append(
            asyncio.create_task(
                run_with_lease(
                    lease_manager,
                    "authoritative-gt-sync",
                    _authoritative_gt_sync_loop,
                    ttl_seconds=120.0,
                ),
                name="authoritative-gt-sync",
            )
        )
    if settings.dchat_notifications_enabled:
        tasks.append(
            asyncio.create_task(
                run_with_lease(
                    lease_manager,
                    "review-dchat-notifications",
                    review_notification_dispatcher.run,
                    ttl_seconds=60.0,
                ),
                name="review-dchat-notifications",
            )
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await asyncio.to_thread(batch_prediction_runner.shutdown)
        await asyncio.to_thread(lease_manager.release, "batch-prediction-runner")
        await asyncio.to_thread(database.close)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_standalone_worker())


if __name__ == "__main__":
    main()
