"""Labeling tasks HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from ...db import LABELS
from fastapi import Request
from ...support.identity import _admin_identity
from ...support.common import _as_text
from ...support.common import _detail
from ...support.catalogs import _parse_issue_id_filter
import asyncio
from ...runtime import database
from ...work_split import distribute_issue_ids
from ...work_split import normalize_overlap_ratio
from ...support.baselines import resolve_request_baseline_scopes
from .common import _active_labeling_scopes, _labeling_filter_values, _require_labeling_writer

router = APIRouter()


@router.get("/api/labeling/tasks")
async def list_labeling_tasks(request: Request, baselines: str = "") -> dict[str, Any]:
    await _require_labeling_writer(request)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    if not scopes:
        return {"items": [], "baseline_scopes": scopes}
    tasks = await asyncio.to_thread(database.list_labeling_tasks, scopes)
    task_ids = [str(item["id"]) for item in tasks]
    progress = (
        await asyncio.to_thread(database.labeling_task_progress, scopes, task_ids)
        if task_ids
        else {}
    )
    empty_progress = {
        "total": 0,
        "resolved": 0,
        "conflict": 0,
        "pending": 0,
        "assignees": [],
    }
    for item in tasks:
        item["progress"] = progress.get(str(item["id"]), dict(empty_progress))
    return {"items": tasks, "baseline_scopes": scopes}

@router.post("/api/labeling/tasks")
async def create_labeling_task(request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_admin_identity, request)
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "任务请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "任务请求必须是 JSON 对象。")
    task_name = " ".join(_as_text(body.get("name")).split())
    if len(task_name) > 80:
        raise _detail(400, "实验名称不能超过 80 个字符。")
    raw_issue_ids = body.get("issue_ids") or []
    if not isinstance(raw_issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    issue_ids = list(dict.fromkeys(_as_text(value) for value in raw_issue_ids))
    issue_ids = [value for value in issue_ids if value]
    filter_body = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    if not issue_ids and filter_body:
        scopes = resolve_request_baseline_scopes(
            _as_text(filter_body.get("baselines")), request=request
        )
        scopes = await _active_labeling_scopes(scopes)
        normalized_status = _labeling_filter_values(
            filter_body.get("status"),
            allowed={"pending", "resolved", "conflict"},
            error="标注状态不合法。",
            lower=True,
        )
        normalized_exclusion = _labeling_filter_values(
            filter_body.get("exclusion"),
            allowed={"excluded", "active"},
            error="排除筛选不合法。",
            lower=True,
        )
        normalized_label = _labeling_filter_values(
            filter_body.get("label"),
            allowed=set(LABELS),
            error="标注结果类别不合法。",
        )
        normalized_cluster = _as_text(filter_body.get("cluster")).strip()
        normalized_gt = _labeling_filter_values(
            filter_body.get("gt"),
            allowed=set(LABELS),
            error="GT 类别不合法。",
        )
        normalized_comment_state = _labeling_filter_values(
            filter_body.get("comment_state"),
            allowed={"with", "without"},
            error="讨论筛选不合法。",
            lower=True,
        )
        raw_filter_issue_ids = _as_text(filter_body.get("issue_ids"))
        normalized_issue_ids = _parse_issue_id_filter(raw_filter_issue_ids)
        if raw_filter_issue_ids.strip() and not normalized_issue_ids:
            raise _detail(400, "issue_ids 未包含有效的 Issue ID。")
        try:
            resolved = await asyncio.to_thread(
                database.labeling_case_issue_ids,
                baseline_scopes=scopes,
                task_id=_as_text(filter_body.get("task_id")),
                search=_as_text(filter_body.get("q")),
                issue_ids=normalized_issue_ids,
                status=normalized_status,
                author=_labeling_filter_values(filter_body.get("author"), lower=True),
                assignee=_labeling_filter_values(filter_body.get("assignee"), lower=True),
                exclusion=normalized_exclusion,
                expected_output=normalized_label,
                gt_label=normalized_gt,
                comment_state=normalized_comment_state,
                cluster=normalized_cluster,
            )
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc
        issue_ids = list(dict.fromkeys(resolved))
    if len(issue_ids) > 5000:
        raise _detail(400, "单个标注任务最多包含 5000 个 Issue。")
    assignees = body.get("assignees") or []
    if not issue_ids or not isinstance(assignees, list) or not assignees:
        raise _detail(400, "任务必须包含 Issue 和标注人。")
    try:
        reviewers_per_issue = int(body.get("reviewers_per_issue") or 1)
        seed = int(body["seed"]) if body.get("seed") not in (None, "") else None
        overlap_ratio = normalize_overlap_ratio(
            body.get("overlap_ratio"), reviewers_per_issue=reviewers_per_issue
        )
        assignments = distribute_issue_ids(
            issue_ids,
            assignees,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
        )
        scope_values = {
            str((await asyncio.to_thread(database.get_issue, issue_id) or {}).get("baseline_scope") or "")
            for issue_id in issue_ids
        }
        if len(scope_values) != 1 or "" in scope_values:
            raise ValueError("一个标注任务只能包含一个已注册数据集。")
        if next(iter(scope_values)) not in set(
            await asyncio.to_thread(database.active_labeling_scopes)
        ):
            raise ValueError("该数据集的 Case 标注迁移尚未激活。")
        workset = await asyncio.to_thread(
            database.create_review_workset,
            baseline_scope=next(iter(scope_values)),
            issue_ids=issue_ids,
            name=task_name or f"标注任务 {len(issue_ids)}",
            selection_source_run_id=_as_text(body.get("selection_source_run_id")),
            source_filter=body.get("source_filter") if isinstance(body.get("source_filter"), dict) else {},
            created_by=identity.username,
            created_by_source=identity.source,
            created_by_verified=True,
        )
        task = await asyncio.to_thread(
            database.create_labeling_task,
            workset_id=workset["id"],
            assignments=assignments,
            created_by=identity.username,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
            created_by_source=identity.source,
            created_by_verified=True,
            idempotency_key=_as_text(
                request.headers.get("idempotency-key") or body.get("request_id")
            ).strip(),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "task": task,
        "workset": workset,
        "split_id": task["id"],
        "total": len(issue_ids),
        "assignments": assignments,
        "reviewers_per_issue": task["reviewers_per_issue"],
        "overlap_ratio": task["overlap_ratio"],
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
