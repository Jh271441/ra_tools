"""Read Trail, explicitly adopt its exclusion into a personal local vote."""
import asyncio
import secrets
import time

from fastapi import APIRouter, Request
from ...auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ...runtime import database, settings
from ...db import LabelAnnotationConflictError
from ...support.baselines import resolve_request_baseline_scopes
from ...support.common import _detail
from ...trail_exclusion_contracts import normalise_issue_ids, canonical_json
from ...trail_sync import read_trail_model_fields
from .selection import _body, _owned_fields
from .preview import _field_names
from .commit import commit_guard

router = APIRouter()
_previews = {}


@router.post("/api/trail-attribute-update/local-import-candidates")
async def local_import_candidates(request: Request):
    """Bounded read-only discovery across the selected datasets, 100 per request."""
    actor = await _actor(request)
    body = await _body(request)
    baselines = body.get("baselines", "")
    if not isinstance(baselines, str):
        raise _detail(422, "数据集格式错误 / Invalid datasets")
    after = body.get("after", "")
    if not isinstance(after, str) or (after and normalise_issue_ids([after]) != ([after], [])):
        raise _detail(422, "分页游标无效 / Invalid cursor")
    scopes = await asyncio.to_thread(resolve_request_baseline_scopes, baselines, request=request)
    page = await asyncio.to_thread(database.trail_local_import_members, scopes=scopes, after=after)
    # An absent local vote is a visible difference, never an inferred false vote.
    members = [row for row in page["items"] if row["local_excluded"] is not True]
    remote = await _remote([row["issue_id"] for row in members]) if members else {}
    items = []
    for row in members:
        source = remote[row["issue_id"]]
        if source.get("should_exclude") is not True:
            continue
        item = {**row, "remote_reason": source.get("should_exclude_comment") or "", "can_import": True}
        try:
            await asyncio.to_thread(database.preview_trail_local_import,
                issue_ids=[row["issue_id"]], actor=actor, scopes=scopes, remote=remote)
        except ValueError as exc:
            item.update(can_import=False, blocked_reason=str(exc))
        items.append(item)
    return {**page, "items": items, "direction": "trail_to_local", "read_only": True}


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
    _, field = _field_names()
    result = await asyncio.to_thread(read_trail_model_fields, ra_root=settings.ra_auto_triage_root,
        issue_ids=ids, view_id=settings.trail_view_id, chunk_size=settings.trail_sync_chunk_size)
    rows = {row.get("issue_id"): row for row in result.rows}
    if not result.complete or len(result.rows) != len(ids) or set(rows) != set(ids) or any(field not in row for row in result.rows):
        raise _detail(409, "Trail 查询不完整 / Incomplete Trail snapshot")
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
