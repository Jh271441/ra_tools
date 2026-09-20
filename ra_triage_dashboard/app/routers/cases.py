from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from ..case_media import empty_case_media, resolve_case_media
from ..contracts import ISSUE_ID_RE
from ..runtime import _public_path
from ..support.attachments import (
    _public_review_attachment,
)
from ..support.baselines import (
    media_for_issue,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..support.catalogs import _review_tag_catalog
from ..support.common import (
    _as_text,
    _detail,
)
from ..support.external_links import (
    _case_external_links,
    _case_link_metadata_fallback,
    _public_batch_job,
    _voyager_issue_url,
    resolve_disable_ra_simulation_version,
)
from ..support.filter_parsing import _case_filter_kwargs
from ..support.identity import _admin_identity
from ..support.thumbnails import _render_case_thumbnail, _thumbnail_cache_path
from ..review_workflow import derive_review_status, effective_expected_output
from ..auth import SessionIdentity, normalise_username, request_identity
from ..runtime import (
    asset_index,
    baseline_registry,
    camera_index,
    database,
    issue_tag_sources,
    logger,
    settings,
    trail_detail_semaphore,
    video_index,
)
from ..trail_sync import read_trail_issue_metadata
from ..work_split import distribute_issue_ids, normalize_overlap_ratio

router = APIRouter()

# issue_id -> (source_path, mtime_ns, size, dest_jpeg)
_thumbnail_dest_cache: dict[str, tuple[str, int, int, Path]] = {}
_thumbnail_encode_gate = threading.Semaphore(8)


def _visible_case_annotations(
    annotations: list[dict[str, Any]],
    assignment: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return the complete Issue audit trail; blind mode only isolates writes."""

    blind_active = bool(assignment and assignment.get("mode") == "blind")
    return list(annotations), blind_active


def _resolve_thumbnail_file(issue_id: str) -> Path | None:
    """Resolve/build a gallery JPEG entirely outside the event loop.

    Homepage requests arrive in bursts. Reusing the process-local path cache
    avoids a mandatory case-row lookup, while the caller offloads this whole
    DB/filesystem/Pillow worker with one ``asyncio.to_thread`` hop.
    """

    cached = _thumbnail_dest_cache.get(issue_id)
    if cached is not None:
        source_s, mtime_ns, size, dest = cached
        source = Path(source_s)
        try:
            stat = source.stat()
        except OSError:
            _thumbnail_dest_cache.pop(issue_id, None)
        else:
            if (
                stat.st_mtime_ns == mtime_ns
                and stat.st_size == size
                and dest.is_file()
            ):
                return dest

    case = database.get_issue(issue_id)
    if case is None:
        return None
    provider = media_for_issue(issue_id, str(case.get("baseline_scope") or ""))
    info = provider.get_thumbnail_source(issue_id) if provider is not None else None
    if not info or not isinstance(info.get("path"), Path):
        return None
    source = info["path"]
    try:
        stat = source.stat()
    except OSError:
        return None
    destination = _thumbnail_cache_path(issue_id, source)
    if not destination.is_file():
        with _thumbnail_encode_gate:
            if not destination.is_file():
                _ensure_case_thumbnail(source, destination)
    _thumbnail_dest_cache[issue_id] = (
        str(source),
        stat.st_mtime_ns,
        stat.st_size,
        destination,
    )
    # Bound memory if the process stays up for a long gallery session.
    if len(_thumbnail_dest_cache) > 4000:
        for key in list(_thumbnail_dest_cache.keys())[:1000]:
            _thumbnail_dest_cache.pop(key, None)
    return destination


def _with_effective_case_review_status(
    item: dict[str, Any], tag_catalog: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    """Expose the same derived status used by analysis and GT export."""

    public = dict(item)
    annotation = dict(item.get("annotation") or {})
    expected_output, source = effective_expected_output(annotation, tag_catalog)
    annotation["expected_output"] = expected_output
    annotation["expected_output_source"] = source
    annotation["label"] = expected_output
    annotation["review_status"] = derive_review_status(
        expected_output,
        item.get("gt_label"),
    )
    public["annotation"] = annotation
    return public


def _empty_issue_label_state() -> dict[str, Any]:
    return {
        "state": "none",
        "expected_output": "",
        "gt_relation": "unknown",
        "method": "single",
        "source_task_ids": [],
        "source_revision_ids": [],
        "sources": [],
    }


def _project_case_label_states(
    items: list[dict[str, Any]], *, include_sources: bool = True
) -> dict[str, dict[str, Any]]:
    issue_ids_by_scope: dict[str, list[str]] = {}
    projected: dict[str, dict[str, Any]] = {}
    for item in items:
        issue_id = _as_text(item.get("issue_id"))
        scope = _as_text(item.get("baseline_scope"))
        if not issue_id:
            continue
        if not scope:
            projected[issue_id] = _empty_issue_label_state()
            continue
        issue_ids_by_scope.setdefault(scope, []).append(issue_id)
    for scope, issue_ids in issue_ids_by_scope.items():
        projected.update(
            database.project_issue_label_states(
                scope, issue_ids, include_sources=include_sources
            )
        )
    return projected


def _case_derived_issue_ids(
    *,
    filters: dict[str, Any],
    review_statuses: tuple[str, ...],
    label_states: tuple[str, ...],
    tag_catalog: tuple[dict[str, Any], ...] | None = None,
) -> list[str]:
    """Apply derived Review/label filters across the complete candidate scan."""

    allowed_review_statuses = set(review_statuses)
    allowed_label_states = set(label_states)
    catalog = tag_catalog if tag_catalog is not None else (
        _review_tag_catalog() if allowed_review_statuses else ()
    )
    matching_ids: list[str] = []
    for candidates in database.iter_case_review_candidate_batches(
        batch_size=400,
        **filters,
    ):
        label_state_by_id = (
            _project_case_label_states(candidates, include_sources=False)
            if allowed_label_states
            else {}
        )
        for item in candidates:
            issue_id = _as_text(item.get("issue_id"))
            if allowed_review_statuses:
                status = _with_effective_case_review_status(item, catalog)["annotation"][
                    "review_status"
                ]
                if status not in allowed_review_statuses:
                    continue
            if allowed_label_states:
                projection = label_state_by_id.get(issue_id, _empty_issue_label_state())
                state = str(projection.get("state") or "none")
                relation = str(projection.get("gt_relation") or "unknown")
                state_matches = any(
                    (
                        selected == state
                        or (
                            selected == "needs_gt_review"
                            and state == "resolved"
                            and relation in {"differs_from_gt", "fills_missing_gt"}
                        )
                        or (
                            selected == "matches_gt"
                            and state == "resolved"
                            and relation == "matches_gt"
                        )
                        or (
                            selected == "unknown"
                            and state == "resolved"
                            and relation == "unknown"
                        )
                    )
                    for selected in allowed_label_states
                )
                if not state_matches:
                    continue
            if issue_id:
                matching_ids.append(issue_id)
    return matching_ids


def _case_result_with_status_filter(
    *,
    filters: dict[str, Any],
    review_statuses: tuple[str, ...],
    page: int,
    page_size: int,
    label_states: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Filter derived Review and shared-label states before pagination."""

    tag_catalog = _review_tag_catalog()
    if review_statuses or label_states:
        matching_ids = _case_derived_issue_ids(
            filters=filters,
            review_statuses=review_statuses,
            label_states=label_states,
            tag_catalog=tag_catalog,
        )
        start = (page - 1) * page_size
        page_ids = matching_ids[start : start + page_size]
        if page_ids:
            page_filters = {**filters, "issue_ids": page_ids}
            raw = database.list_cases(
                **page_filters,
                page=1,
                page_size=len(page_ids),
            )
            items = [
                _with_effective_case_review_status(item, tag_catalog)
                for item in raw.get("items", [])
            ]
            label_state_by_id = _project_case_label_states(items)
            for item in items:
                item["label_state"] = label_state_by_id.get(
                    _as_text(item.get("issue_id")), _empty_issue_label_state()
                )
        else:
            items = []
        return {
            "items": items,
            "total": len(matching_ids),
            "page": page,
            "page_size": page_size,
        }

    result = database.list_cases(
        **filters,
        page=page,
        page_size=page_size,
    )
    result["items"] = [
        _with_effective_case_review_status(item, tag_catalog)
        for item in result.get("items", [])
    ]
    label_state_by_id = _project_case_label_states(result.get("items", []))
    for item in result.get("items", []):
        item["label_state"] = label_state_by_id.get(
            _as_text(item.get("issue_id")), _empty_issue_label_state()
        )
    return result


def _case_issue_ids_with_status_filter(
    *,
    filters: dict[str, Any],
    review_statuses: tuple[str, ...],
    label_states: tuple[str, ...] = (),
) -> list[str]:
    return _case_derived_issue_ids(
        filters=filters,
        review_statuses=review_statuses,
        label_states=label_states,
    )


def _public_case_items(
    rows: list[dict[str, Any]], *, include_thumbnail: bool
) -> list[dict[str, Any]]:
    """Build case summaries and resolve optional media flags off-loop."""

    items: list[dict[str, Any]] = []
    for item in rows:
        issue_id = _as_text(item.get("issue_id"))
        public = {
            **item,
            "voyager_issue_url": _voyager_issue_url(issue_id),
        }
        if include_thumbnail:
            provider = media_for_issue(
                issue_id, str(item.get("baseline_scope") or "")
            )
            has_thumb = bool(provider and provider.has_issue(issue_id))
            public["thumbnail"] = (
                {
                    "url": _public_path(
                        f"/api/case-thumbnails/{quote(issue_id, safe='')}"
                    ),
                    "kind": "bev",
                    "label": "BEV · t0 附近",
                }
                if has_thumb
                else None
            )
        items.append(public)
    return items


def _ensure_case_thumbnail(source: Path, destination: Path) -> None:
    """Create a missing thumbnail atomically on a worker thread."""

    if not destination.is_file():
        _render_case_thumbnail(source, destination)


@router.get("/api/cases")
async def list_cases(
    request: Request,
    search: str = "",
    gt_label: str = "",
    model_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    review_status: str = "",
    label_state: str = "",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
    work_split_id: str = "",
    comment_state: str = "all",
    exclusion: str = "",
    baselines: str = "",
    page: int = 1,
    page_size: int = 100,
    include_thumbnail: bool = False,
) -> dict[str, Any]:
    filters = _case_filter_kwargs(
        search=search,
        gt_label=gt_label,
        model_label=model_label,
        annotation_label=annotation_label,
        annotation_author=annotation_author,
        review_status=review_status,
        label_state=label_state,
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        issue_ids=issue_ids,
        work_assignee=work_assignee,
        work_split_id=work_split_id,
        comment_state=comment_state,
        exclusion=exclusion,
        baselines=baselines,
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    label_states = tuple(filters.pop("label_states", ()))
    exclusion_filter = str(filters.pop("exclusion", "all"))
    identity = await asyncio.to_thread(request_identity, request, settings)
    filters["preferred_annotation_author"] = (
        identity.username if identity.verified and identity.username else ""
    )
    comparison_status = filters["comparison_status"]
    safe_page = max(1, int(page))
    safe_page_size = min(max(1, int(page_size)), 100)
    result = await asyncio.to_thread(
        _case_result_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
        label_states=label_states,
        page=safe_page,
        page_size=safe_page_size,
    )
    result["items"] = await asyncio.to_thread(
        _public_case_items,
        result.get("items", []),
        include_thumbnail=include_thumbnail,
    )
    if "gt_snapshots" not in result:
        result["gt_snapshots"] = await asyncio.to_thread(
            database.active_gt_snapshots,
            filters.get("baseline_scopes") or [],
        )
    result["filters"] = {
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": comparison_status == "mismatch",
        "issue_ids": filters["issue_ids"],
        "work_assignee": filters["work_assignee"],
        "work_split_id": filters["work_split_id"],
        "comment_state": filters["comment_state"],
        "review_status": list(review_statuses),
        "label_state": list(label_states),
        "exclusion": exclusion_filter,
        "baselines": resolve_request_baseline_ids(baselines, request=request),
        "baseline_scopes": filters.get("baseline_scopes") or [],
    }
    return result



@router.get("/api/cases/issue-ids")
async def list_case_issue_ids(
    request: Request,
    search: str = "",
    gt_label: str = "",
    model_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    review_status: str = "",
    label_state: str = "",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
    work_split_id: str = "",
    comment_state: str = "all",
    exclusion: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Return all matching issue IDs for the current Review filters (capped)."""

    filters = _case_filter_kwargs(
        search=search,
        gt_label=gt_label,
        model_label=model_label,
        annotation_label=annotation_label,
        annotation_author=annotation_author,
        review_status=review_status,
        label_state=label_state,
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        issue_ids=issue_ids,
        work_assignee=work_assignee,
        work_split_id=work_split_id,
        comment_state=comment_state,
        exclusion=exclusion,
        baselines=baselines,
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    label_states = tuple(filters.pop("label_states", ()))
    exclusion_filter = str(filters.pop("exclusion", "all"))
    identity = await asyncio.to_thread(request_identity, request, settings)
    filters["preferred_annotation_author"] = (
        identity.username if identity.verified and identity.username else ""
    )
    ids = await asyncio.to_thread(
        _case_issue_ids_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
        label_states=label_states,
    )
    return {
        "issue_ids": ids,
        "total": len(ids),
        "truncated": False,
        "filters": {
            "model_run_id": model_run_id,
            "comparison_status": filters["comparison_status"],
            "failure_only": filters["comparison_status"] == "mismatch",
            "issue_ids": filters["issue_ids"],
            "work_assignee": filters["work_assignee"],
            "work_split_id": filters["work_split_id"],
            "comment_state": filters["comment_state"],
            "review_status": list(review_statuses),
            "label_state": list(label_states),
            "exclusion": exclusion_filter,
        },
    }

@router.get("/api/work-assignees")
async def work_assignees(
    request: Request,
    search: str = "",
    gt_label: str = "",
    model_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    review_status: str = "",
    label_state: str = "",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_split_id: str = "",
    comment_state: str = "all",
    exclusion: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Assignee facet scoped to the current Review queue."""

    filters = _case_filter_kwargs(
        search=search,
        gt_label=gt_label,
        model_label=model_label,
        annotation_label=annotation_label,
        annotation_author=annotation_author,
        review_status=review_status,
        label_state=label_state,
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        issue_ids=issue_ids,
        work_assignee="",
        work_split_id=work_split_id,
        comment_state=comment_state,
        exclusion=exclusion,
        baselines=baselines,
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    label_states = tuple(filters.pop("label_states", ()))
    exclusion_filter = str(filters.pop("exclusion", "all"))
    filtered_issue_ids = await asyncio.to_thread(
        _case_issue_ids_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
        label_states=label_states,
    )
    return {
        "items": await asyncio.to_thread(
            database.list_work_assignees,
            issue_ids=filtered_issue_ids,
            model_run_id=filters["model_run_id"],
        ),
        "total": len(filtered_issue_ids),
        "filters": {
            "model_run_id": filters["model_run_id"],
            "comparison_status": filters["comparison_status"],
            "review_status": list(review_statuses),
            "label_state": list(label_states),
            "comment_state": filters["comment_state"],
            "exclusion": exclusion_filter,
            "baselines": resolve_request_baseline_ids(
                baselines, request=request
            ),
        },
    }


@router.get("/api/cases/work-splits")
async def list_case_work_splits(
    request: Request,
    limit: int = 50,
    model_run_id: str = "",
) -> dict[str, Any]:
    """Admin-only history and progress for Review task allocations."""

    await asyncio.to_thread(_admin_identity, request)
    items = await asyncio.to_thread(
        database.list_review_work_splits,
        limit=max(1, min(int(limit or 50), 100)),
        model_run_id=_as_text(model_run_id),
    )
    return {"items": items, "change_revision": await asyncio.to_thread(database.change_revision)}


@router.get("/api/review-work-splits")
async def review_work_split_options(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Return minimal current task batches for the read-only Review filters."""

    selected_baselines = set(resolve_request_baseline_ids(baselines, request=request))
    raw_items = await asyncio.to_thread(
        database.list_review_work_splits,
        limit=100,
        model_run_id=_as_text(model_run_id),
    )

    def snapshot_baselines(item: dict[str, Any]) -> set[str]:
        snapshot = item.get("filter_snapshot") or {}
        raw = snapshot.get("baselines") or snapshot.get("baseline_scopes") or []
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
            normalized.add(baseline_registry.scope_to_id(text) or text)
        return normalized

    items = []
    for item in raw_items:
        if not item.get("is_current"):
            continue
        item_baselines = snapshot_baselines(item)
        if selected_baselines and item_baselines and selected_baselines.isdisjoint(item_baselines):
            continue
        items.append(
            {
                "split_id": str(item.get("split_id") or ""),
                "model_run_id": str(item.get("model_run_id") or ""),
                "created_at": str(item.get("created_at") or ""),
                "created_by": str(item.get("created_by") or ""),
                "mode": str(item.get("mode") or "single"),
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
) -> dict[str, Any]:
    """Admin-only paginated task detail for one allocation batch."""

    await asyncio.to_thread(_admin_identity, request)
    try:
        result = await asyncio.to_thread(
            database.get_review_work_split,
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
    return result


@router.patch("/api/cases/work-splits/{split_id}/assignments/{issue_id}")
async def reassign_case_work_item(
    split_id: str,
    issue_id: str,
    request: Request,
) -> dict[str, Any]:
    """Admin-only transfer of one unfinished Review task."""

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
    access_users = await asyncio.to_thread(database.list_access_users)
    eligible = {str(item.get("username") or "").strip().lower() for item in access_users}
    if assignee not in eligible:
        raise _detail(400, "新负责人不在 Dashboard 用户列表中。")
    try:
        change = await asyncio.to_thread(
            database.reassign_review_work_assignment,
            split_id=split_id,
            issue_id=issue_id,
            assignee=assignee,
            changed_by=identity.username,
        )
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    detail = await asyncio.to_thread(
        database.get_review_work_split,
        split_id,
        page=1,
        page_size=50,
    )
    return {
        "change": change,
        "split": detail,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.post("/api/cases/work-split")
async def split_case_work(request: Request) -> dict[str, Any]:
    """Admin-only: randomly assign filtered issues and persist ownership."""

    identity = await asyncio.to_thread(_admin_identity, request)
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "均分任务请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "均分任务请求必须是 JSON 对象。")
    filter_body = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    filters = _case_filter_kwargs(
        search=_as_text(filter_body.get("search")),
        gt_label=_as_text(filter_body.get("gt_label")),
        model_label=_as_text(filter_body.get("model_label")),
        annotation_label=_as_text(filter_body.get("annotation_label")),
        annotation_author=_as_text(filter_body.get("annotation_author")),
        review_status=_as_text(filter_body.get("review_status")),
        label_state=_as_text(filter_body.get("label_state")),
        model_run_id=_as_text(filter_body.get("model_run_id")),
        comparison=_as_text(filter_body.get("comparison") or filter_body.get("comparison_status")),
        failure_only=bool(filter_body.get("failure_only")),
        missing_evidence=_as_text(filter_body.get("missing_evidence")),
        issue_ids=_as_text(filter_body.get("issue_ids")),
        work_assignee=_as_text(filter_body.get("work_assignee")),
        comment_state=_as_text(filter_body.get("comment_state") or "all"),
        exclusion=_as_text(filter_body.get("exclusion")),
        baselines=_as_text(filter_body.get("baselines") or filter_body.get("baseline_scopes")),
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    label_states = tuple(filters.pop("label_states", ()))
    exclusion_filter = str(filters.pop("exclusion", "all"))
    issue_ids = await asyncio.to_thread(
        _case_issue_ids_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
        label_states=label_states,
    )
    if len(issue_ids) > 5000:
        raise _detail(400, "均分任务单次最多包含 5000 个 Issue，请收窄筛选。")
    assignees = body.get("assignees")
    if not isinstance(assignees, list):
        raise _detail(400, "assignees 必须是数组。")
    raw_seed = body.get("seed", None)
    seed: int | None
    if raw_seed in (None, ""):
        seed = None
    else:
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError):
            raise _detail(400, "seed 必须是整数。")
    try:
        reviewers_per_issue = int(body.get("reviewers_per_issue") or 1)
    except (TypeError, ValueError):
        raise _detail(400, "reviewers_per_issue 必须是整数。")
    try:
        overlap_ratio = normalize_overlap_ratio(
            body.get("overlap_ratio"),
            reviewers_per_issue=reviewers_per_issue,
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    try:
        assignments = distribute_issue_ids(
            issue_ids,
            assignees,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
        )
        saved = await asyncio.to_thread(
            database.apply_work_split,
            assignments=assignments,
            created_by=identity.username,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
            model_run_id=filters["model_run_id"],
            filter_snapshot={
                "model_run_id": filters["model_run_id"],
                "comparison_status": filters["comparison_status"],
                "comment_state": filters["comment_state"],
                "search": filters["search"],
                "gt_label": filters["gt_label"],
                "model_label": filters["model_label"],
                "annotation_author": filters["annotation_author"],
                "review_status": list(review_statuses),
                "label_state": list(label_states),
                "exclusion": exclusion_filter,
                "missing_evidence": filters["missing_evidence"],
                "overlap_ratio": overlap_ratio,
                "baselines": filters.get("baseline_scopes") and resolve_request_baseline_ids(
                    ",".join(
                        baseline_registry.scope_to_id(s) or s
                        for s in (filters.get("baseline_scopes") or [])
                    )
                ) or baseline_registry.default_ids(),
                "baseline_scopes": filters.get("baseline_scopes") or [],
            },
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "total": len(issue_ids),
        "truncated": False,
        "seed": seed,
        "split_id": saved["split_id"],
        "created_by": saved["created_by"],
        "created_at": saved["created_at"],
        "assignments": assignments,
        "assignment_count": saved["assignment_count"],
        "reviewers_per_issue": saved["reviewers_per_issue"],
        "overlap_ratio": saved["overlap_ratio"],
        "work_assignees": await asyncio.to_thread(
            database.list_work_assignees,
            issue_ids=issue_ids,
            model_run_id=filters["model_run_id"],
        ),
        "change_revision": await asyncio.to_thread(database.change_revision),
        "filters": {
            "model_run_id": filters["model_run_id"],
            "comparison_status": filters["comparison_status"],
            "failure_only": filters["comparison_status"] == "mismatch",
            "work_assignee": filters["work_assignee"],
            "review_status": list(review_statuses),
            "label_state": list(label_states),
            "exclusion": exclusion_filter,
        },
    }



@router.get("/api/reviewers")
async def reviewers(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    items = await asyncio.to_thread(
        database.list_analysis_reviewers,
        baseline_scopes=scopes,
        model_run_id=model_run_id,
    )
    return {"items": items, "analysis_items": items}



@router.get("/api/case-thumbnails/{issue_id}")
async def get_case_thumbnail(issue_id: str) -> FileResponse:
    if not ISSUE_ID_RE.fullmatch(issue_id):
        raise _detail(404, "Issue 不存在。")

    try:
        destination = await asyncio.to_thread(_resolve_thumbnail_file, issue_id)
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        raise _detail(404, "该 Issue 的 BEV 缩略图无法生成。")
    if destination is None:
        raise _detail(404, "该 Issue 暂无 BEV 缩略图。")
    return FileResponse(
        destination,
        media_type="image/jpeg",
        # Fingerprint is content-addressed by source mtime/size, so long cache
        # is safe and avoids re-fetch storms when scrolling the gallery.
        headers={"Cache-Control": "public, max-age=86400"},
    )



@router.get("/api/cases/{issue_id}/trail-metadata")
async def get_case_trail_metadata(issue_id: str) -> dict[str, Any]:
    """Load optional Trail metadata without delaying the Issue detail API.

    The Issue detail response intentionally exposes only local data and any
    metadata already imported with the case.  Trail is a best-effort external
    dependency and is fetched by the browser after the detail has rendered.
    """

    case = await asyncio.to_thread(database.get_issue, issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")

    trail_metadata = _case_link_metadata_fallback(case)
    status = "disabled"
    if settings.trail_detail_metadata_enabled:
        status = "unavailable"
        try:
            async with trail_detail_semaphore:
                fetched = await asyncio.wait_for(
                    asyncio.to_thread(
                        read_trail_issue_metadata,
                        ra_root=settings.ra_auto_triage_root,
                        issue_id=issue_id,
                        view_id=settings.trail_view_id,
                        cache_seconds=settings.trail_detail_metadata_cache_seconds,
                    ),
                    timeout=8.0,
                )
            trail_metadata.update(fetched)
            status = "ready" if fetched else "unavailable"
        except asyncio.TimeoutError:
            status = "timeout"
            logger.warning("Trail detail metadata timed out issue_id=%s", issue_id)
        except Exception:
            status = "unavailable"
            logger.warning("Trail detail metadata unavailable issue_id=%s", issue_id)

    disable_ra_task_id = trail_metadata.get("te_task_id_disabe_ra")
    if disable_ra_task_id not in (None, ""):
        try:
            trail_metadata["te_task_version_disabe_ra"] = await asyncio.wait_for(
                asyncio.to_thread(
                    resolve_disable_ra_simulation_version,
                    disable_ra_task_id,
                ),
                timeout=3.5,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "disable-RA simulation version lookup timed out issue_id=%s",
                issue_id,
            )
        except Exception:
            logger.warning(
                "disable-RA simulation version unavailable issue_id=%s",
                issue_id,
            )

    dashboard_should_exclude = trail_metadata.get("dashboard_should_exclude")
    if not isinstance(dashboard_should_exclude, bool):
        dashboard_should_exclude = None

    return {
        "issue_id": issue_id,
        "status": status,
        "external_links": _case_external_links(issue_id, trail_metadata),
        # This is a read-only projection of the namespaced Trail info marker.
        # It deliberately does not create a local Review annotation or alter
        # Review aggregate counts until the reviewer saves the checkbox.
        "dashboard_should_exclude": dashboard_should_exclude,
        "dashboard_exclusion_status": (
            "synced" if isinstance(dashboard_should_exclude, bool)
            else "unavailable" if status != "ready"
            else "not_marked"
        ),
    }



@router.get("/api/cases/{issue_id}/media")
async def get_case_media(issue_id: str, kind: str = "all") -> dict[str, Any]:
    """Resolve deferred filesystem media for an already-loaded Issue detail.

    This intentionally contains no Trail metadata or Review DB projection.  A
    browser can render the reviewer form from ``/api/cases/{issue_id}`` first,
    then attach video/BEV/camera when their indexes finish scanning.
    """

    if kind not in {"all", "images", "bev", "video"}:
        raise _detail(400, "不支持的媒体模式。")
    case = await asyncio.to_thread(database.get_issue, issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    provider = media_for_issue(issue_id, str(case.get("baseline_scope") or ""))
    if provider is None:
        assets, camera = empty_case_media(issue_id)
        status = "unavailable"
    elif kind == "video":
        assets, camera = empty_case_media(issue_id)
        video = await asyncio.to_thread(provider.get_video, issue_id)
        if video is not None:
            assets["video"] = video
            assets["available"] = True
        status = "ready"
    elif kind != "all":
        assets = await asyncio.to_thread(provider.get_assets, issue_id)
        assets = {k: v for k, v in assets.items() if k != "video"}
        camera = {"frames": [], "available": False}
        if kind == "images":
            camera = await asyncio.to_thread(provider.get_camera_assets, issue_id, (assets.get("capture") or {}).get("timestamp_ms"))
        status = "ready"
    else:
        assets, camera = await resolve_case_media(provider, issue_id)
        status = "ready"
    return {
        "issue_id": issue_id,
        "gt_label": case.get("gt_label", ""),
        "assets": assets,
        "camera": camera,
        "media_status": status,
    }


@router.get("/api/cases/{issue_id}")
async def get_case(
    issue_id: str,
    request: Request = None,
    include_media: bool = True,
    model_run_id: str = "",
    work_split_id: str = "",
    reveal_answers: bool = False,
) -> dict[str, Any]:
    case = await asyncio.to_thread(database.get_case, issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    case["label_state"] = case.get("label_state") or _empty_issue_label_state()
    case["gt_snapshot"] = case.get("gt_snapshot")
    assignment = (
        await asyncio.to_thread(
            database.review_assignment_context,
            issue_id,
            model_run_id=model_run_id,
            username="",
            work_split_id=work_split_id,
        )
        if request is not None
        else None
    )
    identity = SessionIdentity()
    if request is not None and assignment and assignment.get("mode") == "blind":
        identity = await asyncio.to_thread(request_identity, request, settings)
        current_username = identity.username.lower() if identity.verified else ""
        own_assignment = next(
            (
                item for item in assignment.get("members", [])
                if item["username"].lower() == current_username
            ),
            None,
        )
        assignment["assigned"] = own_assignment is not None
        assignment["own_assignment"] = own_assignment
    answers_revealed = bool(
        reveal_answers
        and identity.verified
        and identity.username
        and await asyncio.to_thread(database.access_role, identity.username) == "admin"
    )
    annotations, peer_reviews_visible = _visible_case_annotations(
        list(case.get("annotations", [])),
        assignment,
    )
    case["annotations"] = annotations
    if assignment:
        public_assignment = dict(assignment)
        public_assignment["blind_active"] = assignment.get("mode") == "blind"
        public_assignment["answers_revealed"] = answers_revealed
        public_assignment["peer_reviews_visible"] = peer_reviews_visible
        if assignment.get("mode") == "blind" and not answers_revealed:
            public_assignment["members"] = [
                {
                    "username": (
                        item["username"]
                        if identity.verified
                        and item["username"].lower() == identity.username.lower()
                        else ""
                    ),
                    "submitted": bool(item["submitted"]),
                    "assignment_kind": item["assignment_kind"],
                    "ordinal": item["ordinal"],
                }
                for item in assignment.get("members", [])
            ]
        case["review_assignment"] = public_assignment
    else:
        case["review_assignment"] = None
    for annotation in case.get("annotations", []):
        annotation["attachments"] = [
            _public_review_attachment(attachment)
            for attachment in annotation.get("attachments", [])
        ]
    scope = str(case.get("baseline_scope") or "")
    provider = media_for_issue(issue_id, scope)
    if include_media and provider is not None:
        case["assets"], case["camera"] = await resolve_case_media(provider, issue_id)
        case["media_status"] = "ready"
    else:
        case["assets"], case["camera"] = empty_case_media(issue_id)
        case["media_status"] = "pending" if provider is not None else "unavailable"
    entry = baseline_registry.by_scope(scope)
    case["baseline_id"] = entry.id if entry else ""
    case["issue_tag_suggestion"] = issue_tag_sources.lookup(
        baseline_id=case["baseline_id"],
        issue_id=issue_id,
    )
    case["voyager_issue_url"] = _voyager_issue_url(issue_id)
    case["external_links"] = _case_external_links(
        issue_id, _case_link_metadata_fallback(case)
    )
    case["trail_metadata_status"] = (
        "pending" if settings.trail_detail_metadata_enabled else "disabled"
    )
    case["batch_jobs"] = [
        _public_batch_job(job) for job in case.get("batch_jobs", [])
    ]
    return case



@router.get("/api/assets/{issue_id}/{asset_id}")
async def get_asset(issue_id: str, asset_id: str) -> FileResponse:
    case = await asyncio.to_thread(database.get_issue, issue_id)
    scope = str((case or {}).get("baseline_scope") or "")
    provider = media_for_issue(issue_id, scope)
    path = (
        await asyncio.to_thread(provider.get_asset_path, issue_id, asset_id)
        if provider
        else None
    )
    if path is None and not scope:
        path = await asyncio.to_thread(
            lambda: (
                asset_index.get_asset_path(issue_id, asset_id)
                or camera_index.get_asset_path(issue_id, asset_id)
                or video_index.get_asset_path(issue_id, asset_id)
            )
        )
    if path is None:
        raise _detail(404, "Ares / Camera 资产不存在。")
    suffix = path.suffix.lower()
    media_type = (
        "video/mp4"
        if suffix == ".mp4"
        else "image/jpeg"
        if suffix in {".jpg", ".jpeg"}
        else "image/png"
    )
    if suffix == ".mp4":
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=300, must-revalidate",
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
            },
        )
    return FileResponse(path, media_type=media_type, filename=path.name)
