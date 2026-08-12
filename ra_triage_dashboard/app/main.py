from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from .auth import has_same_origin_mutation_marker, identity_header_candidates, request_identity
from .contracts import MAX_BATCH_JSON_REQUEST_BYTES, MAX_REVIEW_MULTIPART_REQUEST_BYTES
from .http_support import (
    bootstrap_baseline,
    bootstrap_model_result,
    sync_authoritative_gt,
    sync_trail_model_fields,
)
from .runtime import (
    EXAMPLE_CASES,
    _identity_diagnostic_observations,
    asset_index,
    batch_prediction_runner,
    database,
    settings,
)
from .routers import analysis, batch, cases, core, imports, inference, reviews, runs

logger = logging.getLogger("ra_triage_dashboard")


async def _trail_sync_startup() -> None:
    """Best-effort Trail model-field probe; never blocks process startup."""

    try:
        await asyncio.to_thread(
            sync_trail_model_fields,
            create_run=False,
            requested_by="system",
            identity_source="service_startup",
            identity_verified=False,
            trigger="startup",
        )
    except Exception:
        logger.exception("background Trail model-field sync failed")


def _gt_sync_needs_remote_refresh() -> bool:
    """Whether the periodic worker should hit Trail now.

    Hot paths (page open, status) must only read local DB / baseline xlsx.
    Remote Trail is optional freshness, not a gate for serving GT.
    """

    from .http_support import gt_sync_status

    status = gt_sync_status()
    if str(status.get("status") or "") != "ready":
        return True
    # Already fully applied locally; only re-check Trail on the long interval.
    # The loop already sleeps between runs, so a ready snapshot is left alone
    # for this tick when all baselines report ready with non-zero rows.
    baselines = status.get("baselines") or []
    if not baselines:
        return True
    for item in baselines:
        if str(item.get("status") or "") != "ready":
            return True
        if int(item.get("source_row_count") or 0) <= 0:
            return True
        if not str(item.get("last_applied_at") or "").strip():
            return True
    return False


async def _authoritative_gt_sync_loop() -> None:
    """Refresh Trail GT into local tables in the background only.

    Page-open GT labels are served from the database (baseline seed + last
    successful Trail snapshot). This worker may talk to Trail, but never
    blocks HTTP lifespan / first paint.
    """

    if settings.gt_sync_startup_delay_seconds:
        await asyncio.sleep(settings.gt_sync_startup_delay_seconds)
    while True:
        try:
            needs_remote = await asyncio.to_thread(_gt_sync_needs_remote_refresh)
        except Exception:
            logger.exception("failed to evaluate local GT freshness")
            needs_remote = True
        if needs_remote:
            sync_task = asyncio.create_task(
                asyncio.to_thread(
                    sync_authoritative_gt,
                    requested_by="system",
                    identity_source="service_periodic",
                    identity_verified=False,
                    trigger="periodic",
                )
            )
            try:
                await asyncio.shield(sync_task)
            except asyncio.CancelledError:
                # A worker thread cannot be cancelled safely. Wait for its current
                # transaction before lifespan closes the database pool.
                await sync_task
                raise
        else:
            logger.info(
                "skip periodic Trail GT refresh; local gt_sync_state is ready"
            )
        await asyncio.sleep(settings.gt_sync_interval_seconds)

@asynccontextmanager
async def lifespan(_: FastAPI):
    gt_sync_task: asyncio.Task[None] | None = None
    trail_sync_task: asyncio.Task[None] | None = None
    settings.ensure_directories()
    database.init()
    database.bootstrap_access_users(
        writers=settings.sso_write_users,
        administrators=settings.team_default_managers,
    )
    database.seed_examples(EXAMPLE_CASES)
    # Local-only seed from baseline workbooks / registry. No Trail I/O.
    bootstrap_baseline()
    asset_index.refresh(force=True)
    bootstrap_model_result()
    # Never await remote Trail during startup — it freezes first paint.
    if settings.trail_sync_on_start:
        trail_sync_task = asyncio.create_task(
            _trail_sync_startup(),
            name="trail-sync-startup",
        )
    if settings.gt_sync_enabled:
        gt_sync_task = asyncio.create_task(
            _authoritative_gt_sync_loop(),
            name="authoritative-gt-sync",
        )
    batch_prediction_runner.resume_queued_predictions()
    try:
        yield
    finally:
        for task in (gt_sync_task, trail_sync_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await asyncio.to_thread(batch_prediction_runner.shutdown)
        await asyncio.to_thread(database.close)


app = FastAPI(
    title="RA Triage Workbench",
    version="1.9.2",
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


@app.middleware("http")
async def strip_public_base_path(request: Request, call_next):
    """Accept both gateway-stripped and full public-prefix paths.

    Kylin publishes ``/manual/*`` and normally strips the prefix before
    forwarding to this process. Direct-IP browsers still request the public
    URLs emitted in JSON (``/manual/api/...``). Rewrite those onto the root
    routes so BEV thumbnails and assets do not 404 when the gateway is bypassed.
    """

    base = (settings.base_path or "").rstrip("/")
    if base:
        path = request.scope.get("path") or ""
        if path == base or path.startswith(f"{base}/"):
            rewritten = path[len(base) :] or "/"
            request.scope["path"] = rewritten
            raw = request.scope.get("raw_path")
            if isinstance(raw, (bytes, bytearray)):
                request.scope["raw_path"] = rewritten.encode("utf-8")
            # Keep path-based middleware checks (write-guard, size-guard) aligned.
            if hasattr(request, "_url"):
                request._url = None  # type: ignore[attr-defined]
    return await call_next(request)


class _CachedStaticFiles(StaticFiles):
    """Versioned static assets (``?v=manual-triage-N``) can be cached aggressively."""

    def file_response(
        self,
        full_path,  # type: ignore[no-untyped-def]
        stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(
            full_path, stat_result, scope, status_code=status_code
        )
        path = str(scope.get("path") or "")
        if path.endswith((".js", ".css", ".woff2", ".woff", ".png", ".svg")):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        return response


app.mount(
    "/static",
    _CachedStaticFiles(directory=settings.static_dir),
    name="static",
)

app.include_router(core.router)
app.include_router(cases.router)
app.include_router(reviews.router)
app.include_router(runs.router)
app.include_router(analysis.router)
app.include_router(imports.router)
app.include_router(batch.router)
app.include_router(inference.router)
