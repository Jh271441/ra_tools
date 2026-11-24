"""Server-side label sidecar for GT revisions and incremental result recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import signal
import threading

from sqlalchemy import select

from app.database import SessionLocal
from app.infra.locks import LockBusyError, advisory_lock
from app.models import ReleaseSimulationBatch
from app.services import (
    auto_triage_metrics,
    label_cycle,
    published_scene_labels,
    release_workflow as w,
)
from app.services.publication_core import published_batch

logger = logging.getLogger(__name__)


def tick() -> None:
    if os.getenv("LABEL_REFRESH_ENABLED") != "1":
        return
    try:
        lock_ctx = advisory_lock("ra_sim:label_cycle", blocking=False)
        lock_ctx.__enter__()
    except LockBusyError:
        return
    try:
        with SessionLocal() as db:
            config = w.effective_config(db)
            releases = set(db.scalars(select(ReleaseSimulationBatch.release)))
            for release in sorted(releases):
                batch = published_batch(db, release)
                if batch and w.get_state(db, "release_monitor:" + release):
                    previous = w.get_state(db, "label_cycle:" + release)
                    try:
                        elapsed = (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(previous["checked_at"])
                        ).total_seconds()
                        if 0 <= elapsed < label_cycle.CHECK_SECONDS:
                            continue
                    except (KeyError, TypeError, ValueError):
                        pass
                    state = label_cycle.refresh_release(db, config, batch)
                    published_scene_labels.synchronize(db, config, batch, state)
                    auto_triage_metrics.refresh_observed(db, release)
    finally:
        lock_ctx.__exit__(None, None, None)


def main() -> None:
    if os.getenv("LABEL_REFRESH_ENABLED") != "1":
        raise RuntimeError("Label refresh is disabled")
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    while not stopping.is_set():
        try:
            tick()
        except Exception:
            logger.exception("Label sidecar tick failed")
        stopping.wait(label_cycle.CHECK_SECONDS)


if __name__ == "__main__":
    main()
