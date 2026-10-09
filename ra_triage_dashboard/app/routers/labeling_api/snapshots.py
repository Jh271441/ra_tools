"""Labeling snapshots HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from fastapi import Request
from ...support.common import _as_text
from ...support.common import _detail
import asyncio
from ...runtime import database
from ...support.baselines import resolve_request_baseline_scopes
from .common import _active_labeling_scopes, _labeling_snapshot_actor, _require_labeling_admin, _snapshot_allow_partial

router = APIRouter()


@router.get("/api/labeling/gt-candidates")
async def get_gt_candidates(request: Request, baselines: str = "") -> dict[str, Any]:
    await _require_labeling_admin(request)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    items = await asyncio.to_thread(database.label_gt_candidates, scopes)
    return {
        "items": items,
        "ready_count": sum(item["status"] == "ready" for item in items),
        "conflict_count": sum(item["status"] != "ready" for item in items),
        "baseline_scopes": scopes,
    }

@router.get("/api/labeling/gt-snapshots")
async def list_gt_snapshots(request: Request, baselines: str = "") -> dict[str, Any]:
    """Return active immutable GT reference metadata only."""

    await _require_labeling_admin(request)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "items": await asyncio.to_thread(database.active_gt_snapshots, scopes),
        "baseline_scopes": scopes,
    }

@router.get("/api/labeling/gt-snapshots/{snapshot_id}")
async def get_gt_snapshot(
    snapshot_id: str,
    request: Request,
    items: bool = False,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    await _require_labeling_admin(request)
    snapshot = await asyncio.to_thread(
        database.get_gt_snapshot,
        snapshot_id,
        include_items=items,
        page=page,
        page_size=page_size,
    )
    if snapshot is None:
        raise _detail(404, "GT snapshot 不存在。")
    return {"snapshot": snapshot}

@router.post("/api/labeling/label-result-snapshots")
async def create_label_result_snapshot(request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_snapshot_actor, request
    )
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "Label snapshot 请求必须是 JSON 对象。")
    if not isinstance(body, dict) or not _as_text(body.get("workset_id")):
        raise _detail(400, "workset_id 必填。")
    allow_partial = _snapshot_allow_partial(body)
    requested_scopes = body.get("baseline_scopes")
    if requested_scopes is not None and not isinstance(requested_scopes, list):
        raise _detail(400, "baseline_scopes 必须是数组。")
    scopes = list(dict.fromkeys(
        _as_text(value) for value in (requested_scopes or []) if _as_text(value)
    ))
    if not scopes and _as_text(body.get("baseline_scope")):
        scopes = [_as_text(body.get("baseline_scope"))]
    try:
        snapshots = []
        for scope in scopes or [""]:
            snapshots.append(await asyncio.to_thread(
                database.create_label_result_snapshot,
                workset_id=_as_text(body.get("workset_id")),
                baseline_scope=scope,
                created_by=actor,
                created_by_source=actor_source,
                created_by_verified=actor_verified,
                allow_partial=allow_partial,
            ))
    except ValueError as exc:
        status = 409 if "requires all Workset members" in str(exc) else 400
        raise _detail(status, str(exc))
    return {
        "snapshot": snapshots[0] if len(snapshots) == 1 else None,
        "snapshots": snapshots,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.get("/api/labeling/label-result-snapshots/{snapshot_id}")
async def get_label_result_snapshot(
    snapshot_id: str,
    request: Request,
    items: bool = False,
    sources: bool = False,
    page: int = 1,
    page_size: int = 100,
    source_page: int = 1,
    source_page_size: int = 100,
) -> dict[str, Any]:
    await _require_labeling_admin(request)
    snapshot = await asyncio.to_thread(
        database.get_label_result_snapshot,
        snapshot_id,
        include_items=items,
        page=page,
        page_size=page_size,
        include_sources=sources,
        source_page=source_page,
        source_page_size=source_page_size,
    )
    if snapshot is None:
        raise _detail(404, "Label result snapshot 不存在。")
    return {"snapshot": snapshot}
