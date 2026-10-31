"""Extend the existing personal media controller inside its existing global lock."""
import sys
import time
from pathlib import Path

sys.path.insert(0, '/volume/home/workspace/ra_auto_triage')
from tools.manual_sidecar import controller, recovery
from offline_daily import local_tick, save, TASK

original = controller.process_daily


def process_daily():
    try:
        return original()
    finally:
        try:
            local_tick(controller, recovery)
            save(TASK/'daily-sidecar/local-scheduler-error.json',
                 dict(active=False, at=time.time()))
        except Exception as exc:
            save(TASK/'daily-sidecar/local-scheduler-error.json',
                 dict(active=True, code=type(exc).__name__, at=time.time()))


controller.process_daily = process_daily
controller.main()
