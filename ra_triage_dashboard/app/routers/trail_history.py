"""Local audit reads and explicit administrator-only inverse writes."""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Query

from ..auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ..db_parts.trail_history import encoded
from ..runtime import database, settings
from ..support.common import _detail
from ..trail_audit import audited_write, info_object, owned, restore_changes
from ..trail_sync import read_trail_model_fields
from ..trail_writer import write_trail_model_results
from .trail_update.commit import commit_guard
from .trail_update.preview import _capability_for_info_write, _preview_capability_cache

router = APIRouter()
_previews = {}
_TTL = 600
SOURCES = {"exclusion_summary", "exclusion_direct", "rollback", "legacy"}


async def _admin(request):
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源标记 / Same-origin marker required")
    identity = await asyncio.to_thread(request_identity, request, settings)
    role = await asyncio.to_thread(database.access_role, identity.username) if identity.verified else ""
    if role != "admin" or not identity_can_write(identity, settings):
        raise _detail(403, "仅已验证管理员可恢复 / Verified administrator required")
    if not settings.trail_attribute_write_enabled or not getattr(settings, "trail_rollback_enabled", False):
        raise _detail(409, "Trail 恢复开关未开启 / Trail restore is disabled")
    return identity


def _timestamp(value):
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except ValueError:
        raise _detail(422, "时间必须包含时区 / Timestamp must include timezone")


@router.get("/api/trail-history")
async def history(request: Request, issue_id: str = Query("", max_length=128),
                  actor: str = Query("", max_length=128), source: str = "", status: str = "",
                  since: str = "", until: str = "", page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100)):
    if source and source not in SOURCES or status and status not in {"pending", "succeeded", "partial", "unknown", "conflict"}:
        raise _detail(422, "未知筛选条件 / Unknown filter")
    result = await asyncio.to_thread(database.list_trail_operations,
        issue_id=issue_id.strip(), actor=actor.strip(), source=source, status=status,
        since=_timestamp(since), until=_timestamp(until), page=page, page_size=page_size)
    identity = await asyncio.to_thread(request_identity, request, settings)
    role = await asyncio.to_thread(database.access_role, identity.username) if identity.verified else ""
    result["can_restore"] = bool(role == "admin" and identity_can_write(identity, settings)
        and settings.trail_attribute_write_enabled and getattr(settings, "trail_rollback_enabled", False))
    result["coverage"] = {"connected": ["exclusion_summary", "exclusion_direct", "rollback"],
        "not_connected": ["daily_publication", "sampling", "rd_sync", "external_autotriage", "trail_native"],
        "historical_values_complete": False}
    return result


@router.get("/api/trail-history/{operation_id}")
async def detail(operation_id: str):
    operation = await asyncio.to_thread(database.trail_operation, operation_id)
    if operation is None:
        raise _detail(404, "更新记录不存在 / Update record not found")
    operation["restorable"] = operation["source"] != "legacy" and "succeeded" in operation["outcomes"].values()
    return operation


async def _snapshot(ids, field):
    result = await asyncio.to_thread(read_trail_model_fields, ra_root=settings.ra_auto_triage_root,
        issue_ids=ids, view_id=settings.trail_view_id, chunk_size=settings.trail_sync_chunk_size)
    if not result.complete or len(result.rows) != len(ids) or {r["issue_id"] for r in result.rows} != set(ids) or not _capability_for_info_write(result, field).get("ready"):
        raise _detail(409, "Trail 查询或权限不完整 / Incomplete Trail snapshot or capability")
    try:
        for row in result.rows:
            info_object(row.get(field))
    except ValueError:
        raise _detail(409, "Trail 数据异常 / Invalid Trail data")
    return result.rows


async def _body(request):
    try:
        body = await request.json()
    except Exception:
        raise _detail(400, "JSON 格式错误 / Invalid JSON")
    if not isinstance(body, dict):
        raise _detail(400, "请求必须为对象 / Object required")
    return body


@router.post("/api/trail-history/{operation_id}/verify")
async def verify(operation_id: str, request: Request):
    identity = await _admin(request)
    operation = await detail(operation_id)
    if operation["source"] == "legacy":
        raise _detail(409, "旧版历史没有完整快照 / Legacy snapshots are incomplete")
    field = settings.trail_attribute_info_field
    if any(item["field"] != field for item in operation["items"]):
        raise _detail(409, "目标字段配置已改变 / Target field configuration changed")
    async with commit_guard():
        rows = await _snapshot([i["issue_id"] for i in operation["items"]], field)
        current = {r["issue_id"]: r for r in rows}
        observed = {item["issue_id"]: "succeeded" if encoded(owned(current[item["issue_id"]].get(field))) == encoded(item["after"]) else "conflict" for item in operation["items"]}
        # A newer external change cannot erase an earlier verified successful write.
        outcomes = {issue: value for issue, value in observed.items() if operation["outcomes"].get(issue) != "succeeded"}
        if outcomes:
            await asyncio.to_thread(database.append_trail_event, operation_id,
                "succeeded" if all(v == "succeeded" for v in outcomes.values()) else "conflict", outcomes,
                actor=identity.username, actor_source=identity.source)
    return {**await detail(operation_id), "current_conflicts": [issue for issue, value in observed.items() if value == "conflict"], "observed_at": datetime.now(timezone.utc).isoformat()}


@router.post("/api/trail-history/{operation_id}/restore-preview")
async def restore_preview(operation_id: str, request: Request):
    identity = await _admin(request)
    body = await _body(request)
    reason = str(body.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        raise _detail(422, "请填写恢复原因（最多 1000 字） / Restore reason required (max 1,000 characters)")
    operation = await detail(operation_id)
    if not operation["restorable"]:
        raise _detail(409, "旧值或成功回执不完整，不能恢复 / Incomplete snapshots or success receipts; restore unavailable")
    selected = body.get("issue_ids", [item["issue_id"] for item in operation["items"]])
    if not isinstance(selected, list) or not selected or len(selected) > 200 or any(not isinstance(iid, str) for iid in selected) or len(set(selected)) != len(selected):
        raise _detail(422, "请选择有效 Issue / Select valid Issues")
    known = {item["issue_id"] for item in operation["items"]}
    if not set(selected).issubset(known) or any(operation["outcomes"].get(iid) != "succeeded" for iid in selected):
        raise _detail(409, "仅能恢复本次操作中已核验成功的 Issue / Only verified Issues from this operation may be restored")
    operation = {**operation, "items": [item for item in operation["items"] if item["issue_id"] in selected]}
    field = settings.trail_attribute_info_field
    if any(item["field"] != field for item in operation["items"]):
        raise _detail(409, "目标字段配置已改变 / Target field configuration changed")
    async with commit_guard():
        rows = await _snapshot([i["issue_id"] for i in operation["items"]], field)
        restore_id = "restore-" + uuid.uuid4().hex
        try:
            changes, conflicts = restore_changes(operation, rows, restore_id)
        except ValueError:
            raise _detail(409, "Trail 数据异常 / Invalid Trail data")
        now = time.time()
        for key in list(_previews):
            if _previews[key]["expires_at"] < now:
                del _previews[key]
        if len(_previews) >= 256:
            raise _detail(503, "预览繁忙，请稍后重试 / Preview busy; retry later")
        preview = {"operation_id": restore_id, "parent_id": operation_id, "actor": identity.username,
            "reason": reason, "expires_at": now + _TTL, "rows": rows, "changes": changes, "field": field}
        digest = hashlib.sha256(encoded({k:v for k,v in preview.items() if k != "rows"}).encode()).hexdigest()
        if not conflicts:
            _previews[digest] = preview
        return {"preview_id": digest if not conflicts else "", "expires_at": preview["expires_at"],
            "conflicts": conflicts, "ready": not conflicts, "items": [
                {"issue_id": c["issue_id"], "current": owned(next(r for r in rows if r["issue_id"] == c["issue_id"]).get(field)),
                 "restore": owned(c[field])} for c in changes]}


async def _exact_readback(changes, stats, *, result_field, info_field):
    # Read EVERY attempted Issue, including transport failures with an uncertain outcome.
    rows = await _snapshot([c["issue_id"] for c in changes], info_field)
    actual = {r["issue_id"]: r for r in rows}
    mismatched = [c["issue_id"] for c in changes if encoded(info_object(c[info_field])) != encoded(info_object(actual[c["issue_id"]].get(info_field)))]
    return {"complete": True, "ok": not mismatched, "missing_issue_ids": [],
        "mismatched_issue_ids": mismatched, "verified_count": len(changes)-len(mismatched)}


@router.post("/api/trail-history/{operation_id}/restore-commit")
async def restore_commit(operation_id: str, request: Request):
    identity = await _admin(request)
    body = await _body(request)
    if body.get("confirm") is not True:
        raise _detail(400, "需要明确确认 / Explicit confirmation required")
    async with commit_guard():
        preview = _previews.get(str(body.get("preview_id") or ""))
        if not preview or preview["expires_at"] < time.time() or preview["parent_id"] != operation_id:
            raise _detail(409, "预览已过期，请重新预览 / Preview expired; preview again")
        if preview["actor"] != identity.username:
            raise _detail(403, "预览属于其他操作人 / Preview belongs to another actor")
        if preview.get("result"):
            return deepcopy(preview["result"])
        field = preview["field"]
        if field != settings.trail_attribute_info_field:
            raise _detail(409, "目标字段配置已改变 / Target field configuration changed")
        rows = await _snapshot([c["issue_id"] for c in preview["changes"]], field)
        current = {r["issue_id"]: r for r in rows}
        before = {r["issue_id"]: r for r in preview["rows"]}
        pending, already = [], []
        for change in preview["changes"]:
            iid = change["issue_id"]
            value = encoded(info_object(current[iid].get(field)))
            if value == encoded(info_object(change[field])):
                already.append(iid)
            elif value == encoded(info_object(before[iid].get(field))):
                pending.append(change)
            else:
                raise _detail(409, "Trail 在预览后发生变化，未写入 / Trail changed since preview; nothing written")
        # Reconcile a previous interrupted attempt without resending successful items.
        existing = await asyncio.to_thread(database.trail_operation, preview["operation_id"])
        if already and not existing:
            raise _detail(409, "缺少恢复意图记录 / Missing restore intent")
        if already:
            await asyncio.to_thread(database.append_trail_event, preview["operation_id"],
                "succeeded" if not pending else "partial", {iid: "succeeded" for iid in already})
        if pending:
            _, readback = await audited_write(database=database, settings=settings, identity=identity,
                operation_id=preview["operation_id"], source="rollback", parent_id=operation_id,
                reason=preview["reason"], changes=pending, current_rows=preview["rows"],
                info_field=field, writer=write_trail_model_results, readback=_exact_readback)
        result = await detail(preview["operation_id"])
        response = {"ok": result["status"] == "succeeded", "operation_id": preview["operation_id"], "status": result["status"]}
        if response["ok"]:
            preview["result"] = response
        _preview_capability_cache.clear()
        return response
