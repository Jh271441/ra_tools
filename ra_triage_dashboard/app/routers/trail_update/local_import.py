"""Read Trail, explicitly adopt its exclusion into a personal local vote."""
import asyncio
import secrets
import time

from fastapi import APIRouter, Request
from ...auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ...runtime import database, settings
from ...db import LabelAnnotationConflictError
from ...support.baselines import resolve_request_baseline_scopes, restrict_version_issue_ids
from ...support.common import _detail
from ...trail_exclusion_contracts import normalise_issue_ids, canonical_json
from ...trail_sync import read_trail_model_fields
from ...trail_import_discovery import TrailImportDiscovery
from .selection import _body, _owned_fields
from .preview import _field_names
from .commit import commit_guard

router = APIRouter()
_previews = {}


@router.post("/api/trail-attribute-update/local-import-candidates")
async def local_import_candidates(request: Request):
    """Read saved observations; only first visit/explicit refresh starts a scan."""
    actor = await _actor(request)
    body = await _body(request)
    baselines = body.get("baselines", "")
    if not isinstance(baselines, str):
        raise _detail(422, "数据集格式错误 / Invalid datasets")
    refresh = body.get("refresh", False)
    if not isinstance(refresh, bool) or body.get("after", ""):
        raise _detail(422, "查询参数无效，请刷新页面 / Invalid scan options; reload the page")
    scopes = await asyncio.to_thread(resolve_request_baseline_scopes, baselines, request=request)
    members = await asyncio.to_thread(database.trail_local_import_inventory, scopes=scopes)
    selected = await asyncio.to_thread(restrict_version_issue_ids, baselines, request=request)
    if selected:
        members = [row for row in members if row["issue_id"] in set(selected)]
    cache = TrailImportDiscovery(settings.data_dir, [str(settings.ra_auto_triage_root),
        settings.trail_view_id, _field_names(), settings.database_url])
    try:
        saved = await asyncio.to_thread(cache.read_or_start, scopes=scopes, members=members,
                                        read_remote=_read_remote, refresh=refresh)
    except RuntimeError as exc:
        raise _detail(503, str(exc)) from exc
    items = await asyncio.to_thread(_discovery_items, saved, members, actor, scopes)
    snapshot = saved.get("snapshot") or {}
    return {"items": items, "direction": "trail_to_local", "read_only": True,
            "status": saved["status"], "error": saved.get("error", ""),
            "scanned": saved.get("scanned", 0), "total": saved.get("total", 0),
            "snapshot_available": bool(snapshot), "checked_at": snapshot.get("checked_at"),
            "snapshot_total": snapshot.get("total", 0),
            "membership_changed": cache.membership_changed(saved, members), "next_cursor": None}


def _discovery_items(saved, members, actor, scopes):
    """Shared remote facts never cache another actor's eligibility/local state."""
    current = {row["issue_id"]: row["baseline_scope"] for row in members}
    snapshot = saved.get("snapshot")
    observed = snapshot["items"] if snapshot else saved.get("partial", [])
    observed = [row for row in observed if current.get(row["issue_id"]) == row["baseline_scope"]]
    projections = database.project_issue_exclusions([row["issue_id"] for row in observed]) if observed else {}
    items = []
    for row in observed:
        local = projections.get(row["issue_id"])
        local_excluded = local["is_excluded"] if local else None
        if local_excluded is True:
            continue
        item = {"issue_id": row["issue_id"], "baseline_scope": row["baseline_scope"],
                "local_excluded": local_excluded,
                "remote_reason": row["remote"].get("should_exclude_comment") or "", "can_import": True}
        try:
            database.preview_trail_local_import(issue_ids=[row["issue_id"]], actor=actor,
                scopes=scopes, remote={row["issue_id"]: row["remote"]})
        except ValueError as exc:
            item.update(can_import=False, blocked_reason=str(exc))
        items.append(item)
    return items


async def _actor(request):
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源标记 / Same-origin marker required")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings) or not identity.verified:
        raise _detail(403, "需要已验证的写权限 / Verified write access required")
    if await asyncio.to_thread(database.access_role, identity.username) not in {"writer", "admin"}:
        raise _detail(403, "需要标注写权限 / Annotation write access required")
    return identity.username.lower()


async def _remote(ids):
    return await asyncio.to_thread(_read_remote, ids)


def _read_remote(ids):
    _, field = _field_names()
    result = read_trail_model_fields(ra_root=settings.ra_auto_triage_root,
        issue_ids=ids, view_id=settings.trail_view_id, chunk_size=settings.trail_sync_chunk_size)
    rows = {row.get("issue_id"): row for row in result.rows}
    if not result.complete or len(result.rows) != len(ids) or set(rows) != set(ids):
        raise _detail(409, "Trail 查询不完整 / Incomplete Trail snapshot")
    # Old Issues omit empty custom columns. Missing info is an unset marker,
    # not an incomplete Issue snapshot and never an explicit false/true vote.
    return {issue: _owned_fields(rows[issue], field) for issue in ids}


@router.post("/api/trail-attribute-update/local-import-preview")
async def local_import_preview(request: Request):
    actor = await _actor(request)
    body = await _body(request)
    ids, invalid = normalise_issue_ids(body.get("issue_ids", []))
    if invalid or not ids or len(ids) > 200:
        raise _detail(422, "请输入 1–200 个有效 Issue / Enter 1–200 valid Issues")
    baselines = body.get("baselines", "")
    if isinstance(baselines, list) and all(isinstance(value, str) for value in baselines):
        baselines = ",".join(baselines)
    if not isinstance(baselines, str):
        raise _detail(422, "数据集格式错误 / Invalid datasets")
    scopes = await asyncio.to_thread(resolve_request_baseline_scopes, baselines, request=request)
    selected = await asyncio.to_thread(restrict_version_issue_ids, baselines, request=request, issue_ids=ids)
    if set(selected) != set(ids):
        raise _detail(409, "Issue 超出所选数据集 / Issue outside selected dataset")
    remote = await _remote(ids)
    try:
        items = await asyncio.to_thread(database.preview_trail_local_import,
            issue_ids=ids, actor=actor, scopes=scopes, remote=remote)
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    now = time.time()
    for key in list(_previews):
        if _previews[key]["expires_at"] < now:
            del _previews[key]
    if len(_previews) >= 256:
        raise _detail(503, "预览繁忙，请稍后重试 / Preview busy; retry later")
    token = secrets.token_hex(32)
    _previews[token] = {"actor": actor, "ids": ids, "scopes": scopes, "items": items, "remote": remote, "expires_at": now + 600}
    return {"preview_id": token, "expires_at": now + 600, "items": items, "direction": "trail_to_local"}


@router.post("/api/trail-attribute-update/local-import-commit")
async def local_import_commit(request: Request):
    actor = await _actor(request)
    body = await _body(request)
    if body.get("confirm") is not True:
        raise _detail(400, "需要明确确认 / Explicit confirmation required")
    token = str(body.get("preview_id") or "")
    async with commit_guard():
        try:
            existing = await asyncio.to_thread(database.trail_local_import_result, token, actor)
            if existing:
                return existing
            receipt = _previews.get(token)
            if not receipt or receipt["expires_at"] < time.time():
                raise _detail(409, "预览已过期，请重新预览 / Preview expired; preview again")
            if receipt["actor"] != actor:
                raise _detail(403, "预览属于其他用户 / Preview belongs to another user")
            remote = await _remote(receipt["ids"])
            if canonical_json(remote) != canonical_json(receipt["remote"]):
                raise _detail(409, "Trail 已变化，请重新预览 / Trail changed; preview again")
            return await asyncio.to_thread(database.commit_trail_local_import,
                operation_id=token, actor=actor, scopes=receipt["scopes"], items=receipt["items"])
        except PermissionError as exc:
            raise _detail(403, str(exc)) from exc
        except (ValueError, LabelAnnotationConflictError) as exc:
            raise _detail(409, str(exc)) from exc
