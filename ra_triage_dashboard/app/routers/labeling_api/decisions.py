"""Labeling decisions HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any, Optional, List
from ...db import LabelAnnotationConflictError
from fastapi import Request, File, Form, UploadFile
import json
from ...support.attachments import _store_review_attachments
from ...support.common import _as_text
from ...support.common import _detail
import asyncio
from ...runtime import database
from .common import _labeling_actor, _labeling_payload, _public_label_case, _require_active_labeling_issue, _require_labeling_writer

router = APIRouter()


@router.get("/api/labeling/issues/{issue_id}/decisions")
async def list_issue_label_decisions(issue_id: str, request: Request) -> dict[str, Any]:
    await _require_labeling_writer(request)
    issue = await _require_active_labeling_issue(issue_id)
    items = await asyncio.to_thread(
        database.list_issue_label_decisions,
        baseline_scope=str(issue.get("baseline_scope") or ""),
        issue_id=issue_id,
    )
    return {"items": items, "count": len(items)}

@router.post("/api/labeling/issues/{issue_id}/decisions")
async def adjudicate_issue_label(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError) as exc:
        raise _detail(400, "裁决请求必须是 JSON 对象。 / Decision must be a JSON object.") from exc
    return await _save_issue_decision(issue_id, request, body)


@router.post("/api/labeling/issues/{issue_id}/decisions-with-attachments")
async def adjudicate_issue_with_attachments(
    issue_id: str, request: Request, payload: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
) -> dict[str, Any]:
    try:
        body = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise _detail(400, "裁决请求必须是 JSON 对象。 / Decision must be a JSON object.") from exc
    return await _save_issue_decision(issue_id, request, body, attachments or [])


async def _save_issue_decision(issue_id, request, body, uploads=()):
    actor, actor_source, actor_verified = await asyncio.to_thread(_labeling_actor, request)
    issue = await _require_active_labeling_issue(issue_id)
    if not isinstance(body, dict):
        raise _detail(400, "裁决请求必须是 JSON 对象。 / Decision must be a JSON object.")
    full = None
    if "full_result" in body:
        if body["full_result"] is not True or type(body.get("is_excluded")) is not bool:
            raise _detail(400, "请确认完整结果及是否排除。 / Confirm the complete result and exclusion.")
        normalized = _labeling_payload(body)
        full = {**normalized, "label_rationale": _as_text(body.get("label_rationale")),
                "adopted_revision_id": body.get("adopted_revision_id"),
                "retained_attachment_ids": body.get("retained_attachment_ids") or []}
        body = {**body, "expected_output": normalized["expected_output"]}
    if uploads and full is None:
        raise _detail(400, "截图需要完整裁决。 / Attachments require a full decision.")
    raw_previous = body.get("expected_previous_decision_id")
    try:
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "expected_previous_decision_id 不合法。") from exc
    records, paths = await _store_review_attachments(list(uploads)) if uploads else ([], [])
    async def commit():
        return await asyncio.to_thread(
            database.adjudicate_issue_label,
            baseline_scope=str(issue.get("baseline_scope") or ""),
            issue_id=issue_id,
            expected_output=_as_text(body.get("expected_output")),
            rationale=_as_text(body.get("rationale")),
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            expected_source_fingerprint=_as_text(
                body.get("expected_source_fingerprint")
            ),
            expected_previous_decision_id=expected_previous,
            full_result=full, attachments=records,
        )
    # Cancellation must not remove images while the database worker may commit.
    worker = asyncio.create_task(commit())
    try:
        result = await asyncio.shield(worker)
    except asyncio.CancelledError:
        def completed(task):
            if task.cancelled() or task.exception() is not None:
                for path in paths:
                    path.unlink(missing_ok=True)
        worker.add_done_callback(completed)
        raise
    except LabelAnnotationConflictError as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise _detail(409, str(exc)) from exc
    except PermissionError as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise _detail(403, str(exc)) from exc
    except ValueError as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise _detail(400, str(exc)) from exc
    except Exception:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return {
        **result,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.post("/api/labeling/label-cases/{label_case_id}/adjudications")
async def adjudicate_label_case(label_case_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "裁决请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "裁决请求必须是 JSON 对象。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    current_case = await asyncio.to_thread(database.get_label_case, label_case_id)
    if current_case is None:
        raise _detail(404, "标注 Case 不存在。")
    await _require_active_labeling_issue(current_case["issue_id"])
    payload = _labeling_payload(body)
    raw_sources = body.get("source_revision_ids") or []
    if not isinstance(raw_sources, list):
        raise _detail(400, "source_revision_ids 必须是数组。")
    try:
        source_ids = [int(value) for value in raw_sources]
        raw_previous = body.get("expected_previous_resolution_id")
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "裁决版本参数不合法。") from exc
    try:
        label_case = await asyncio.to_thread(
            database.adjudicate_label_case,
            label_case_id=label_case_id,
            source_revision_ids=source_ids,
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            expected_previous_resolution_id=expected_previous,
            adjudication_scope=_as_text(body.get("adjudication_scope") or "label"),
            confirm_full_label=body.get("confirm_full_label") is True,
            **payload,
        )
    except LabelAnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "label_case": _public_label_case(label_case),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
