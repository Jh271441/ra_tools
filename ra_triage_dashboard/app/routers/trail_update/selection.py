"""Explicit, expiring selected-diff previews. Never creates local annotations."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from ...auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ...runtime import database, settings
from ...support.common import _detail
from ...support.baselines import resolve_request_baseline_scopes
from ...trail_exclusion_contracts import canonical_json, normalise_issue_ids, normalise_trail_info_value, trail_update_details
from ...trail_sync import read_trail_model_fields
from ...trail_audit import audited_write, reconcile_existing
from ...trail_writer import attach_trail_operation_id, build_trail_changes, write_trail_model_results
from .commit import commit_guard, _readback_changes
from .preview import _build_preview, _field_names, _capability_for_info_write, _preview_capability_cache

router = APIRouter()
_SELECTION_TTL = 600
_selection_previews: dict[str, dict[str, Any]] = {}


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _owned_fields(row, info_field):
    raw = normalise_trail_info_value(row.get(info_field))
    info = {} if raw is None or raw == "" else raw
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            raise _detail(409, "Trail info 无法解析，请先核查 / Invalid Trail info; inspect before updating")
    if not isinstance(info, dict):
        raise _detail(409, "Trail info 格式异常 / Invalid Trail info format")
    namespace = info.get("ra_triage_dashboard", {})
    if not isinstance(namespace, dict):
        raise _detail(409, "Trail 排除数据格式异常 / Invalid Trail exclusion data")
    # Preserve missing vs null, exact bytes, types, and another writer's operation.
    return {key: namespace[key] for key in ("should_exclude", "should_exclude_comment", "operation_id") if key in namespace}


def _local_fingerprint(items):
    return _hash([{key: item.get(key) for key in (
        "issue_id", "comment", "reason_source", "case_label_source", "review", "target"
    )} for item in sorted(items, key=lambda item: item["issue_id"])])


async def _authorized(request):
    if not settings.trail_attribute_write_enabled or not getattr(settings, "trail_attribute_review_write_enabled", False):
        raise _detail(409, "汇总写入开关未开启 / Summary writes are disabled")
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源标记 / Same-origin marker required")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings):
        raise _detail(403, "需要已验证的 SSO 写入权限 / Verified SSO write access required")
    return identity


async def _body(request):
    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "JSON 格式错误 / Invalid JSON") from exc
    if not isinstance(body, dict):
        raise _detail(400, "请求必须为对象 / Object required")
    return body


async def _candidates(request, run_id, baselines, issue_ids, intent="reason_only"):
    if intent == "unexclude":
        scopes = await asyncio.to_thread(resolve_request_baseline_scopes, baselines, request=request)
        items = await asyncio.to_thread(database.trail_non_exclusion_candidates,
            issue_ids, baseline_scopes=scopes, model_run_id=run_id)
        if len(items) != len(issue_ids) or {item["issue_id"] for item in items} != set(issue_ids):
            raise _detail(409, "所选案例必须有当前有效且明确的不排除结论；未标注、待裁决或范围外案例不可提交 / Selected cases need a current explicit non-exclusion outcome; unannotated, unresolved or out-of-scope cases cannot be submitted")
        by_id = {item["issue_id"]: item for item in items}
        return [by_id[issue] for issue in issue_ids]
    preview = await _build_preview(request, selected_run_id=run_id, baselines=baselines,
                                   probe_trail=False, fresh_local=True)
    by_id = {item["issue_id"]: item for item in preview["items"]}
    if any(issue not in by_id or sum(item["issue_id"] == issue for item in preview["items"]) != 1 or by_id[issue].get("readonly") for issue in issue_ids):
        raise _detail(409, "所选案例已离开候选范围，请重新预览 / Selected cases changed; preview again")
    return [by_id[issue] for issue in issue_ids]


async def _snapshot(issue_ids):
    _, info_field = _field_names()
    result = await asyncio.to_thread(read_trail_model_fields,
        ra_root=settings.ra_auto_triage_root, issue_ids=issue_ids,
        view_id=settings.trail_view_id, chunk_size=settings.trail_sync_chunk_size)
    capability = _capability_for_info_write(result, info_field)
    rows = {row["issue_id"]: row for row in result.rows}
    if not capability.get("ready") or set(rows) != set(issue_ids) or len(result.rows) != len(issue_ids):
        raise _detail(409, "Trail 查询不完整，未提交 / Incomplete Trail snapshot; nothing submitted")
    return result, {issue: _owned_fields(rows[issue], info_field) for issue in issue_ids}


@router.post("/api/trail-attribute-update/selection-preview")
async def selection_preview(request: Request) -> dict[str, Any]:
    return await _selection_preview(request)


@router.post("/api/trail-attribute-update/non-exclusion-preview")
async def non_exclusion_preview(request: Request) -> dict[str, Any]:
    return await _selection_preview(request, required_intent="unexclude")


async def _selection_preview(request, required_intent=None):
    identity = await _authorized(request)
    body = await _body(request)
    ids, invalid = normalise_issue_ids(body.get("issue_ids", []))
    if invalid or not ids or len(ids) > 200:
        raise _detail(422, "请选择 1–200 个有效 Issue / Select 1–200 valid Issues")
    intent = body.get("intent", required_intent or "reason_only")
    if intent not in {"reason_only", "exclude", "unexclude"} or (required_intent and intent != required_intent):
        raise _detail(422, "未知更新类型 / Unknown update type")
    run_id = str(body.get("model_run_id") or "")
    baselines = body.get("baselines") or ""
    if isinstance(baselines, list):
        baselines = ",".join(str(item) for item in baselines)
    if not isinstance(baselines, str):
        raise _detail(422, "数据集格式错误 / Invalid datasets")
    items = await _candidates(request, run_id, baselines, ids, intent)
    result, before = await _snapshot(ids)
    _, info_field = _field_names()
    details = trail_update_details(result, ids, info_field=info_field,
                                   expected_comments={item["issue_id"]: item["comment"] for item in items})
    selected = []
    for item in items:
        issue = item["issue_id"]
        detail = details[issue]
        eligible = (detail["trail_should_exclude"] is True and detail["needs_reason_update"]) if intent == "reason_only" else detail["needs_exclusion_update"]
        if intent == "unexclude":
            marker = before[issue].get("should_exclude")
            eligible = marker is True or marker is None
            detail = {**detail, "state": "needs_non_exclusion" if eligible else "not_eligible",
                "local_should_exclude": False, "needs_exclusion_update": False,
                "needs_reason_update": False, "needs_non_exclusion_update": eligible,
                "comment_policy": "preserve_remote"}
        if not eligible:
            raise _detail(409, f"{issue}: 当前状态不支持所选操作，请重新预览 / State changed; preview again")
        patch = {"should_exclude_comment": detail["local_comment"]} if intent == "reason_only" else {
            "should_exclude": True, **({"should_exclude_comment": detail["local_comment"]} if detail["local_comment"] else {})}
        if intent == "unexclude":
            patch = {"should_exclude": False}
        selected.append({**{key:item.get(key) for key in ("issue_id", "comment", "reason_source", "case_label_source", "baseline_id")}, "trail_detail": detail, "trail_update_status": "pending",
                         "target": {"patch": {"ra_triage_dashboard": patch}},
                         "before": before[issue], "after": {**before[issue], **patch}})
    receipt = {"actor": identity.username, "intent": intent, "issue_ids": ids,
               "model_run_id": run_id, "baselines": baselines, "before": before,
               "local_fingerprint": _local_fingerprint(items), "items": selected,
               "expires_at": time.time() + _SELECTION_TTL}
    digest = _hash(receipt)
    now = time.time()
    for key in list(_selection_previews):
        if _selection_previews[key]["expires_at"] < now:
            del _selection_previews[key]
    if len(_selection_previews) >= 256:
        raise _detail(503, "预览繁忙，请稍后重试 / Preview busy; retry shortly")
    _selection_previews[digest] = receipt
    # Never send full remote info/model JSON to the browser.
    return {"mode": "selected_exclusions", "intent": intent, "items": selected,
            "count": len(ids), "pending_count": len(ids), "payload_sha256": digest,
            "selected_run": {"id": run_id},
            "write_mode": "info_only", "target_field": info_field,
            "write_ready": True, "write_status": "ready", "baselines": baselines.split(","),
            "expires_at": receipt["expires_at"]}


async def _audit(receipt, digest, identity, status, verified=(), failed=()):
    entries = [{"issue_id": item["issue_id"], "comment": item["comment"],
                "status": "synced" if item["issue_id"] in verified else "failed" if item["issue_id"] in failed else "pending",
                "detail": "Trail info-only; local annotations unchanged",
                "change": {"intent": receipt["intent"], "before": item["before"], "after": item["after"],
                           "reason_source": item.get("reason_source"), "label_revision_ids": item.get("case_label_source"),
                           "local_fingerprint": receipt["local_fingerprint"]}}
               for item in receipt["items"]]
    # Durable audit is required before the first external mutation.
    await asyncio.to_thread(database.upsert_trail_issue_exclusion_history,
        operation_id=digest, actor=identity.username, actor_source=identity.source,
        actor_verified=identity.verified, status=status, requested_count=len(entries),
        synced_count=len(verified), failed_count=len(failed), entries=entries,
        message="Trail selected update; local annotations unchanged")


@router.post("/api/trail-attribute-update/selection-commit")
async def selection_commit(request: Request) -> dict[str, Any]:
    return await _selection_commit(request)


@router.post("/api/trail-attribute-update/non-exclusion-commit")
async def non_exclusion_commit(request: Request) -> dict[str, Any]:
    return await _selection_commit(request, required_intent="unexclude")


async def _selection_commit(request, required_intent=None):
    identity = await _authorized(request)
    body = await _body(request)
    if body.get("confirm") is not True:
        raise _detail(400, "需要明确确认 / Explicit confirmation required")
    digest = str(body.get("payload_sha256") or "")
    async with commit_guard():
        receipt = _selection_previews.get(digest)
        if not receipt or receipt["expires_at"] < time.time():
            raise _detail(409, "请勾选案例并重新预览；预览已过期 / Select cases and preview again; preview expired")
        if receipt["actor"] != identity.username:
            raise _detail(403, "预览操作人与当前用户不同 / Preview belongs to another user")
        if required_intent and receipt["intent"] != required_intent:
            raise _detail(409, "预览类型不符，请重新预览不排除更新 / Preview intent mismatch; preview non-exclusion again")
        ids = receipt["issue_ids"]
        items = await _candidates(request, receipt["model_run_id"], receipt["baselines"], ids, receipt["intent"])
        if _local_fingerprint(items) != receipt["local_fingerprint"]:
            raise _detail(409, "本地理由版本已变化，请重新预览 / Local reason version changed; preview again")
        snapshot, current = await _snapshot(ids)
        pending, skipped = [], []
        for item in receipt["items"]:
            issue = item["issue_id"]
            desired = {**item["after"], "operation_id": digest}
            if canonical_json(current[issue]) == canonical_json(desired):
                skipped.append(issue)
            elif canonical_json(current[issue]) != canonical_json(receipt["before"][issue]):
                raise _detail(409, f"{issue}: Trail 内容已变化，请重新预览 / Trail changed; preview again")
            else:
                pending.append(item)
        if not pending and receipt.get("result", {}).get("ok"):
            return {**receipt["result"], "submitted_count": 0, "skipped_synced_issue_ids": ids}
        await _audit(receipt, digest, identity, "pending", skipped)
        _, info_field = _field_names()
        await reconcile_existing(database, digest, snapshot.rows, info_field)
        changes = attach_trail_operation_id(build_trail_changes(pending, current_rows=snapshot.rows,
            info_field=info_field, write_result_field=False), operation_id=digest, info_field=info_field)
        try:
            stats, readback = await audited_write(database=database, settings=settings,
                identity=identity, operation_id=digest, source="exclusion_summary",
                changes=changes, current_rows=snapshot.rows, info_field=info_field,
                writer=write_trail_model_results, readback=_readback_changes)
        except Exception:
            await _audit(receipt, digest, identity, "unknown", skipped)
            raise
        failed = set(stats.get("failed_issue_ids", [])) | set(readback.get("missing_issue_ids", [])) | set(readback.get("mismatched_issue_ids", []))
        if not readback.get("complete"):
            failed.update(item["issue_id"] for item in pending)
        verified = set(ids) - failed
        ok = not failed and bool(readback.get("ok")) and not stats.get("failed_count")
        await _audit(receipt, digest, identity, "synced" if ok else "partial", verified, failed)
        response = {"ok": ok, "mode": "selected_exclusions", "intent": receipt["intent"],
                    "payload_sha256": digest, "submitted_count": len(changes),
                    "skipped_synced_issue_ids": skipped, "stats": stats, "readback": readback,
                    "local_review": {"status": "not_required", "marked_count": 0},
                    "failed_issue_ids": sorted(failed)}
        receipt["result"] = deepcopy(response)
        _preview_capability_cache.clear()
        return response
