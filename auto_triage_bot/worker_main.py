from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .service import RemoteBotWorker
from .settings import Settings


def create_worker_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    worker = RemoteBotWorker(settings=config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        config.ensure_directories()
        task = None
        if config.enabled:
            task = asyncio.create_task(worker.run(), name="auto-triage-remote-worker")
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Auto Triage Worker", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, object]:
        if worker.last_error and not worker.relay_reachable:
            raise HTTPException(
                503,
                {
                    "status": "degraded",
                    "role": "offline_worker",
                    "relay_reachable": False,
                },
            )
        return {
            "status": "ok",
            "enabled": config.enabled,
            "role": "offline_worker",
            "relay_reachable": worker.relay_reachable,
            "delivery_mode": config.delivery_mode,
            "model_configured": bool(config.model_id),
            "dashboard_mode": "read_only_loopback",
        }

    app.state.bot_settings = config
    app.state.bot_worker = worker
    return app


app = create_worker_app()
