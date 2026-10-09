"""Labeling queries HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from ...db import LABELS
from fastapi import Request
from ...support.common import _as_text
from ...support.common import _detail
from ...support.catalogs import _parse_issue_id_filter
from ...runtime import _public_path
from ...support.external_links import _voyager_issue_url
import asyncio
from ...runtime import database
from ...case_media import empty_case_media
from ...support.baselines import resolve_request_baseline_scopes
from .common import _active_labeling_scopes, _labeling_filter_values, _public_label_case, _require_active_labeling_issue, _require_labeling_writer
from .comments import _public_label_comment

router = APIRouter()


@router.get("/api/labeling/cases")
async def list_labeling_cases(
    request: Request,
    baselines: str = "",
    task_id: str = "",
    q: str = "",
    issue_ids: str = "",
    status: str = "all",
    author: str = "",
    assignee: str = "",
    exclusion: str = "all",
    label: str = "",
    gt: str = "",
    comment_state: str = "all",
    cluster: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    await _require_labeling_writer(request)
    normalized_status = _labeling_filter_values(
        status,
        allowed={"pending", "resolved", "conflict"},
        error="标注状态不合法。",
        lower=True,
    )
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    normalized_task_id = _as_text(task_id)
    if normalized_task_id:
        tasks = (
            await asyncio.to_thread(database.list_labeling_tasks, scopes)
            if scopes else []
        )
        if not any(task["id"] == normalized_task_id for task in tasks):
            raise _detail(404, "标注任务不在当前已激活的数据集中。")
    normalized_author = _labeling_filter_values(author, lower=True)
    normalized_assignee = _labeling_filter_values(assignee, lower=True)
    normalized_exclusion = _labeling_filter_values(
        exclusion,
        allowed={"excluded", "active"},
        error="排除筛选不合法。",
        lower=True,
    )
    normalized_label = _labeling_filter_values(
        label, allowed=set(LABELS), error="标注结果类别不合法。"
    )
    normalized_gt = _labeling_filter_values(
        gt, allowed=set(LABELS), error="GT 类别不合法。"
    )
    normalized_comment_state = _labeling_filter_values(
        comment_state,
        allowed={"with", "without"},
        error="讨论筛选不合法。",
        lower=True,
    )
    normalized_issue_ids = _parse_issue_id_filter(issue_ids)
    if _as_text(issue_ids).strip() and not normalized_issue_ids:
        raise _detail(400, "issue_ids 未包含有效的 Issue ID。")
    normalized_cluster = _as_text(cluster)
    try:
        result = await asyncio.to_thread(
            database.list_labeling_cases,
            baseline_scopes=scopes,
            task_id=normalized_task_id,
            search=_as_text(q),
            issue_ids=normalized_issue_ids,
            status=normalized_status,
            author=normalized_author,
            assignee=normalized_assignee,
            exclusion=normalized_exclusion,
            expected_output=normalized_label,
            gt_label=normalized_gt,
            comment_state=normalized_comment_state,
            cluster=normalized_cluster,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    for item in result["items"]:
        item["thumbnail_url"] = _public_path(
            f"/api/case-thumbnails/{item['issue_id']}"
        )
        item["voyager_issue_url"] = _voyager_issue_url(item["issue_id"])
    result["filters"] = {
        "baseline_scopes": scopes,
        "task_id": _as_text(task_id),
        "q": _as_text(q),
        "issue_ids": normalized_issue_ids,
        "status": normalized_status,
        "author": normalized_author,
        "assignee": normalized_assignee,
        "exclusion": normalized_exclusion,
        "label": normalized_label,
        "gt": normalized_gt,
        "comment_state": normalized_comment_state,
        "cluster": normalized_cluster,
    }
    return result

@router.get("/api/labeling/summary")
async def labeling_summary(
    request: Request,
    baselines: str = "",
    task_id: str = "",
    q: str = "",
    issue_ids: str = "",
    status: str = "all",
    author: str = "",
    assignee: str = "",
    exclusion: str = "all",
    label: str = "",
    gt: str = "",
    comment_state: str = "all",
    cluster: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from ...labeling_summary import summarize_labeling_cases
    await _require_labeling_writer(request)
    scopes = await _active_labeling_scopes(resolve_request_baseline_scopes(baselines, request=request))
    normalized_issue_ids = _parse_issue_id_filter(issue_ids)
    if _as_text(issue_ids).strip() and not normalized_issue_ids:
        raise _detail(400, "issue_ids 未包含有效的 Issue ID。")
    normalized_status = _labeling_filter_values(
        status,
        allowed={"pending", "resolved", "conflict"},
        error="标注状态不合法。",
        lower=True,
    )
    normalized_exclusion = _labeling_filter_values(
        exclusion,
        allowed={"excluded", "active"},
        error="排除筛选不合法。",
        lower=True,
    )
    normalized_label = _labeling_filter_values(
        label, allowed=set(LABELS), error="标注结果类别不合法。"
    )
    normalized_gt = _labeling_filter_values(
        gt, allowed=set(LABELS), error="GT 类别不合法。"
    )
    normalized_comment_state = _labeling_filter_values(
        comment_state,
        allowed={"with", "without"},
        error="讨论筛选不合法。",
        lower=True,
    )
    try:
        normalized_task = _as_text(task_id)
        items, _ = await asyncio.to_thread(
            database._project_labeling_cases,
            baseline_scopes=scopes,
            task_id=normalized_task,
            search=_as_text(q),
            issue_ids=normalized_issue_ids,
            status=normalized_status,
            author=_labeling_filter_values(author, lower=True),
            assignee=_labeling_filter_values(assignee, lower=True),
            exclusion=normalized_exclusion,
            expected_output=normalized_label,
            gt_label=normalized_gt,
            comment_state=normalized_comment_state,
            cluster=_as_text(cluster),
        )
        result, labelers, assignees = await asyncio.gather(
            asyncio.to_thread(
                summarize_labeling_cases,
                items,
                page=page,
                page_size=page_size,
            ),
            asyncio.to_thread(database.labeling_labelers, scopes, normalized_task),
            asyncio.to_thread(database.labeling_assignees, scopes, normalized_task),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {
        **result,
        "baseline_scopes": scopes,
        "task_id": normalized_task,
        "labelers": labelers,
        "assignees": assignees,
    }

@router.get("/api/labeling/clusters")
async def list_labeling_clusters(
    request: Request,
    baselines: str = "",
    task_id: str = "",
    q: str = "",
    issue_ids: str = "",
    status: str = "all",
    author: str = "",
    assignee: str = "",
    exclusion: str = "all",
    label: str = "",
    gt: str = "",
    comment_state: str = "all",
) -> dict[str, Any]:
    await _require_labeling_writer(request)
    normalized_status = _labeling_filter_values(
        status,
        allowed={"pending", "resolved", "conflict"},
        error="标注状态不合法。",
        lower=True,
    )
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    normalized_exclusion = _labeling_filter_values(
        exclusion,
        allowed={"excluded", "active"},
        error="排除筛选不合法。",
        lower=True,
    )
    normalized_label = _labeling_filter_values(
        label, allowed=set(LABELS), error="标注结果类别不合法。"
    )
    normalized_gt = _labeling_filter_values(
        gt, allowed=set(LABELS), error="GT 类别不合法。"
    )
    normalized_comment_state = _labeling_filter_values(
        comment_state,
        allowed={"with", "without"},
        error="讨论筛选不合法。",
        lower=True,
    )
    normalized_author = _labeling_filter_values(author, lower=True)
    normalized_assignee = _labeling_filter_values(assignee, lower=True)
    normalized_issue_ids = _parse_issue_id_filter(issue_ids)
    if _as_text(issue_ids).strip() and not normalized_issue_ids:
        raise _detail(400, "issue_ids 未包含有效的 Issue ID。")
    try:
        clusters = await asyncio.to_thread(
            database.labeling_clusters,
            baseline_scopes=scopes,
            task_id=_as_text(task_id),
            search=_as_text(q),
            issue_ids=normalized_issue_ids,
            status=normalized_status,
            author=normalized_author,
            assignee=normalized_assignee,
            exclusion=normalized_exclusion,
            expected_output=normalized_label,
            gt_label=normalized_gt,
            comment_state=normalized_comment_state,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {
        "items": clusters,
        "filters": {
            "baseline_scopes": scopes,
            "task_id": _as_text(task_id),
            "q": _as_text(q),
            "issue_ids": normalized_issue_ids,
            "status": normalized_status,
            "author": normalized_author,
            "assignee": normalized_assignee,
            "exclusion": normalized_exclusion,
            "label": normalized_label,
            "gt": normalized_gt,
            "comment_state": normalized_comment_state,
        },
    }

@router.get("/api/labeling/cases/{issue_id}")
async def get_labeling_case(
    issue_id: str,
    request: Request,
    task_id: str = "",
) -> dict[str, Any]:
    identity = await _require_labeling_writer(request)
    issue = await _require_active_labeling_issue(issue_id)
    scopes = resolve_request_baseline_scopes("", request=request)
    if scopes and str(issue.get("baseline_scope") or "") not in scopes:
        raise _detail(404, "Issue 不在当前数据集。")
    task_key = _as_text(task_id)
    cases = await asyncio.to_thread(database.label_cases_for_issue, issue_id)
    assignment = (
        await asyncio.to_thread(
            database.review_assignment_context,
            issue_id,
            model_run_id="",
            username=identity.username,
            work_split_id=task_key,
        )
        if task_key
        else None
    )
    detailed_cases = []
    for item in cases:
        detail = await asyncio.to_thread(database.get_label_case, item["id"])
        detailed_cases.append(_public_label_case(detail or item))
    comments = await asyncio.to_thread(
        database.list_label_comments,
        issue_id=issue_id,
        task_id=_as_text(task_id),
    )
    label_state = await asyncio.to_thread(
        database.project_issue_label_states,
        str(issue.get("baseline_scope") or ""),
        [issue_id],
        include_sources=True,
        preloaded_cases={issue_id: cases},
    )
    decision_history = await asyncio.to_thread(
        database.list_issue_label_decisions,
        baseline_scope=str(issue.get("baseline_scope") or ""),
        issue_id=issue_id,
    )
    assets, camera = empty_case_media(issue_id)
    return {
        "issue_id": issue_id,
        "baseline_scope": str(issue.get("baseline_scope") or ""),
        "title": str(issue.get("title") or ""),
        "scenario": str(issue.get("scenario") or ""),
        "summary": str(issue.get("summary") or ""),
        "gt_label": str(issue.get("gt_label") or ""),
        "gt_source": str(issue.get("gt_source") or ""),
        "trail_url": str(issue.get("trail_url") or ""),
        "voyager_issue_url": _voyager_issue_url(issue_id),
        "label_cases": detailed_cases,
        "comments": [_public_label_comment(comment) for comment in comments],
        "task_id": task_key,
        "current_user_is_task_member": bool(assignment and assignment.get("assigned")),
        "label_state": label_state.get(issue_id) or {},
        "decision_history": decision_history,
        "assets": assets,
        "camera": camera,
        "media_status": "pending",
    }
