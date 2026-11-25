"""Pure ASGI middleware stack for base-path rewriting, timing, guards, and security headers."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import has_same_origin_mutation_marker, identity_header_candidates, request_identity
from .contracts import (
    MAX_BATCH_JSON_REQUEST_BYTES,
    MAX_DEFAULT_JSON_REQUEST_BYTES,
    MAX_REVIEW_MULTIPART_REQUEST_BYTES,
    MAX_UPLOAD_BYTES,
)
from .core.observability import metrics_registry

logger = logging.getLogger("ra_triage_dashboard")

_STRICT_BATCH_JSON_PATHS = frozenset(
    {
        "/api/prediction-batches",
        "/api/import/autotriage",
    }
)
_CASE_ATTACHMENT_SUFFIXES = (
    "/annotations-with-attachments",
    "/comments-with-attachments",
    "/discussion-with-attachments",
    "/combined-review-with-attachments",
    "/case-label-from-review-with-attachments",
)
_LARGE_UPLOAD_PATHS = frozenset(
    {
        "/api/import/issues",
        "/api/import/model-results",
        "/api/rd-results/te-excel-preview",
        "/api/version-datasets/ingest",
        "/api/trail-attribute-update/issue-import/json-preview",
        "/api/trail-attribute-update/issue-import/excel-preview",
    }
)
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH"})
_ALL_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _RequestBodyTooLargeError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _parse_content_length(headers: Headers) -> tuple[bool, int | None, JSONResponse | None]:
    raw = headers.get("content-length", "").strip()
    if not raw:
        return False, None, None
    try:
        size = int(raw)
    except ValueError:
        return True, None, JSONResponse(status_code=400, content={"detail": "Content-Length 非法。"})
    if size < 0:
        return True, None, JSONResponse(status_code=400, content={"detail": "Content-Length 非法。"})
    return True, size, None


def _is_marker_attachment_path(path: str) -> bool:
    return (
        path.startswith("/api/cases/") and path.endswith(_CASE_ATTACHMENT_SUFFIXES)
    ) or (
        path.startswith("/api/labeling/cases/") and path.endswith("/revisions-with-attachments")
    )


def _is_other_multipart_attachment_path(path: str) -> bool:
    return path.startswith("/api/labeling/") and path.endswith("-with-attachments")


def evaluate_request_size_guard(
    method: str,
    path: str,
    headers: Headers,
) -> tuple[JSONResponse | None, int | None, str]:
    """Validate declared Content-Length/markers and return any streaming byte cap.

    Returns ``(error_response, max_stream_bytes, overflow_detail)``.
    """
    if method == "POST" and path in _STRICT_BATCH_JSON_PATHS:
        present, size, err = _parse_content_length(headers)
        if err is not None:
            return err, None, ""
        if not present:
            return (
                JSONResponse(status_code=411, content={"detail": "JSON 请求必须提供 Content-Length。"}),
                None,
                "",
            )
        assert size is not None
        detail = "Batch / AutoTriage 请求不能超过 256 KiB。"
        if size > MAX_BATCH_JSON_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": detail}), None, ""
        return None, MAX_BATCH_JSON_REQUEST_BYTES, detail

    if method == "POST" and _is_marker_attachment_path(path):
        is_comment_upload = path.endswith(("/comments-with-attachments", "/discussion-with-attachments"))
        is_label_upload = path.endswith(
            (
                "/revisions-with-attachments",
                "/combined-review-with-attachments",
                "/case-label-from-review-with-attachments",
            )
        )
        required_marker = (
            "comment-v1"
            if is_comment_upload
            else "labeling-v1"
            if is_label_upload
            else "review-v1"
        )
        if headers.get("x-ra-triage-request") != required_marker:
            return (
                JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "缺少评论图片请求标记。"
                            if is_comment_upload
                            else "缺少标注图片请求标记。"
                            if is_label_upload
                            else "缺少 Review 截图请求标记。"
                        )
                    },
                ),
                None,
                "",
            )
        present, size, err = _parse_content_length(headers)
        if err is not None:
            return err, None, ""
        if not present:
            return (
                JSONResponse(status_code=411, content={"detail": "图片上传请求必须提供 Content-Length。"}),
                None,
                "",
            )
        assert size is not None
        detail = "截图上传请求不能超过 26 MB。"
        if size > MAX_REVIEW_MULTIPART_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": detail}), None, ""
        return None, MAX_REVIEW_MULTIPART_REQUEST_BYTES, detail

    if method not in _MUTATION_METHODS or not path.startswith("/api/"):
        return None, None, ""

    # Artifact endpoints keep their own bounded streaming reader untouched.
    if path == "/api/artifacts" or path.startswith("/api/artifacts/"):
        return None, None, ""

    if method == "POST" and _is_other_multipart_attachment_path(path):
        limit = MAX_REVIEW_MULTIPART_REQUEST_BYTES
        detail = "截图上传请求不能超过 26 MB。"
    elif method == "POST" and path in _LARGE_UPLOAD_PATHS:
        limit = MAX_UPLOAD_BYTES
        detail = "导入文件请求不能超过 64 MB。"
    else:
        limit = MAX_DEFAULT_JSON_REQUEST_BYTES
        detail = "API 写请求体不能超过 2 MB。"

    present, size, err = _parse_content_length(headers)
    if err is not None:
        return err, None, ""
    if present and size is not None and size > limit:
        return JSONResponse(status_code=413, content={"detail": detail}), None, ""
    return None, limit, detail


class BasePathTimingAndSecurityMiddleware:
    """Pure ASGI outermost middleware: base_path rewrite, timing, slow-log, security headers."""

    def __init__(self, app: ASGIApp, *, settings: Any = None, get_settings: Any = None) -> None:
        self.app = app
        self._get_settings = get_settings or (lambda: settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        current_settings = self._get_settings()
        base = (current_settings.base_path or "").rstrip("/")
        if base:
            path = scope.get("path") or ""
            if path == base or path.startswith(f"{base}/"):
                rewritten = path[len(base) :] or "/"
                scope["path"] = rewritten
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)):
                    scope["raw_path"] = rewritten.encode("utf-8")

        path = scope.get("path") or ""
        method = scope.get("method") or ""
        is_artifact_path = (
            path == "/artifacts"
            or path.startswith("/artifacts/")
            or path == "/architecture-original-330"
            or path.startswith("/architecture-original-330/")
        )
        started = time.monotonic()
        status_code = 500
        req_headers = Headers(scope=scope)
        request_id = (req_headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:16]

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                duration_ms = (time.monotonic() - started) * 1000
                headers = MutableHeaders(raw=message["headers"])
                headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
                headers["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
                headers["X-Request-Id"] = request_id
                if not is_artifact_path:
                    if "x-content-type-options" not in headers:
                        headers["X-Content-Type-Options"] = "nosniff"
                    if "referrer-policy" not in headers:
                        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                    if "x-frame-options" not in headers:
                        headers["X-Frame-Options"] = "SAMEORIGIN"
                metrics_registry.record_http_request(
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    request_id=request_id,
                )
                if path.startswith("/api/") and duration_ms >= 500:
                    logger.warning(
                        "slow_request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                        request_id,
                        method,
                        path,
                        status_code,
                        duration_ms,
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestSizeGuardMiddleware:
    """Pure ASGI streaming body size and upload marker guard."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method") or ""
        path = scope.get("path") or ""
        headers = Headers(scope=scope)
        error_response, max_bytes, overflow_detail = evaluate_request_size_guard(
            method, path, headers
        )
        if error_response is not None:
            await error_response(scope, receive, send)
            return
        if max_bytes is None:
            await self.app(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"") or b""
                received_bytes += len(chunk)
                if received_bytes > max_bytes:
                    raise _RequestBodyTooLargeError(overflow_detail)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _RequestBodyTooLargeError as exc:
            if not response_started:
                response = JSONResponse(status_code=413, content={"detail": exc.detail})
                await response(scope, receive, send)
            else:
                raise


class ProductionWriteGuardMiddleware:
    """Pure ASGI production mutation guard with per-request verified identity caching."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Any = None,
        database: Any = None,
        get_settings: Any = None,
        get_database: Any = None,
    ) -> None:
        self.app = app
        self._get_settings = get_settings or (lambda: settings)
        self._get_database = get_database or (lambda: database)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        current_settings = self._get_settings()
        current_database = self._get_database()
        if (
            current_settings.deployment_mode == "production"
            and (scope.get("method") or "") in _ALL_WRITE_METHODS
            and (scope.get("path") or "").startswith("/api/")
        ):
            request = Request(scope, receive)
            if not has_same_origin_mutation_marker(request):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "写请求缺少同源校验标记，请刷新页面后重试。"},
                )
                await response(scope, receive, send)
                return
            identity = await asyncio.to_thread(request_identity, request, current_settings)
            role = (
                await asyncio.to_thread(current_database.access_role, identity.username)
                if identity.verified and identity.username
                else ""
            )
            if role not in {"writer", "admin"}:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "当前入口为只读预览；请通过获准的企业 SSO 域名访问。"},
                )
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})["_verified_auth"] = (
                id(current_settings),
                id(current_database),
                identity,
                role,
            )

        await self.app(scope, receive, send)


class IdentityDiagnosticsMiddleware:
    """Pure ASGI opt-in SSO header diagnostics; zero overhead when disabled."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Any = None,
        observations: Any = None,
        get_settings: Any = None,
        get_observations: Any = None,
    ) -> None:
        self.app = app
        self._get_settings = get_settings or (lambda: settings)
        self._get_observations = get_observations or (lambda: observations)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        current_settings = self._get_settings()
        if (
            scope["type"] == "http"
            and current_settings.identity_diagnostics
            and (scope.get("path") or "").startswith("/api/")
        ):
            request = Request(scope, receive)
            candidates = identity_header_candidates(request)
            client_host = request.client.host if request.client else "unknown"
            observation = (client_host, tuple(sorted(candidates.items())))
            if self._get_observations().add_if_new(observation):
                logger.warning(
                    "SSO ingress diagnostic client=%s identity_candidates=%s",
                    client_host,
                    candidates,
                )
        await self.app(scope, receive, send)
