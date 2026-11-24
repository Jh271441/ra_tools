from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import os
import logging
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.evaluation_routes import router as evaluation_router
from app.api.release_routes import router as release_router
from app.api.routes import router
from app.database import init_db
from app.infra.audit import install_db_audit_sink
from app.schemas import AuthMeResponse
from app.security import (
    identity_can_write,
    load_security_config,
    request_identity,
    security_middleware,
    validate_security_settings,
)
from app.services import evaluation_worker
from app.services.workflow_orchestrator import tick


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    init_db()
    install_db_audit_sink()

    async def monitor():
        while True:
            try:
                await asyncio.to_thread(tick)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Release monitor tick failed; retry next interval"
                )
            await asyncio.sleep(900)

    task = (
        asyncio.create_task(monitor())
        if os.getenv("RELEASE_WORKFLOW_ENABLED") == "1"
        and os.getenv("RELEASE_WORKFLOW_RUNNER", "api") == "api"
        else None
    )
    evaluation_task = (
        asyncio.create_task(evaluation_worker.monitor())
        if evaluation_worker.enabled() and os.getenv("EVALUATION_WORKER_RUNNER", "api") == "api"
        else None
    )
    try:
        yield
    finally:
        if evaluation_task:
            evaluation_task.cancel()
            with suppress(asyncio.CancelledError):
                await evaluation_task
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


_security_cfg = load_security_config()

app = FastAPI(
    title="RA Sim Repro Dashboard API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_security_cfg.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-RA-Sim-Client", "X-RA-Sim-Request"],
)
app.middleware("http")(security_middleware)


@app.get("/api/auth/me", response_model=AuthMeResponse)
def auth_me(request: Request) -> AuthMeResponse:
    cfg = load_security_config()
    identity = request_identity(request, cfg)
    return AuthMeResponse(
        **identity.as_dict(
            can_write=identity_can_write(identity, cfg),
            deployment_mode=cfg.deployment_mode,
        )
    )


app.include_router(router)
app.include_router(release_router)
app.include_router(evaluation_router)
