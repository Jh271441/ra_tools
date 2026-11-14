"""Recover authorized work independently from hourly plan scheduling."""
import asyncio
import logging
import os

POLL_SECONDS = 30


def enabled():
    return os.getenv('EVALUATION_WORKER_ENABLED', '1') == '1'


def scheduling_enabled():
    return enabled() and os.getenv('EVALUATION_CRON_ENABLED') == '1'


async def monitor():
    from app.services.evaluation_pipeline import tick
    while True:
        try:
            await asyncio.to_thread(tick, schedule=scheduling_enabled())
        except Exception:
            logging.getLogger(__name__).exception('Evaluation work retained; retry next interval')
        await asyncio.sleep(POLL_SECONDS)
