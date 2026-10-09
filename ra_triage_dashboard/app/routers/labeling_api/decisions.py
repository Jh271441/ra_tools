"""Labeling decisions HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from ...db import LabelAnnotationConflictError
from fastapi import Request
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
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    issue = await _require_active_labeling_issue(issue_id)
    try:
        body = await request.json()
    except (TypeError, ValueError) as exc:
        raise _detail(400, "Issue 标签裁决请求必须是 JSON 对象。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "Issue 标签裁决请求必须是 JSON 对象。")
    raw_previous = body.get("expected_previous_decision_id")
    try:
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "expected_previous_decision_id 不合法。") from exc
    try:
        result = await asyncio.to_thread(
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
        )
    except LabelAnnotationConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except PermissionError as exc:
        raise _detail(403, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
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
