from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime
from typing import Any
from urllib.parse import quote

import openpyxl
from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..db import LABELS, MODEL_LABELS
from ..auth import request_identity
from ..runtime import _public_path, database, settings
from ..support.baselines import (
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..support.catalogs import (
    _missing_evidence_catalog,
    _review_tag_catalog,
)
from ..support.common import (
    _as_text,
    _detail,
)
from ..support.review_payloads import (
    _review_reason_analysis_payload,
)
from ..support.filter_parsing import _case_filter_kwargs
from ..support.external_links import _voyager_issue_url
from .cases import _case_issue_ids_with_status_filter

router = APIRouter()

@router.get("/api/review-reason-analysis")
async def review_reason_analysis(
    request: Request,
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
    issue_ids: str = "",
    search: str = "",
    comment_state: str = "all",
    comment_search: str = "",
    exclusion: str = "all",
    page: int = 1,
    page_size: int = 20,
    baselines: str = "",
    work_agreement: str = "all",
    work_split_id: str = "",
) -> dict[str, Any]:
    # Multi-review analysis is read-only.  Blind mode isolates each user's
    # writes, but does not restrict submitted Review history or aggregate
    # filters to administrators; every Dashboard visitor should see the same
    # conflict/agreement projection for a shared dataset.
    include_multi_reviews = True
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    payload = await asyncio.to_thread(
        _review_reason_analysis_payload,
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        annotation_author=annotation_author,
        review_status=review_status,
        gt_label=gt_label,
        annotation_label=annotation_label,
        model_label=model_label,
        missing_evidence=missing_evidence,
        theme=theme,
        tag=tag,
        scene_tag=scene_tag,
        trigger_tag=trigger_tag,
        egress_tag=egress_tag,
        issue_ids=issue_ids,
        search=search,
        comment_state=comment_state,
        comment_search=comment_search,
        exclusion=exclusion,
        page=page,
        page_size=page_size,
        baselines=baselines,
        baseline_scopes=scopes,
        work_agreement=work_agreement,
        work_split_id=work_split_id,
        include_multi_reviews=include_multi_reviews,
    )
    payload["baselines"] = resolve_request_baseline_ids(baselines, request=request)
    payload["baseline_scopes"] = scopes
    return payload


@router.get("/api/model-review-facets")
async def model_review_facets(
    request: Request, model_run_id: str, baselines: str = ""
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    result = await asyncio.to_thread(
        database.model_review_facets,
        model_run_id=_as_text(model_run_id),
        baseline_scopes=scopes,
    )
    result["baseline_scopes"] = scopes
    return result


@router.get("/api/model-review-shadow-comparison")
async def model_review_shadow_comparison(
    request: Request, model_run_id: str, baselines: str = ""
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    result = await asyncio.to_thread(
        database.model_review_shadow_comparison,
        model_run_id=_as_text(model_run_id),
        baseline_scopes=scopes,
    )
    result["baseline_scopes"] = scopes
    return result


REVIEW_ANALYSIS_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("issue_id", "Issue ID"),
    ("scene", "场景"),
    ("gt_label", "GT"),
    ("model_label", "模型结论"),
    ("comparison_status", "模型判断结果"),
    ("model_reason", "模型说明"),
    ("model_confidence", "模型置信度"),
    ("expected_output", "期望输出"),
    ("review_status", "Issue GT Review状态"),
    ("model_review_status", "模型判错复核状态"),
    ("review_domain", "Review 数据域"),
    ("is_excluded", "应该排除"),
    ("review_reason", "人工 Review 原因"),
    ("tags", "场景 Tags"),
    ("scene_tags", "场景 Tags（环境/意图）"),
    ("trigger_tags", "触发判定 Tags"),
    ("egress_tags", "脱困方式 Tags"),
    ("other_tags", "其他 Tags"),
    ("tag_details", "Tags 详细归类"),
    ("tag_keys", "Tags 原始 key"),
    ("missing_evidence", "缺失信息"),
    ("missing_evidence_keys", "缺失信息原始 key"),
    ("reviewer", "复核人"),
    ("reviewed_at", "Review 时间"),
    ("review_model_run_id", "Review Model Run"),
    ("review_work_split_id", "Review 盲标 Split"),
    ("review_url", "Workbench 链接"),
    ("voyager_issue_url", "Voyager Issue 链接"),
)


def _spreadsheet_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
        ("=", "+", "-", "@")
    ):
        return f"'{value}"
    return value


def _review_analysis_export_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    tag_catalog = {
        str(item["key"]): item for item in _review_tag_catalog()
    }
    evidence_labels = {
        str(item["key"]): str(item.get("label") or item["key"])
        for item in _missing_evidence_catalog()
    }

    section_labels = {
        "scene": "scene",
        "interaction_decision": "trigger",
        "egress": "egress",
    }
    section_titles = {
        "scene": "场景",
        "trigger": "触发判定",
        "egress": "脱困方式",
        "other": "其他",
    }
    group_titles = {
        "environment": "环境",
        "self_intent": "自车意图",
        "false_trigger": "误触发",
        "true_trigger": "应该触发",
        "ra": "正确触发",
        "no_assist": "无需协助",
    }

    def tag_label(key: Any) -> str:
        text = _as_text(key)
        item = tag_catalog.get(text) or {}
        return _as_text(item.get("label")) or text

    def tag_section(key: Any) -> str:
        item = tag_catalog.get(_as_text(key)) or {}
        return section_labels.get(_as_text(item.get("section")), "other")

    def tag_values(annotation: dict[str, Any]) -> list[str]:
        raw = annotation.get("tags") or []
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        return [_as_text(value) for value in raw if _as_text(value)]

    def joined_tag_labels(keys: list[str], section: str | None = None) -> str:
        selected = [key for key in keys if section is None or tag_section(key) == section]
        return "、".join(tag_label(key) for key in selected)

    def tag_details(keys: list[str]) -> str:
        details: list[str] = []
        for key in keys:
            item = tag_catalog.get(key) or {}
            section = tag_section(key)
            group = _as_text(item.get("group"))
            prefix = section_titles.get(section, "其他")
            if group_titles.get(group):
                prefix = f"{prefix}/{group_titles[group]}"
            details.append(f"{prefix}={tag_label(key)}")
        return "；".join(details)

    exported: list[dict[str, Any]] = []
    for item in result.get("items", []):
        annotation = item.get("annotation") or {}
        prediction = item.get("prediction") or {}
        tag_keys = tag_values(annotation)
        evidence_keys = [
            _as_text(key)
            for key in (annotation.get("missing_evidence") or [])
            if _as_text(key)
        ]
        expected_output = _as_text(
            annotation.get("expected_output") or annotation.get("label")
        )
        exported.append(
            {
                "issue_id": _as_text(item.get("issue_id")),
                "scene": _as_text(item.get("title") or item.get("scenario")),
                "gt_label": _as_text(item.get("gt_label")),
                "model_label": _as_text(prediction.get("label")),
                "comparison_status": _as_text(item.get("comparison_status")).upper(),
                "model_reason": _as_text(prediction.get("reason")),
                "model_confidence": prediction.get("confidence"),
                "expected_output": expected_output,
                "review_status": _as_text(annotation.get("review_status")),
                "model_review_status": _as_text(
                    annotation.get("model_review_status")
                ),
                "review_domain": _as_text(annotation.get("review_domain")) or "legacy",
                "is_excluded": "是" if bool(annotation.get("is_excluded")) else "否",
                "review_reason": _as_text(annotation.get("note")),
                "tags": "、".join(tag_label(key) for key in tag_keys),
                "scene_tags": joined_tag_labels(tag_keys, "scene"),
                "trigger_tags": joined_tag_labels(tag_keys, "trigger"),
                "egress_tags": joined_tag_labels(tag_keys, "egress"),
                "other_tags": joined_tag_labels(tag_keys, "other"),
                "tag_details": tag_details(tag_keys),
                "tag_keys": "、".join(tag_keys),
                "missing_evidence": "、".join(
                    evidence_labels.get(key, key) for key in evidence_keys
                ),
                "missing_evidence_keys": "、".join(evidence_keys),
                "reviewer": _as_text(annotation.get("author")),
                "reviewed_at": _as_text(annotation.get("created_at")),
                "review_model_run_id": _as_text(annotation.get("model_run_id")),
                "review_work_split_id": _as_text(annotation.get("work_split_id")),
                "review_url": _as_text(item.get("review_url")),
                "voyager_issue_url": _as_text(item.get("voyager_issue_url")),
            }
        )
    return exported


def _gallery_export_fallback_item(item: dict[str, Any], model_run_id: str) -> dict[str, Any]:
    """Adapt an unreviewed Gallery row to the shared Review-export schema."""

    public = dict(item)
    issue_id = _as_text(public.get("issue_id"))
    prediction = public.get("prediction") or {}
    model_label = _as_text(prediction.get("label"))
    gt_label = _as_text(public.get("gt_label"))
    if model_label not in MODEL_LABELS:
        comparison_status = "none"
    elif gt_label not in LABELS:
        comparison_status = "no_gt"
    elif bool(prediction.get("mismatch")):
        comparison_status = "mismatch"
    else:
        comparison_status = "match"
    review_params = [f"issue={quote(issue_id, safe='')}"]
    if model_run_id:
        review_params.append(f"run={quote(model_run_id, safe='')}")
    public["comparison_status"] = comparison_status
    public["review_url"] = _public_path(f"/review?{'&'.join(review_params)}")
    public["voyager_issue_url"] = _voyager_issue_url(issue_id)
    return public


def _trail_expected_output_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    """Return only GT-changing rows accepted by 张扬's expected-output mode."""

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in result.get("items", []):
        annotation = item.get("annotation") or {}
        issue_id = _as_text(item.get("issue_id"))
        expected_output = _as_text(
            annotation.get("expected_output") or annotation.get("label")
        )
        gt_label = _as_text(item.get("gt_label"))
        if (
            not issue_id
            or issue_id in seen
            or expected_output not in LABELS
            or expected_output == gt_label
        ):
            continue
        seen.add(issue_id)
        rows.append({"issue_id": issue_id, "期望输出": expected_output})
    return rows


def _review_analysis_export_response(
    result: dict[str, Any], export_format: str
) -> Response:
    if export_format == "trail_xlsx":
        rows = _trail_expected_output_rows(result)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "GT 更新"
        worksheet.append(["issue_id", "期望输出"])
        for row in rows:
            worksheet.append(
                [
                    _spreadsheet_safe(row["issue_id"]),
                    _spreadsheet_safe(row["期望输出"]),
                ]
            )
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        worksheet.column_dimensions["A"].width = 24
        worksheet.column_dimensions["B"].width = 16
        output = io.BytesIO()
        workbook.save(output)
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="gt-update-{timestamp}.xlsx"'
                )
            },
        )

    rows = _review_analysis_export_rows(result)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"review-analysis-{timestamp}.{export_format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    column_keys = [key for key, _ in REVIEW_ANALYSIS_EXPORT_COLUMNS]
    column_labels = [label for _, label in REVIEW_ANALYSIS_EXPORT_COLUMNS]
    if export_format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(column_labels)
        for row in rows:
            writer.writerow([_spreadsheet_safe(row.get(key)) for key in column_keys])
        return Response(
            content=("\ufeff" + stream.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Review 分析"
    worksheet.append(column_labels)
    for row in rows:
        worksheet.append([_spreadsheet_safe(row.get(key)) for key in column_keys])
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for index, (_, label) in enumerate(REVIEW_ANALYSIS_EXPORT_COLUMNS, start=1):
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = min(
            42, max(12, len(label) * 2 + 4)
        )
    output = io.BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )



@router.get("/api/review-reason-analysis/export")
async def export_review_reason_analysis(
    request: Request,
    format: str = "csv",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    annotation_author: str = "",
    review_status: str = "",
    label_state: str = "",
    gt_label: str = "",
    annotation_label: str = "",
    model_label: str = "",
    missing_evidence: str = "",
    theme: str = "",
    tag: str = "",
    scene_tag: str = "",
    trigger_tag: str = "",
    egress_tag: str = "",
    issue_ids: str = "",
    search: str = "",
    comment_state: str = "all",
    comment_search: str = "",
    exclusion: str = "all",
    baselines: str = "",
    work_agreement: str = "all",
    work_split_id: str = "",
    gallery_scope: bool = False,
    work_assignee: str = "",
) -> Response:
    # Every export format uses the same current Review projection. Once the
    # active blind Split has at least one submission it takes precedence over
    # an older ordinary Review; an untouched Split still falls back to the
    # ordinary stream. This also lets GT-update exports include partial blind
    # progress without duplicating or silently preferring stale single-review
    # history.
    include_multi_reviews = True
    export_format = _as_text(format).strip().lower()
    if export_format not in {"csv", "xlsx", "trail_xlsx"}:
        raise _detail(400, "format 仅支持 csv、xlsx 或 trail_xlsx。")
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    export_issue_ids: str | list[str] = issue_ids
    export_search = search
    export_comment_state = comment_state
    gallery_items: list[dict[str, Any]] = []
    if gallery_scope:
        case_filters = _case_filter_kwargs(
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
        review_statuses = tuple(case_filters.pop("review_statuses", ()))
        label_states = tuple(case_filters.pop("label_states", ()))
        case_filters.pop("exclusion", None)
        identity = await asyncio.to_thread(request_identity, request, settings)
        case_filters["preferred_annotation_author"] = (
            identity.username if identity.verified and identity.username else ""
        )
        export_issue_ids = await asyncio.to_thread(
            _case_issue_ids_with_status_filter,
            filters=case_filters,
            review_statuses=review_statuses,
            label_states=label_states,
        )
        # Membership has already been resolved with the Gallery's exact search,
        # discussion, exclusion and assignee semantics. Avoid applying the
        # analysis page's different free-text/comment projection a second time.
        export_search = ""
        export_comment_state = "all"
        if not export_issue_ids:
            return await asyncio.to_thread(
                _review_analysis_export_response, {"items": []}, export_format
            )
        for offset in range(0, len(export_issue_ids), 400):
            issue_batch = export_issue_ids[offset : offset + 400]
            gallery_case_filters = {**case_filters, "issue_ids": issue_batch}
            gallery_result = await asyncio.to_thread(
                database.list_cases,
                **gallery_case_filters,
                page=1,
                page_size=len(issue_batch),
            )
            gallery_items.extend(gallery_result.get("items") or [])
    result = await asyncio.to_thread(
        _review_reason_analysis_payload,
        model_run_id=model_run_id,
        comparison=comparison,
        failure_only=failure_only,
        annotation_author=annotation_author,
        review_status=review_status,
        gt_label=gt_label,
        annotation_label=annotation_label,
        model_label=model_label,
        missing_evidence=missing_evidence,
        theme=theme,
        tag=tag,
        scene_tag=scene_tag,
        trigger_tag=trigger_tag,
        egress_tag=egress_tag,
        issue_ids=export_issue_ids,
        search=export_search,
        comment_state=export_comment_state,
        comment_search=comment_search,
        exclusion=exclusion,
        unbounded=True,
        baselines=baselines,
        baseline_scopes=scopes,
        work_agreement=work_agreement,
        work_split_id=work_split_id,
        include_multi_reviews=include_multi_reviews,
    )
    if gallery_scope:
        exported_issue_ids = {
            _as_text(item.get("issue_id")) for item in result.get("items", [])
        }
        result.setdefault("items", []).extend(
            _gallery_export_fallback_item(item, model_run_id)
            for item in gallery_items
            if _as_text(item.get("issue_id")) not in exported_issue_ids
        )
        result["items"].sort(key=lambda item: _as_text(item.get("issue_id")))
    result["baselines"] = resolve_request_baseline_ids(baselines, request=request)
    return await asyncio.to_thread(
        _review_analysis_export_response, result, export_format
    )
