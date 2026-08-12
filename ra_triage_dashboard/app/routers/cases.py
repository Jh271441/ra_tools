from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from ..contracts import ISSUE_ID_RE
from ..http_support import (
    _admin_identity,
    _as_text,
    _case_external_links,
    _case_filter_kwargs,
    _case_link_metadata_fallback,
    _create_annotation_record,
    _detail,
    _public_batch_job,
    _public_path,
    _public_review_attachment,
    _render_case_thumbnail,
    _review_tag_catalog,
    _store_review_attachments,
    _thumbnail_cache_path,
    _voyager_issue_url,
    media_for_issue,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..review_workflow import derive_review_status, effective_expected_output
from ..runtime import (
    asset_index,
    baseline_registry,
    camera_index,
    database,
    logger,
    settings,
    trail_detail_semaphore,
    video_index,
)
from ..trail_sync import read_trail_issue_metadata
from ..work_split import distribute_issue_ids

router = APIRouter()

# issue_id -> (source_path, mtime_ns, size, dest_jpeg)
_thumbnail_dest_cache: dict[str, tuple[str, int, int, Path]] = {}
_thumbnail_encode_gate = threading.Semaphore(8)


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

    info = None
    provider = media_for_issue(issue_id, "")
    if provider is not None:
        info = provider.get_thumbnail_source(issue_id)
    if not info:
        info = asset_index.get_thumbnail_source(issue_id)
    if not info or not isinstance(info.get("path"), Path):
        # Fall back to case baseline only when default media misses (e.g. 0626).
        case = database.get_case(issue_id)
        if case is None:
            return None
        provider = media_for_issue(
            issue_id, str(case.get("baseline_scope") or "")
        )
        if provider is not None:
            info = provider.get_thumbnail_source(issue_id)
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


def _case_result_with_status_filter(
    *,
    filters: dict[str, Any],
    review_statuses: tuple[str, ...],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Filter after read-time Tag inference, then paginate the exact slice."""

    tag_catalog = _review_tag_catalog()
    if review_statuses:
        raw = database.list_cases(**filters, page=1, page_size=5000)
        allowed = set(review_statuses)
        items = [
            normalized
            for item in raw.get("items", [])
            if (
                normalized := _with_effective_case_review_status(
                    item, tag_catalog
                )
            )["annotation"]["review_status"]
            in allowed
        ]
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": len(items),
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
    return result


def _case_issue_ids_with_status_filter(
    *,
    filters: dict[str, Any],
    review_statuses: tuple[str, ...],
) -> list[str]:
    if not review_statuses:
        return database.list_case_issue_ids(**filters, limit=5000)
    result = _case_result_with_status_filter(
        filters=filters,
        review_statuses=review_statuses,
        page=1,
        page_size=5000,
    )
    return [str(item.get("issue_id") or "") for item in result["items"]]


def _load_case_media(provider: Any, issue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve all filesystem-backed media for one issue on a worker thread."""

    assets = provider.get_assets(issue_id)
    captured_video = provider.get_video(issue_id)
    if captured_video is not None:
        assets["video"] = captured_video
        assets["available"] = True
    camera = provider.get_camera_assets(
        issue_id,
        (assets.get("capture") or {}).get("timestamp_ms"),
    )
    return assets, camera


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
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
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
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        issue_ids=issue_ids,
        work_assignee=work_assignee,
        baselines=baselines,
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    comparison_status = filters["comparison_status"]
    safe_page = max(1, int(page))
    safe_page_size = min(max(1, int(page_size)), 100)
    result = await asyncio.to_thread(
        _case_result_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
        page=safe_page,
        page_size=safe_page_size,
    )
    result["items"] = await asyncio.to_thread(
        _public_case_items,
        result.get("items", []),
        include_thumbnail=include_thumbnail,
    )
    result["filters"] = {
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": comparison_status == "mismatch",
        "issue_ids": filters["issue_ids"],
        "work_assignee": filters["work_assignee"],
        "review_status": list(review_statuses),
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
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
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
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        issue_ids=issue_ids,
        work_assignee=work_assignee,
        baselines=baselines,
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    ids = await asyncio.to_thread(
        _case_issue_ids_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
    )
    return {
        "issue_ids": ids,
        "total": len(ids),
        "truncated": len(ids) >= 5000,
        "filters": {
            "model_run_id": model_run_id,
            "comparison_status": filters["comparison_status"],
            "failure_only": filters["comparison_status"] == "mismatch",
            "issue_ids": filters["issue_ids"],
            "work_assignee": filters["work_assignee"],
            "review_status": list(review_statuses),
        },
    }

@router.get("/api/work-assignees")
async def work_assignees() -> dict[str, Any]:
    """Assignees currently attached to Issues via work-split."""

    return {
        "items": await asyncio.to_thread(database.list_work_assignees),
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
        model_run_id=_as_text(filter_body.get("model_run_id")),
        comparison=_as_text(filter_body.get("comparison") or filter_body.get("comparison_status")),
        failure_only=bool(filter_body.get("failure_only")),
        missing_evidence=_as_text(filter_body.get("missing_evidence")),
        issue_ids=_as_text(filter_body.get("issue_ids")),
        work_assignee=_as_text(filter_body.get("work_assignee")),
        baselines=_as_text(filter_body.get("baselines") or filter_body.get("baseline_scopes")),
        request=request,
    )
    review_statuses = tuple(filters.pop("review_statuses", ()))
    issue_ids = await asyncio.to_thread(
        _case_issue_ids_with_status_filter,
        filters=filters,
        review_statuses=review_statuses,
    )
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
        assignments = distribute_issue_ids(issue_ids, assignees, seed=seed)
        saved = await asyncio.to_thread(
            database.apply_work_split,
            assignments=assignments,
            created_by=identity.username,
            seed=seed,
            filter_snapshot={
                "model_run_id": filters["model_run_id"],
                "comparison_status": filters["comparison_status"],
                "search": filters["search"],
                "gt_label": filters["gt_label"],
                "model_label": filters["model_label"],
                "annotation_author": filters["annotation_author"],
                "review_status": list(review_statuses),
                "missing_evidence": filters["missing_evidence"],
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
        "truncated": len(issue_ids) >= 5000,
        "seed": seed,
        "split_id": saved["split_id"],
        "created_by": saved["created_by"],
        "created_at": saved["created_at"],
        "assignments": assignments,
        "work_assignees": await asyncio.to_thread(database.list_work_assignees),
        "change_revision": await asyncio.to_thread(database.change_revision),
        "filters": {
            "model_run_id": filters["model_run_id"],
            "comparison_status": filters["comparison_status"],
            "failure_only": filters["comparison_status"] == "mismatch",
            "work_assignee": filters["work_assignee"],
            "review_status": list(review_statuses),
        },
    }



@router.get("/api/reviewers")
async def reviewers(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "items": await asyncio.to_thread(
            database.list_reviewers,
            baseline_scopes=scopes,
            model_run_id=model_run_id,
        )
    }



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

    case = await asyncio.to_thread(database.get_case, issue_id)
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

    return {
        "issue_id": issue_id,
        "status": status,
        "external_links": _case_external_links(issue_id, trail_metadata),
    }



@router.get("/api/cases/{issue_id}")
async def get_case(issue_id: str) -> dict[str, Any]:
    case = await asyncio.to_thread(database.get_case, issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    for annotation in case.get("annotations", []):
        annotation["attachments"] = [
            _public_review_attachment(attachment)
            for attachment in annotation.get("attachments", [])
        ]
    scope = str(case.get("baseline_scope") or "")
    provider = media_for_issue(issue_id, scope)
    if provider is None:
        case["assets"] = {"available": False, "issue_id": issue_id, "frames": [], "capture": {}}
        case["camera"] = {"available": False, "issue_id": issue_id, "frames": [], "capture": {}}
    else:
        case["assets"], case["camera"] = await asyncio.to_thread(
            _load_case_media,
            provider,
            issue_id,
        )
    entry = baseline_registry.by_scope(scope)
    case["baseline_id"] = entry.id if entry else ""
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
    case = await asyncio.to_thread(database.get_case, issue_id)
    scope = str((case or {}).get("baseline_scope") or "")
    provider = media_for_issue(issue_id, scope)
    path = (
        await asyncio.to_thread(provider.get_asset_path, issue_id, asset_id)
        if provider
        else None
    )
    if path is None:
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



@router.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    if await asyncio.to_thread(database.get_case, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    annotation = await asyncio.to_thread(
        _create_annotation_record,
        issue_id=issue_id,
        request=request,
        body=body,
    )
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
    if await asyncio.to_thread(database.get_case, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _detail(400, "payload 必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "payload 必须是 JSON 对象。")
    records, paths = await _store_review_attachments(attachments or [])
    try:
        annotation = await asyncio.to_thread(
            _create_annotation_record,
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
    return {
        "annotation": annotation,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.delete("/api/cases/{issue_id}/annotations/{annotation_id}")
async def delete_annotation(issue_id: str, annotation_id: int) -> dict[str, Any]:
    if annotation_id <= 0:
        raise _detail(400, "Review 版本 ID 不合法。")
    deleted = await asyncio.to_thread(
        database.delete_annotation,
        issue_id=issue_id,
        annotation_id=annotation_id,
    )
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
