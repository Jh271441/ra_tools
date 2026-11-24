"""Dedicated standalone evaluation worker process, decoupled from the FastAPI API process."""

from __future__ import annotations

import logging
import os
import signal
import threading

from app.database import init_db
from app.services import evaluation_worker
from app.services.evaluation_pipeline import tick

logger = logging.getLogger(__name__)


def main() -> None:
    if not evaluation_worker.enabled():
        raise RuntimeError("Evaluation worker is disabled (EVALUATION_WORKER_ENABLED=0)")
    if os.getenv("EVALUATION_WORKER_RUNNER", "worker") != "worker":
        raise RuntimeError("Dedicated evaluation worker requires EVALUATION_WORKER_RUNNER=worker")
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    init_db()
    logger.info(
        "Starting dedicated evaluation worker (poll=%ss cron=%s)",
        evaluation_worker.POLL_SECONDS,
        evaluation_worker.scheduling_enabled(),
    )
    while not stopping.is_set():
        try:
            tick(schedule=evaluation_worker.scheduling_enabled())
        except Exception:
            logger.exception("Evaluation worker tick failed; retrying next interval")
        stopping.wait(evaluation_worker.POLL_SECONDS)
    logger.info("Evaluation worker stopped cleanly")


if __name__ == "__main__":
    main()
