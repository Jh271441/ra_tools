"""Review Payloads HTTP helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..db import LABELS, MODEL_LABELS, REVIEW_STATUSES
from ..model_labels import canonical_model_label
from ..review_analysis import COMPARISON_STATUSES, build_review_reason_analysis
from ..runtime import _public_path, database, settings
from .baselines import resolve_request_baseline_scopes
from .catalogs import (
    _csv_filter_values,
    _missing_evidence_catalog,
    _review_tag_catalog,
    resolve_review_exclusion_filter,
)
from .common import _as_text, _detail
from .external_links import _voyager_issue_url


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
    exclusion: str = "all",
    page: int = 1,
    page_size: int = 20,
    unbounded: bool = False,
    baselines: str = "",
    baseline_scopes: list[str] | None = None,
) -> dict[str, Any]:
    exclusion, is_excluded = resolve_review_exclusion_filter(exclusion)
    missing_evidence_catalog = _missing_evidence_catalog()
    evidence_catalog = {
        str(item["key"]): {
            "label": str(item["label"]),
            "description": str(item["hint"]),
        }
        for item in missing_evidence_catalog
    }
    # Free-text keyword themes are not part of the current Review contract.
    # Ignore the retired theme parameter so old bookmarked URLs remain usable.
    theme = ""
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
    model_labels = [
        canonical_model_label(value) for value in _csv_filter_values(model_label)
    ]
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
        if label not in MODEL_LABELS:
            raise _detail(400, "model_label 不在支持的三分类或 Stage1 范围内。")
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
        if requested_tag not in tag_by_key:
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
        selected_run = database.model_run_with_scope_counts(
            model_run_id,
            baseline_scopes=baseline_scopes
            or resolve_request_baseline_scopes(baselines),
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
        "待补充": "pending",
        "与 GT 一致": "reviewed",
        "GT 需复核": "needs_gt_review",
        "Pending": "pending",
        "Matches GT": "reviewed",
        "Needs GT review": "needs_gt_review",
    }
    search_statuses = tuple(
        status
        for label, status in status_labels.items()
        if folded_search
        and (
            folded_search in label.casefold()
            or label.casefold() in folded_search
        )
    )
    effective_statuses = tuple(statuses)
    status_filter_impossible = False
    if search_statuses:
        search_status_set = set(search_statuses)
        if effective_statuses:
            effective_statuses = tuple(
                status
                for status in effective_statuses
                if status in search_status_set
            )
            status_filter_impossible = not effective_statuses
        else:
            effective_statuses = tuple(dict.fromkeys(search_statuses))
    scopes = baseline_scopes or resolve_request_baseline_scopes(baselines)
    rows = []
    if not status_filter_impossible:
        rows = database.review_reason_rows(
            baseline_scopes=scopes,
            model_run_id=model_run_id,
            comparison_status=comparison_status,
            # Reason clustering is a read-only progress/analysis surface.
            # Pre-Run Review history remains useful human evidence when no
            # selected-Run Review exists for the Issue. The selected Run
            # always wins inside the DB join; a prior bound Review is then
            # reusable human evidence. Trail candidate generation keeps its
            # strict default and never receives this compatibility view.
            include_unbound_fallback=True,
            include_bound_history_fallback=True,
            # Keep the exclusion slice at the DB boundary so cards, charts,
            # detail rows, and all analysis exports agree.  ``None`` means
            # the default all-inclusive view.
            is_excluded=is_excluded,
            annotation_author=",".join(authors),
            # Historical persisted status/label fields predate expected output.
            # Apply both filters after read-time Tag inference below.
            review_status="",
            gt_label=",".join(gt_labels),
            annotation_label="",
            model_label=",".join(model_labels),
            missing_evidence=list(evidence_keys),
            tag_filters=legacy_tags,
            scene_tags=scene_tags,
            trigger_tags=trigger_tags,
            egress_tags=egress_tags,
            # Exact automatic-status searches are evaluated from the same
            # derived value as the dedicated filter instead of stale storage.
            search="" if search_statuses else normalized_search,
            search_aliases=() if search_statuses else search_aliases,
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
        is_excluded=is_excluded,
        review_statuses=effective_statuses,
        annotation_labels=annotation_labels,
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
        "exclusion": exclusion,
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
        "exclusion": exclusion,
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
