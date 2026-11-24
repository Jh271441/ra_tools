"""Recover authorized work independently from hourly plan scheduling."""

import asyncio
import logging

from app.infra.settings import (
    EVALUATION_POLL_SECONDS as POLL_SECONDS,
    evaluation_scheduling_enabled as scheduling_enabled,
    evaluation_worker_enabled as enabled,
)
from app.services import evaluation_pipeline


async def monitor():
    while True:
        try:
            await asyncio.to_thread(evaluation_pipeline.tick, schedule=scheduling_enabled())
        except Exception:
            logging.getLogger(__name__).exception("Evaluation work retained; retry next interval")
        await asyncio.sleep(POLL_SECONDS)
