"""Dedicated server-side release scheduler, independent of API/browser lifetime."""
from __future__ import annotations

import logging
import os
import threading
import signal

from app.database import init_db
from app.services.release_workflow import tick


def main():
    if os.getenv("RELEASE_WORKFLOW_ENABLED") != "1":
        raise RuntimeError("Release workflow is disabled")
    if os.getenv("RELEASE_WORKFLOW_RUNNER") != "worker":
        raise RuntimeError("Dedicated release worker is not configured")
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    init_db()
    while not stopping.is_set():
        try:
            tick()
        except Exception:
            logging.getLogger(__name__).exception("Release tick failed; retry next interval")
        stopping.wait(900)


if __name__ == "__main__":
    main()
