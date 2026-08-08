from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import has_same_origin_mutation_marker, identity_header_candidates, request_identity
from .http_support import *  # noqa: F401,F403
from .runtime import *  # noqa: F401,F403
from .routers import analysis, batch, cases, core, imports, inference, reviews, runs

logger = logging.getLogger("ra_triage_dashboard")

@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    database.init()
    database.bootstrap_access_users(
        writers=settings.sso_write_users,
        administrators=settings.team_default_managers,
    )
    database.seed_examples(EXAMPLE_CASES)
    bootstrap_baseline()
    asset_index.refresh(force=True)
    bootstrap_model_result()
    if settings.trail_sync_on_start:
        await asyncio.to_thread(
            sync_trail_model_fields,
            create_run=False,
            requested_by="system",
            identity_source="service_startup",
            identity_verified=False,
            trigger="startup",
        )
    batch_prediction_runner.resume_queued_predictions()
    try:
        yield
    finally:
        await asyncio.to_thread(batch_prediction_runner.shutdown)
        await asyncio.to_thread(database.close)


app = FastAPI(
    title="RA Triage Workbench",
    version="1.7.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def identity_ingress_diagnostics(request: Request, call_next):
    if settings.identity_diagnostics and request.url.path.startswith("/api/"):
        candidates = identity_header_candidates(request)
        client_host = request.client.host if request.client else "unknown"
        observation = (client_host, tuple(sorted(candidates.items())))
        if _identity_diagnostic_observations.add_if_new(observation):
            logger.warning(
                "SSO ingress diagnostic client=%s identity_candidates=%s",
                client_host,
                candidates,
            )
    return await call_next(request)


@app.middleware("http")
async def production_write_guard(request: Request, call_next):
    if (
        settings.deployment_mode == "production"
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
    ):
        if not has_same_origin_mutation_marker(request):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "写请求缺少同源校验标记，请刷新页面后重试。"
                },
            )
        identity = await asyncio.to_thread(request_identity, request, settings)
        role = (
            await asyncio.to_thread(database.access_role, identity.username)
            if identity.verified and identity.username
            else ""
        )
        if role not in {"writer", "admin"}:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "当前入口为只读预览；请通过获准的企业 SSO 域名访问。"
                },
            )
    return await call_next(request)


@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    if request.method == "POST" and request.url.path in {
        "/api/prediction-batches",
        "/api/import/autotriage",
    }:
        content_length = request.headers.get("content-length", "").strip()
        if not content_length:
            return JSONResponse(
                status_code=411,
                content={"detail": "JSON 请求必须提供 Content-Length。"},
            )
        try:
            request_bytes = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 非法。"},
            )
        if request_bytes < 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 非法。"},
            )
        if request_bytes > MAX_BATCH_JSON_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Batch / AutoTriage 请求不能超过 256 KiB。"},
            )
    if (
        request.method == "POST"
        and request.url.path.startswith("/api/cases/")
        and request.url.path.endswith("/annotations-with-attachments")
    ):
        if request.headers.get("x-ra-triage-request") != "review-v1":
            return JSONResponse(
                status_code=403,
                content={"detail": "缺少 Review 截图请求标记。"},
            )
        content_length = request.headers.get("content-length", "").strip()
        if not content_length:
            return JSONResponse(
                status_code=411,
                content={"detail": "Review 截图请求必须提供 Content-Length。"},
            )
        try:
            request_bytes = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 非法。"},
            )
        if request_bytes < 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 非法。"},
            )
        if request_bytes > MAX_REVIEW_MULTIPART_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "截图上传请求不能超过 26 MB。"},
            )
    return await call_next(request)


@app.middleware("http")
async def request_latency_observer(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started) * 1000
    response.headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
    response.headers["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
    if request.url.path.startswith("/api/") and duration_ms >= 500:
        logger.warning(
            "slow_request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response



app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

app.include_router(core.router)
app.include_router(cases.router)
app.include_router(reviews.router)
app.include_router(runs.router)
app.include_router(analysis.router)
app.include_router(imports.router)
app.include_router(batch.router)
app.include_router(inference.router)
