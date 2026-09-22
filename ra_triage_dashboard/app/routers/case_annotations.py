from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from ..auth import request_identity
from ..db import AnnotationConflictError, LabelAnnotationConflictError
from ..runtime import database, logger, review_notification_dispatcher, settings
from ..support.annotations import _create_annotation_record, _create_model_review_record
from ..support.attachments import (
    _public_review_attachment,
    _store_review_attachments,
)
from ..support.common import _as_text, _detail
from ..support.catalogs import _normalise_missing_evidence, _normalise_review_tags, _review_tag_catalog
from ..support.identity import _action_actor
from ..review_workflow import resolve_expected_output

router = APIRouter()


def _optional_int(value: Any, field: str) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _detail(400, f"{field} 不合法。") from exc


@router.get("/api/cases/{issue_id}/combined-review-context")
async def combined_review_context(
    issue_id: str, request: Request, campaign_id: str = "", model_run_id: str = ""
) -> dict[str, Any]:
    identity = await asyncio.to_thread(request_identity, request, settings)
    role = await asyncio.to_thread(database.access_role, identity.username) if identity.verified else ""
    if not identity.verified or role != "admin":
        raise _detail(403, "联合复核需要模型复核与 Case 标注双重写权限。")
    try:
        context = await asyncio.to_thread(
            database.combined_review_context,
            issue_id=issue_id,
            campaign_id=_as_text(campaign_id),
            reviewer=identity.username,
            model_run_id=_as_text(model_run_id),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if not context.get("assigned"):
        raise _detail(403, "当前账号不在联合复核任务中。")
    return {"context": context}


@router.post("/api/cases/{issue_id}/combined-review")
async def submit_combined_review(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "联合复核请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "联合复核请求必须是 JSON 对象。")
    actor, source, verified = await asyncio.to_thread(
        _action_actor, request, body.get("author")
    )
    role = await asyncio.to_thread(database.access_role, actor) if verified else ""
    if role != "admin":
        raise _detail(403, "联合复核需要模型复核与 Case 标注双重写权限。")
    tags = body.get("tags") or []
    evidence = body.get("missing_evidence") or []
    if not isinstance(tags, list) or not isinstance(evidence, list):
        raise _detail(400, "tags 和 missing_evidence 必须是数组。")
    tags = _normalise_review_tags(tags)
    evidence = _normalise_missing_evidence(evidence)
    try:
        tag_catalog = await asyncio.to_thread(_review_tag_catalog)
        output = resolve_expected_output(body.get("expected_output"), tags, tag_catalog)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    key = _as_text(request.headers.get("idempotency-key") or body.get("idempotency_key"))
    try:
        result = await asyncio.to_thread(
            database.submit_combined_review,
            issue_id=issue_id,
            campaign_id=_as_text(body.get("campaign_id")),
            model_run_id=_as_text(body.get("model_run_id")),
            reviewer=actor,
            reviewer_source=source,
            reviewer_verified=verified,
            model_review_status=_as_text(body.get("model_review_status") or "pending"),
            reason=_as_text(body.get("reason") or body.get("note")),
            missing_evidence=evidence,
            expected_output=output,
            tags=tags,
            rationale=_as_text(body.get("rationale")),
            expected_model_review_storage_id=_optional_int(body.get("expected_model_review_storage_id"), "expected_model_review_storage_id"),
            expected_case_revision_id=_optional_int(body.get("expected_case_revision_id"), "expected_case_revision_id"),
            expected_label_state_fingerprint=_as_text(body.get("expected_label_state_fingerprint")),
            idempotency_key=key,
        )
    except (AnnotationConflictError, LabelAnnotationConflictError) as exc:
        raise _detail(409, str(exc)) from exc
    except PermissionError as exc:
        raise _detail(403, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {"combined_review": result, "change_revision": await asyncio.to_thread(database.change_revision)}


@router.post("/api/cases/{issue_id}/case-label-from-review")
async def submit_case_label_from_review(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "Case 标注请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "Case 标注请求必须是 JSON 对象。")
    actor, source, verified = await asyncio.to_thread(
        _action_actor, request, body.get("author")
    )
    role = await asyncio.to_thread(database.access_role, actor) if verified else ""
    if role != "admin":
        raise _detail(403, "Review 页内 Case 标注需要管理员权限。")
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        raise _detail(400, "tags 必须是数组。")
    tags = _normalise_review_tags(tags)
    try:
        tag_catalog = await asyncio.to_thread(_review_tag_catalog)
        output = resolve_expected_output(body.get("expected_output"), tags, tag_catalog)
        result = await asyncio.to_thread(
            database.submit_review_case_label,
            issue_id=issue_id,
            reviewer=actor,
            reviewer_source=source,
            reviewer_verified=verified,
            expected_output=output,
            tags=tags,
            rationale=_as_text(body.get("rationale")),
            expected_case_revision_id=_optional_int(body.get("expected_case_revision_id"), "expected_case_revision_id"),
            expected_label_state_fingerprint=_as_text(body.get("expected_label_state_fingerprint")),
        )
    except LabelAnnotationConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except PermissionError as exc:
        raise _detail(403, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {"case_label": result, "change_revision": await asyncio.to_thread(database.change_revision)}


async def _require_unmigrated_issue(
    issue_id: str, database: Any, *, model_run_id: str = ""
) -> dict[str, Any]:
    """Keep legacy no-Run operations off activated Case-label scopes."""

    issue = await asyncio.to_thread(database.get_issue, issue_id)
    if issue is None:
        raise _detail(404, "Issue 不存在。")
    active = await asyncio.to_thread(database.active_labeling_scopes)
    if (
        str(issue.get("baseline_scope") or "") in active
        and not str(model_run_id or "").strip()
    ):
        raise _detail(
            409,
            "该数据集已启用 Case 标注：无 Run 的标签/GT 写入请到 Case 标注工作台；"
            "带 Model Run 的判错复核可继续在 Review 保存。",
        )
    return issue


@router.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    model_run_id = _as_text(body.get("model_run_id")).strip()
    await _require_unmigrated_issue(issue_id, database, model_run_id=model_run_id)
    if not model_run_id:
        raise _detail(
            400,
            "新建模型复核必须先选择 Model Run；共享标签和 GT 请到 Case 标注工作台修改。",
        )
    annotation = await asyncio.to_thread(
        _create_model_review_record,
        issue_id=issue_id,
        request=request,
        body=body,
    )
    if annotation.get("notification", {}).get("status") == "queued":
        review_notification_dispatcher.wake()
    return {
        "annotation": annotation,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.post("/api/cases/{issue_id}/annotations-with-attachments")
async def create_annotation_with_attachments(
    issue_id: str,
    request: Request,
    payload: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
) -> dict[str, Any]:
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _detail(400, "payload 必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "payload 必须是 JSON 对象。")
    model_run_id = _as_text(body.get("model_run_id")).strip()
    await _require_unmigrated_issue(issue_id, database, model_run_id=model_run_id)
    if not model_run_id:
        raise _detail(
            400,
            "新建模型复核必须先选择 Model Run；共享标签和 GT 请到 Case 标注工作台修改。",
        )
    records, paths = await _store_review_attachments(attachments or [])
    try:
        await _require_unmigrated_issue(issue_id, database, model_run_id=model_run_id)
        annotation = await asyncio.to_thread(
            _create_model_review_record,
            issue_id=issue_id,
            request=request,
            body=body,
            attachments=records,
        )
    except Exception:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    annotation["attachments"] = [
        _public_review_attachment(attachment)
        for attachment in annotation.get("attachments", [])
    ]
    if annotation.get("notification", {}).get("status") == "queued":
        review_notification_dispatcher.wake()
    return {
        "annotation": annotation,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.get("/api/cases/{issue_id}/model-reviews")
async def list_model_reviews(issue_id: str, model_run_id: str = "") -> dict[str, Any]:
    if await asyncio.to_thread(database.get_issue, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    items = await asyncio.to_thread(
        database.model_review_revisions,
        issue_id=issue_id,
        model_run_id=_as_text(model_run_id),
    )
    return {"items": items, "count": len(items)}


@router.delete("/api/cases/{issue_id}/annotations/{annotation_id}")
async def delete_annotation(
    issue_id: str, annotation_id: int, request: Request
) -> dict[str, Any]:
    if annotation_id <= 0:
        raise _detail(400, "Review 版本 ID 不合法。")
    await _require_unmigrated_issue(issue_id, database)
    case = await asyncio.to_thread(database.get_case, issue_id)
    target = next(
        (
            item for item in (case or {}).get("annotations", [])
            if int(item.get("id") or 0) == annotation_id
        ),
        None,
    )
    if target and target.get("review_domain") == "model_review":
        raise _detail(409, "模型复核版本为追加式审计记录，不能通过旧 Review 删除接口移除。")
    if target and target.get("legacy_read_only"):
        raise _detail(409, "该版本属于历史 Review 证据，只读保留；请在 canonical Label/Model Review 域更正。")
    if target:
        scope = str((case or {}).get("baseline_scope") or "")
        policy = await asyncio.to_thread(database.legacy_policy_for_scopes, [scope])
        if policy.get(scope) == "canonical":
            raise _detail(409, "canonical scope 的历史 Review 只读，不能通过旧接口删除。")
    if target and target.get("work_split_id"):
        identity = await asyncio.to_thread(request_identity, request, settings)
        role = (
            await asyncio.to_thread(database.access_role, identity.username)
            if identity.verified and identity.username
            else ""
        )
        if role != "admin" and (
            not identity.verified
            or identity.username.lower() != str(target.get("author") or "").lower()
        ):
            raise _detail(403, "只能删除自己的盲标 Review 版本。")
    try:
        deleted = await asyncio.to_thread(
            database.delete_annotation,
            issue_id=issue_id,
            annotation_id=annotation_id,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    if deleted is None:
        raise _detail(404, "Review 版本不存在或已被删除。")
    attachment_root = settings.review_attachments_dir.resolve()
    for attachment in deleted.get("attachments", []):
        path = (attachment_root / str(attachment.get("stored_name") or "")).resolve()
        if attachment_root not in path.parents:
            logger.warning(
                "Skipped unsafe deleted review attachment path annotation_id=%s",
                annotation_id,
            )
            continue
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            logger.exception(
                "Failed to remove deleted review attachment annotation_id=%s attachment_id=%s",
                annotation_id,
                attachment.get("id"),
            )
    deleted["attachments"] = [
        _public_review_attachment(attachment)
        for attachment in deleted.get("attachments", [])
    ]
    return {
        "deleted": deleted,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
