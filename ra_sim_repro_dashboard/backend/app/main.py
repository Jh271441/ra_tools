from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import os
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.database import init_db
from app.api.release_routes import router as release_router
from app.services.release_workflow import tick


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    async def monitor():
        while True:
            await asyncio.to_thread(tick)
            await asyncio.sleep(900)

    task = (
        asyncio.create_task(monitor())
        if os.getenv("RELEASE_WORKFLOW_ENABLED") == "1"
        else None
    )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="RA Sim Repro Dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(release_router)
