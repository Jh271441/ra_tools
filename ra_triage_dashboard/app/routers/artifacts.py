"""Standalone read-only artifact pages, unified Artifact Hub portal, and CRUD APIs.

These routes are intentionally absent from the Manual Workbench navigation shell.
Static shell templates are rendered once at import time with the configured base
path so page navigation performs minimal I/O, while all dynamic store and
identity operations run off the event loop via ``asyncio.to_thread``.
"""
from __future__ import annotations

import asyncio
import html as html_escape
import json
import re
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..artifact_store import (
    DEFAULT_GROUP_LABELS,
    normalize_artifact_slug,
    render_artifact_frame_html,
)
from ..auth import request_identity
from ..contracts import (
    DEFAULT_ARTIFACT_PAGE_SIZE,
    MAX_ARTIFACT_PAGE_SIZE,
    MAX_ARTIFACT_REQUEST_BYTES,
)
from ..runtime import artifact_store, database, settings
from ..settings import DASHBOARD_RETURN_HOSTS
from ..support.common import _detail
from ..support.identity import _action_actor, _writer_identity
from ..web_paths import render_index_html

router = APIRouter()

_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,128}$")
_TITLE_PLACEHOLDER_RE = re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)

ARCHITECTURE_ORIGINAL_330_HTML = render_index_html(
    (
        settings.static_dir
        / "artifacts"
        / "architecture-original-330"
        / "index.html"
    ).read_text(encoding="utf-8"),
    settings.base_path,
)

ARTIFACT_PORTAL_HTML = render_index_html(
    (settings.static_dir / "artifacts" / "portal.html").read_text(encoding="utf-8"),
    settings.base_path,
)

ARTIFACT_VIEWER_HTML = render_index_html(
    (settings.static_dir / "artifacts" / "viewer.html").read_text(encoding="utf-8"),
    settings.base_path,
)


def _artifact_can_manage(request: Request) -> tuple[bool, str]:
    """Check whether caller can create/edit/archive/delete dynamic artifacts."""
    if settings.deployment_mode != "production":
        username, _, _ = _action_actor(request)
        return True, username or "local"
    identity = request_identity(request, settings)
    if not (identity.verified and identity.username):
        return False, ""
    role = database.access_role(identity.username)
    return role in {"writer", "admin"}, identity.username


def _artifact_require_writer(request: Request) -> str:
    """Enforce verified writer/admin in production; allow dev-mode mutations."""
    if settings.deployment_mode == "production":
        identity = _writer_identity(request)
        return identity.username
    username, _, _ = _action_actor(request)
    return username or "local"


def _frame_csp_header(request: Request) -> str:
    """Allow only trusted dashboard origins for local vendored Tailwind inside sandbox."""
    allowed_origins: list[str] = ["'self'"]
    for trusted_host in sorted(DASHBOARD_RETURN_HOSTS):
        allowed_origins.append(f"https://{trusted_host}")
    req_host = (request.headers.get("host") or "").strip()
    if req_host and _SAFE_HOST_RE.fullmatch(req_host):
        scheme = "https" if request.url.scheme == "https" else "http"
        origin = f"{scheme}://{req_host}"
        if origin not in allowed_origins:
            allowed_origins.append(origin)
        if scheme == "http" and f"https://{req_host}" not in allowed_origins:
            allowed_origins.append(f"https://{req_host}")
    origins_expr = " ".join(allowed_origins)
    return (
        f"default-src {origins_expr} data: blob:; "
        f"script-src {origins_expr} 'unsafe-inline' 'unsafe-eval'; "
        f"style-src {origins_expr} 'unsafe-inline'; "
        f"img-src {origins_expr} data: blob:; "
        f"font-src {origins_expr} data:; "
        "connect-src 'none'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self';"
    )


async def _read_bounded_json_body(request: Request, *, max_bytes: int) -> dict[str, Any]:
    content_length = (request.headers.get("content-length") or "").strip()
    if content_length:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise _detail(400, "Content-Length 非法。") from exc
        if declared < 0:
            raise _detail(400, "Content-Length 非法。")
        if declared > max_bytes:
            raise _detail(413, f"请求体不能超过 {max_bytes} 字节。")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise _detail(413, f"请求体不能超过 {max_bytes} 字节。")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise _detail(400, "请求体不能为空。")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _detail(400, "请求体必须是合法的 UTF-8 JSON。") from exc
    if not isinstance(payload, dict):
        raise _detail(400, "JSON 顶层必须是对象。")
    return payload


@router.get("/architecture-original-330", include_in_schema=False)
@router.get("/architecture-original-330/", include_in_schema=False)
async def architecture_original_330_page() -> HTMLResponse:
    return HTMLResponse(
        content=ARCHITECTURE_ORIGINAL_330_HTML,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/artifacts", include_in_schema=False)
@router.get("/artifacts/", include_in_schema=False)
async def artifacts_portal_page() -> HTMLResponse:
    return HTMLResponse(
        content=ARTIFACT_PORTAL_HTML,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/artifacts/{slug}", include_in_schema=False)
@router.get("/artifacts/{slug}/", include_in_schema=False)
async def artifact_viewer_page(slug: str, request: Request):
    try:
        normalized = normalize_artifact_slug(slug)
    except ValueError:
        return HTMLResponse(
            content=ARTIFACT_VIEWER_HTML,
            status_code=404,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    if normalized == "architecture-original-330":
        target = (
            "../../architecture-original-330"
            if request.url.path.endswith("/")
            else "../architecture-original-330"
        )
        return RedirectResponse(url=target, status_code=302)
    item = await asyncio.to_thread(artifact_store.get_artifact, normalized)
    if item is None:
        return HTMLResponse(
            content=ARTIFACT_VIEWER_HTML,
            status_code=404,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    safe_title = html_escape.escape(f"{item['title']} · RA Triage Artifacts")
    rendered = _TITLE_PLACEHOLDER_RE.sub(
        f"<title>{safe_title}</title>",
        ARTIFACT_VIEWER_HTML,
        count=1,
    )
    return HTMLResponse(
        content=rendered,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/artifacts/{slug}/frame", include_in_schema=False)
async def artifact_frame_page(
    slug: str,
    request: Request,
    theme: str = Query(default="dark"),
) -> HTMLResponse:
    found = await asyncio.to_thread(artifact_store.read_artifact_html, slug)
    if found is None:
        return HTMLResponse(
            content="<!DOCTYPE html><html><body style='font-family:system-ui;padding:24px;color:#94a3b8'>Artifact not found.</body></html>",
            status_code=404,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    _, raw_html = found
    rendered = render_artifact_frame_html(
        raw_html,
        base_path=None,
        initial_theme=theme,
    )
    return HTMLResponse(
        content=rendered,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Security-Policy": _frame_csp_header(request),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/artifacts")
async def list_artifacts_api(
    request: Request,
    q: str = Query(default="", max_length=160),
    group: str = Query(default="", max_length=64),
    status: str = Query(default="active", max_length=16),
    sort: str = Query(default="updated_desc", max_length=32),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(
        default=DEFAULT_ARTIFACT_PAGE_SIZE,
        ge=1,
        le=MAX_ARTIFACT_PAGE_SIZE,
    ),
) -> JSONResponse:
    def _load() -> dict[str, Any]:
        listing = artifact_store.list_artifacts(
            q=q,
            group=group,
            status=status,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        can_manage, actor = _artifact_can_manage(request)
        listing["can_manage"] = can_manage
        listing["actor"] = actor
        listing["preset_groups"] = [
            {"id": gid, "label": labels[0], "label_en": labels[1]}
            for gid, labels in DEFAULT_GROUP_LABELS.items()
        ]
        return listing

    payload = await asyncio.to_thread(_load)
    return JSONResponse(content=payload, headers={"Cache-Control": "no-store"})


@router.get("/api/artifacts/{slug}")
async def get_artifact_api(slug: str, request: Request) -> JSONResponse:
    def _load() -> dict[str, Any] | None:
        item = artifact_store.get_artifact(slug)
        if item is None:
            return None
        can_manage, actor = _artifact_can_manage(request)
        return {
            "item": item,
            "can_manage": can_manage,
            "actor": actor,
            "preset_groups": [
                {"id": gid, "label": labels[0], "label_en": labels[1]}
                for gid, labels in DEFAULT_GROUP_LABELS.items()
            ],
        }

    payload = await asyncio.to_thread(_load)
    if payload is None:
        raise _detail(404, "未找到对应的 Artifact。")
    return JSONResponse(content=payload, headers={"Cache-Control": "no-store"})


@router.post("/api/artifacts")
async def upsert_artifact_api(request: Request) -> JSONResponse:
    body = await _read_bounded_json_body(
        request,
        max_bytes=MAX_ARTIFACT_REQUEST_BYTES,
    )

    def _save() -> dict[str, Any]:
        actor = _artifact_require_writer(request)
        slug = body.get("slug") or body.get("filename") or ""
        html_content = body.get("html_content")
        if not isinstance(html_content, str):
            raise _detail(400, "缺少 html_content 字符串。")
        try:
            return artifact_store.upsert_artifact(
                slug=str(slug),
                html_content=html_content,
                title=body.get("title"),
                title_en=body.get("title_en"),
                summary=body.get("summary"),
                summary_en=body.get("summary_en"),
                group=body.get("group"),
                group_label=body.get("group_label"),
                group_label_en=body.get("group_label_en"),
                tags=body.get("tags"),
                conversation_id=body.get("conversation_id"),
                conversation_label=body.get("conversation_label"),
                source_filename=body.get("source_filename"),
                source_host=body.get("source_host") or "browser",
                source_path=body.get("source_path"),
                source_updated_at=body.get("source_updated_at"),
                pinned=body.get("pinned") if "pinned" in body else None,
                archived=body.get("archived") if "archived" in body else None,
                updated_by=actor,
                preserve_manual_edits=bool(body.get("preserve_manual_edits", False)),
            )
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc

    result = await asyncio.to_thread(_save)
    return JSONResponse(
        content=result,
        status_code=201 if result.get("created") else 200,
    )


@router.patch("/api/artifacts/{slug}")
async def update_artifact_api(slug: str, request: Request) -> JSONResponse:
    body = await _read_bounded_json_body(request, max_bytes=64 * 1024)

    def _update() -> dict[str, Any]:
        actor = _artifact_require_writer(request)
        try:
            updated = artifact_store.update_artifact_metadata(
                slug,
                patch=body,
                updated_by=actor,
            )
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc
        if updated is None:
            raise _detail(404, "未找到对应的 Artifact。")
        return {"item": updated}

    result = await asyncio.to_thread(_update)
    return JSONResponse(content=result)


@router.delete("/api/artifacts/{slug}")
async def delete_artifact_api(slug: str, request: Request) -> JSONResponse:
    def _delete() -> dict[str, Any]:
        _artifact_require_writer(request)
        try:
            existed = artifact_store.delete_artifact(slug)
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc
        if not existed:
            raise _detail(404, "未找到对应的 Artifact。")
        return {"deleted": True, "slug": slug}

    result = await asyncio.to_thread(_delete)
    return JSONResponse(content=result)
