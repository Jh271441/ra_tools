"""Review work-split listing, detail, reassignment, and reviewer facet routes."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...auth import normalise_username, request_identity
from ...contracts import ISSUE_ID_RE
from ...core.deps import get_baseline_registry, get_db, get_settings, resolve_dep
from ...db_parts.task_lifecycle import normalize_task_lifecycle, task_list_metrics
from ...runtime import baseline_registry, database, settings
from ...schemas import WorkSplitListResponse
from ...support.baselines import (
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
    restrict_version_issue_ids,
    task_baseline_ids,
)
from ...support.common import _as_text, _detail
from ...support.identity import _admin_identity, _writer_identity

router = APIRouter()


@router.get("/api/cases/work-splits", responses={200: {"model": WorkSplitListResponse}})
async def list_case_work_splits(
    request: Request,
    limit: int = 50,
    model_run_id: str = "",
    lifecycle: str = "current",
    assigned_to_me: bool = False,
    group_by_version: bool = False,
    version_only: bool = False,
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    """Writer/admin history and progress for Review task allocations."""

    db = resolve_dep(db, lambda: database)
    identity = await asyncio.to_thread(_writer_identity, request)
    try:
        lifecycle = normalize_task_lifecycle(lifecycle)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    assignee = identity.username if assigned_to_me else ""
    items = await asyncio.to_thread(
        db.list_review_work_splits,
        limit=max(1, min(int(limit or 50), 100)),
        model_run_id=_as_text(model_run_id),
        lifecycle=lifecycle,
        assignee=assignee,
    )
    query_params = getattr(request, "query_params", None) or {}
    manual_only = str(query_params.get("manual_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if group_by_version and lifecycle != "history":
        from ...version_review_tasks import merge_version_task_list, version_tasks

        parents = await asyncio.to_thread(
            version_tasks,
            db,
            assignee=assignee,
            model_run_id=model_run_id,
            lifecycle=lifecycle,
        )
        items = merge_version_task_list(
            parents, items, version_only=version_only, manual_only=manual_only
        )
    for item in items:
        item["baseline_ids"] = await asyncio.to_thread(
            task_baseline_ids,
            item.get("baseline_scopes") or item.get("baseline_ids") or [],
            item["split_id"],
        )
    return {
        "items": items,
        "metrics": task_list_metrics(items, assignee),
        "lifecycle": lifecycle,
        "assigned_to_me": assigned_to_me,
        "change_revision": await asyncio.to_thread(db.change_revision),
    }


@router.get("/api/review-work-splits")
async def review_work_split_options(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
    all_baselines: bool = False,
    assigned_to_me: bool = False,
    lifecycle: str = "current",
    db: Any = Depends(get_db),
    cfg: Any = Depends(get_settings),
    baselines_reg: Any = Depends(get_baseline_registry),
) -> dict[str, Any]:
    """Return task options; the entry picker may discover own tasks across datasets."""

    db = resolve_dep(db, lambda: database)
    cfg = resolve_dep(cfg, lambda: settings)
    baselines_reg = resolve_dep(baselines_reg, lambda: baseline_registry)
    try:
        lifecycle = normalize_task_lifecycle(lifecycle)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    selected_baselines = (
        set()
        if all_baselines
        else set(resolve_request_baseline_ids(baselines, request=request))
    )
    assignee = ""
    if assigned_to_me:
        identity = await asyncio.to_thread(request_identity, request, cfg)
        if not identity.verified or not identity.username:
            return {"items": []}
        assignee = identity.username
    raw_items = await asyncio.to_thread(
        db.list_review_work_splits,
        limit=100,
        model_run_id=_as_text(model_run_id),
        assignee=assignee,
        lifecycle=lifecycle,
        issue_ids=()
        if all_baselines
        else await asyncio.to_thread(
            restrict_version_issue_ids, baselines, request=request
        ),
    )

    def snapshot_baselines(item: dict[str, Any]) -> set[str]:
        snapshot = item.get("filter_snapshot") or {}
        raw = (
            item.get("baseline_scopes")
            or snapshot.get("baselines")
            or snapshot.get("baseline_scopes")
            or []
        )
        if isinstance(raw, str):
            values = raw.split(",")
        elif isinstance(raw, (list, tuple, set)):
            values = raw
        else:
            values = []
        normalized = set()
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            normalized.add(baselines_reg.scope_to_id(text) or text)
        if normalized.intersection({"0821", "0821-review-extra", "0821-trail-extra"}):
            return set(task_baseline_ids(list(values), item["split_id"]))
        return normalized

    items = []
    for item in raw_items:
        can_review = bool(item.get("is_current")) and item.get("lifecycle", "active") in {
            "",
            "active",
        }
        if lifecycle in {"current", "active"} and not can_review:
            continue
        item_baselines = snapshot_baselines(item)
        if (
            selected_baselines
            and item_baselines
            and selected_baselines.isdisjoint(item_baselines)
        ):
            continue
        items.append(
            {
                "split_id": str(item.get("split_id") or ""),
                "lifecycle": str(item.get("lifecycle") or "active"),
                "can_review": can_review,
                "name": str(item.get("campaign_name") or ""),
                "model_run_id": str(item.get("model_run_id") or ""),
                "created_at": str(item.get("created_at") or ""),
                "created_by": str(item.get("created_by") or ""),
                "mode": str(item.get("mode") or "single"),
                "workflow_mode": str(item.get("workflow_mode") or "model_review_only"),
                "reviewers_per_issue": int(item.get("reviewers_per_issue") or 1),
                "total_count": int(item.get("total_count") or 0),
                "assignment_count": int(item.get("assignment_count") or 0),
                "completed_count": int(item.get("completed_count") or 0),
                "baselines": sorted(item_baselines),
            }
        )
    return {"items": items}


@router.get("/api/cases/work-splits/{split_id}")
async def get_case_work_split(
    split_id: str,
    request: Request,
    page: int = 1,
    page_size: int = 50,
    assignee: str = "",
    status: str = "all",
    q: str = "",
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    """Writer/admin paginated task detail for one allocation batch."""

    db = resolve_dep(db, lambda: database)
    await asyncio.to_thread(_writer_identity, request)
    try:
        if split_id.startswith("version:") or await asyncio.to_thread(
            db.version_campaign_dataset, split_id
        ):
            from ...version_review_tasks import version_task_detail

            result = await asyncio.to_thread(
                version_task_detail,
                db,
                split_id,
                page=max(1, int(page)),
                page_size=max(10, min(int(page_size), 100)),
                assignee=assignee,
                status=status,
                query=q[:128],
            )
            if result is None:
                raise _detail(404, "Version task not found")
            return result
        result = await asyncio.to_thread(
            db.get_review_work_split,
            split_id,
            page=max(1, int(page or 1)),
            page_size=max(10, min(int(page_size or 50), 100)),
            assignee=_as_text(assignee),
            status=_as_text(status),
            query=_as_text(q),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if result is None:
        raise _detail(404, "分配批次不存在。")
    result["baseline_ids"] = await asyncio.to_thread(
        task_baseline_ids, result.get("baseline_scopes") or [], split_id
    )
    return result


@router.patch("/api/cases/work-splits/{split_id}/assignments/{issue_id}")
async def reassign_case_work_item(
    split_id: str,
    issue_id: str,
    request: Request,
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    """Admin-only transfer of one unfinished Review task."""

    db = resolve_dep(db, lambda: database)
    identity = await asyncio.to_thread(_admin_identity, request)
    if not ISSUE_ID_RE.fullmatch(issue_id):
        raise _detail(404, "Issue 不存在。")
    raw = await request.body()
    if len(raw) > 8 * 1024:
        raise _detail(413, "任务调整请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "任务调整请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "任务调整请求必须是 JSON 对象。")
    assignee = normalise_username(str(body.get("assignee") or "")).lower()
    if not assignee:
        raise _detail(400, "新负责人账号格式非法。")
    access_users = await asyncio.to_thread(db.list_access_users)
    eligible = {
        str(item.get("username") or "").strip().lower() for item in access_users
    }
    if assignee not in eligible:
        raise _detail(400, "新负责人不在 Dashboard 用户列表中。")
    try:
        change = await asyncio.to_thread(
            db.reassign_review_work_assignment,
            split_id=split_id,
            issue_id=issue_id,
            assignee=assignee,
            changed_by=identity.username,
        )
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    detail = await asyncio.to_thread(
        db.get_review_work_split,
        split_id,
        page=1,
        page_size=50,
    )
    return {
        "change": change,
        "split": detail,
        "change_revision": await asyncio.to_thread(db.change_revision),
    }


@router.get("/api/reviewers")
async def reviewers(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    db = resolve_dep(db, lambda: database)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    items = await asyncio.to_thread(
        db.list_analysis_reviewers,
        baseline_scopes=scopes,
        model_run_id=model_run_id,
        issue_ids=await asyncio.to_thread(
            restrict_version_issue_ids, baselines, request=request
        ),
    )
    return {"items": items, "analysis_items": items}
