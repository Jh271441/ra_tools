from __future__ import annotations

from typing import Any, List, Optional, Union

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..http_support import *  # noqa: F401,F403
from ..runtime import *  # noqa: F401,F403

# Keep FastAPI symbols after star-imports (runtime/http_support may not define them).
from fastapi import APIRouter, File, Form, Request, UploadFile  # noqa: F401
from fastapi.responses import (  # noqa: F401
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

router = APIRouter()

@router.get("/api/model-runs")
async def model_runs(request: Request, baselines: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    items = await asyncio.to_thread(
        database.list_model_runs, baseline_scopes=scopes
    )
    coverage_map = await asyncio.to_thread(
        database.model_run_scope_coverage_map,
        [str(item.get("id") or "") for item in items],
    )
    items = [
        enrich_model_run_baseline_hint(
            item,
            coverage=coverage_map.get(str(item.get("id") or ""), []),
        )
        for item in items
    ]
    for item in items:
        if item.get("kind") != "upload":
            continue
        source_file = _model_source_file(item)
        filename = _model_source_filename(item)
        suffix = Path(filename).suffix.lower()
        preview_supported = suffix in {".json", ".csv", ".xlsx", ".xlsm"}
        reconstructed = (
            source_file is None
            and preview_supported
            and bool(item.get("prediction_count"))
        )
        item["source_file"] = {
            "filename": filename,
            "available": bool(source_file) or reconstructed,
            "reconstructed": reconstructed,
            "preview_supported": preview_supported,
            "preview_url": _public_path(
                f"/api/model-runs/{quote(str(item['id']), safe='')}/source-preview"
                if preview_supported
                else f"/api/model-runs/{quote(str(item['id']), safe='')}/source"
            ),
            "download_url": _public_path(
                f"/api/model-runs/{quote(str(item['id']), safe='')}/source?download=1"
            ),
        }
    return {
        "items": items,
        "default_model_run_id": database.default_model_run_id(),
    }



@router.get("/api/model-runs/{run_id}/source-preview")
async def preview_model_run_source(
    run_id: str,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    run = database.get_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    reconstructed = False
    if source_file is None:
        filename = _model_source_filename(run)
        suffix = Path(filename).suffix.lower()
        reconstructed = True
    else:
        path, filename = source_file
        suffix = path.suffix.lower()
    if suffix not in {".json", ".csv", ".xlsx", ".xlsm"}:
        raise _detail(415, "当前仅支持在页面内预览 CSV / JSON / XLSX。")
    if reconstructed:
        source_rows = database.model_run_source_rows(run_id)
        metadata = {
            "source": "dashboard_reconstructed",
            "notice": "原始文件未归档；以下内容由该 Run 已保存的脱敏预测行重建。",
        }
    else:
        try:
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                raise _detail(413, "来源文件过大，暂不生成页面预览；请使用下载。")
            content = await asyncio.to_thread(path.read_bytes)
            source_rows, metadata = parse_source_bytes(filename, content)
        except HTTPException:
            raise
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise _detail(422, f"来源文件无法生成预览：{exc}")

    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_SOURCE_PREVIEW_ROWS)
    total_rows = len(source_rows)
    page_count = max(1, math.ceil(total_rows / page_size))
    page = min(page, page_count)
    page_start = (page - 1) * page_size
    page_rows = source_rows[page_start : page_start + page_size]
    preview_rows = [
        {
            str(key): _source_preview_value(value)
            for key, value in row.items()
        }
        for row in page_rows
    ]
    columns: list[str] = []
    seen_columns: set[str] = set()
    for row in preview_rows:
        for key in row:
            if key not in seen_columns:
                seen_columns.add(key)
                columns.append(key)
    metadata_preview = {
        str(key): _source_preview_value(value)
        for key, value in (metadata.items() if isinstance(metadata, dict) else [])
    }
    return {
        "filename": filename,
        "format": suffix[1:],
        "columns": columns,
        "rows": preview_rows,
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "offset": page_start,
        "has_previous": page > 1,
        "has_next": page < page_count,
        "truncated": total_rows > len(preview_rows),
        "metadata": metadata_preview,
        "reconstructed": reconstructed,
    }



@router.get("/api/model-runs/{run_id}/source")
async def get_model_run_source(run_id: str, download: bool = False) -> Response:
    run = database.get_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    if source_file is None:
        reconstructed = _reconstructed_model_source(run_id, run)
        if reconstructed is None:
            raise _detail(404, "该 Run 的原始文件未归档且无法从已保存结果重建。")
        content, filename, media_type = reconstructed
        disposition = "attachment" if download else "inline"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Cache-Control": "private, max-age=300, must-revalidate",
                "X-Content-Type-Options": "nosniff",
                "X-RA-Source-Reconstructed": "1",
            },
        )
    path, filename = source_file
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=300, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )



@router.delete("/api/model-runs/{run_id}")
async def delete_model_run(run_id: str) -> dict[str, Any]:
    run = database.get_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    try:
        deleted = database.delete_model_run(run_id)
    except ValueError as exc:
        raise _detail(409, str(exc))
    if deleted is None:
        raise _detail(404, "模型 Run 不存在。")

    source_deleted = False
    if source_file is not None:
        path, _ = source_file
        upload_root = settings.uploads_dir.resolve()
        resolved = path.resolve()
        if upload_root == resolved or upload_root in resolved.parents:
            try:
                resolved.unlink(missing_ok=True)
                source_deleted = True
            except OSError:
                # The Run is already deleted; report the artifact separately so
                # an operator can recover a permissions/disk cleanup issue.
                source_deleted = False
    return {
        "deleted": deleted,
        "source_deleted": source_deleted,
    }



@router.post("/api/model-runs/{run_id}/default")
async def set_default_model_run(run_id: str, request: Request) -> dict[str, Any]:
    if not _can_manage_team_default(request):
        raise _detail(
            403,
            "设置团队默认 Run 需要可信 SSO 且用户名位于 "
            "DASHBOARD_TEAM_DEFAULT_MANAGERS；当前仍可在 Review 中选择任意 Run。",
        )
    run = database.set_default_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 run 不存在。")
    return {"run": run, "default_model_run_id": run_id}



@router.get("/api/review-clusters")
async def review_clusters(
    request: Request,
    model_run_id: str = "",
    failure_only: bool = True,
    annotation_author: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "items": database.review_clusters(
            baseline_scopes=scopes,
            model_run_id=model_run_id,
            failure_only=failure_only,
            annotation_author=annotation_author,
        )
    }


def _csv_filter_values(raw: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    values: list[str] = []
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        parts = raw
    else:
        parts = str(raw).split(",")
    for part in parts:
        text = _as_text(part).strip()
        if text:
            values.append(text)
    return tuple(dict.fromkeys(values))


def _review_reason_analysis_payload(
    *,
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    annotation_author: str = "",
    review_status: str = "",
    gt_label: str = "",
    annotation_label: str = "",
    model_label: str = "",
    missing_evidence: str = "",
    theme: str = "",
    tag: str = "",
    scene_tag: str = "",
    trigger_tag: str = "",
    egress_tag: str = "",
    search: str = "",
    page: int = 1,
    page_size: int = 20,
    unbounded: bool = False,
    baselines: str = "",
    baseline_scopes: list[str] | None = None,
) -> dict[str, Any]:
    missing_evidence_catalog = _missing_evidence_catalog()
    evidence_catalog = {
        str(item["key"]): {
            "label": str(item["label"]),
            "description": str(item["hint"]),
        }
        for item in missing_evidence_catalog
    }
    # Free-text keyword themes are not part of the current Review contract.
    # Ignore the retired theme parameter so old bookmarked URLs remain usable;
    # the canonical response and UI no longer expose or apply it.
    theme = ""
    # Accept multi comparison like gallery filters: mismatch,match,none or all.
    comparison_values = [
        value
        for value in _csv_filter_values(comparison)
        if value in COMPARISON_STATUSES and value != "all"
    ]
    if failure_only and comparison_values and comparison_values != ["mismatch"]:
        if comparison and set(comparison_values) != {"mismatch"}:
            raise _detail(400, "failure_only=true 与 comparison 参数冲突。")
    if failure_only and not comparison_values:
        comparison_values = ["mismatch"]
    if comparison_values and set(comparison_values) == {
        "match",
        "mismatch",
        "none",
    }:
        comparison_values = []
    comparison_status = ",".join(comparison_values) if comparison_values else "all"
    authors = _csv_filter_values(annotation_author)
    statuses = _csv_filter_values(review_status)
    gt_labels = _csv_filter_values(gt_label)
    annotation_labels = _csv_filter_values(annotation_label)
    model_labels = _csv_filter_values(model_label)
    evidence_keys = _csv_filter_values(missing_evidence)
    for status in statuses:
        if status not in REVIEW_STATUSES:
            raise _detail(400, "review_status 不在支持范围内。")
    for label in gt_labels:
        if label not in LABELS:
            raise _detail(400, "gt_label 不在三分类范围内。")
    for label in annotation_labels:
        if label not in LABELS:
            raise _detail(400, "annotation_label 不在三分类范围内。")
    for label in model_labels:
        if label not in LABELS:
            raise _detail(400, "model_label 不在三分类范围内。")
    if model_labels and not model_run_id:
        raise _detail(400, "按模型预测筛选时必须选择 Model Run。")
    for key in evidence_keys:
        if key not in evidence_catalog:
            raise _detail(400, "missing_evidence 不在稳定字段目录中。")
    tag_catalog = _review_tag_catalog()
    tag_by_key = {str(item["key"]): item for item in tag_catalog}
    scene_tags = _csv_filter_values(scene_tag)
    trigger_tags = _csv_filter_values(trigger_tag)
    egress_tags = _csv_filter_values(egress_tag)
    legacy_tags = _csv_filter_values(tag)
    for requested_tag in (*legacy_tags, *scene_tags, *trigger_tags, *egress_tags):
        item = tag_by_key.get(requested_tag)
        if item is None:
            raise _detail(400, "场景 Tags 不在共享目录中。")
    for key in scene_tags:
        if tag_by_key[key].get("section") != "scene":
            raise _detail(400, "scene_tag 必须属于场景 Tags。")
    for key in trigger_tags:
        if tag_by_key[key].get("section") != "interaction_decision":
            raise _detail(400, "trigger_tag 必须属于触发判定 Tags。")
    for key in egress_tags:
        if tag_by_key[key].get("section") != "egress":
            raise _detail(400, "egress_tag 必须属于如何脱困 Tags。")
    if comparison_status != "all" and not model_run_id:
        raise _detail(400, "筛选模型对比关系时必须选择 Model Run。")

    selected_run: dict[str, Any] | None = None
    if model_run_id:
        selected_run = next(
            (
                run
                for run in database.list_model_runs(
                    baseline_scopes=baseline_scopes
                    or resolve_request_baseline_scopes(baselines)
                )
                if run["id"] == model_run_id
            ),
            None,
        )
        if selected_run is None:
            raise _detail(404, "Model Run 不存在。")

    normalized_search = _as_text(search)[:256]
    folded_search = normalized_search.casefold()
    search_aliases = tuple(
        str(item["key"])
        for item in (*_review_tag_catalog(), *missing_evidence_catalog)
        if folded_search
        and (
            folded_search in str(item["label"]).casefold()
            or str(item["label"]).casefold() in folded_search
        )
    )
    status_labels = {
        "待复核": "pending",
        "已 Review": "reviewed",
        "GT 待复核": "needs_gt_review",
    }
    search_aliases += tuple(
        status
        for label, status in status_labels.items()
        if folded_search
        and (
            folded_search in label.casefold()
            or label.casefold() in folded_search
        )
    )
    scopes = baseline_scopes or resolve_request_baseline_scopes(baselines)
    rows = database.review_reason_rows(
        baseline_scopes=scopes,
        model_run_id=model_run_id,
        comparison_status=comparison_status,
        annotation_author=",".join(authors),
        review_status=",".join(statuses),
        gt_label=",".join(gt_labels),
        annotation_label=",".join(annotation_labels),
        model_label=",".join(model_labels),
        missing_evidence=list(evidence_keys),
        tag_filters=legacy_tags,
        scene_tags=scene_tags,
        trigger_tags=trigger_tags,
        egress_tags=egress_tags,
        search=normalized_search,
        search_aliases=search_aliases,
    )
    tag_catalog_for_analysis = {
        str(item["key"]): {
            "label": str(item["label"]),
            "description": str(item.get("hint") or item.get("description") or ""),
            "section": str(item.get("section") or ""),
            "group": str(item.get("group") or ""),
        }
        for item in tag_catalog
    }
    result = build_review_reason_analysis(
        rows,
        theme="",
        evidence_catalog=evidence_catalog,
        tag_catalog=tag_catalog_for_analysis,
        has_model_run=bool(model_run_id),
        include_reason_themes=False,
        page=page,
        page_size=max(len(rows), 1) if unbounded else page_size,
        page_size_limit=None if unbounded else 200,
    )
    for item in result["items"]:
        issue_id = _as_text(item.get("issue_id"))
        review_params = [f"issue={quote(issue_id, safe='')}"]
        if model_run_id:
            review_params.append(f"run={quote(model_run_id, safe='')}")
        if comparison_status == "mismatch" and model_run_id:
            review_params.append("failure=1")
        item["voyager_issue_url"] = _voyager_issue_url(issue_id)
        item["review_url"] = _public_path(f"/review?{'&'.join(review_params)}")
    result["scope"] = {
        "baseline_scope": settings.baseline_scope,
        "model_run": (
            {
                "id": selected_run["id"],
                "name": selected_run["name"],
                "kind": selected_run["kind"],
                "prediction_count": selected_run["baseline_prediction_count"],
                "failure_count": selected_run["failure_count"],
            }
            if selected_run
            else None
        ),
        "comparison_status": comparison_status,
        "failure_only": comparison_status == "mismatch",
        "review_binding": (
            "latest_annotation_per_issue_per_model_run"
            if model_run_id
            else "latest_annotation_per_issue_all_runs"
        ),
        "review_is_run_bound": bool(model_run_id),
    }
    result["filters"] = {
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": comparison_status == "mismatch",
        "annotation_author": list(authors),
        "review_status": list(statuses),
        "gt_label": list(gt_labels),
        "annotation_label": list(annotation_labels),
        "model_label": list(model_labels),
        "missing_evidence": list(evidence_keys),
        "theme": theme,
        "tag": list(legacy_tags),
        "scene_tag": list(scene_tags),
        "trigger_tag": list(trigger_tags),
        "egress_tag": list(egress_tags),
        "search": normalized_search,
    }
    return result
