"""Filter Parsing HTTP helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..db import LABELS, MODEL_LABELS, REVIEW_STATUSES
from ..db_parts.labeling import ISSUE_LABEL_STATE_FILTERS
from ..db_parts.model_reviews import MODEL_REVIEW_STATUSES
from ..model_labels import canonical_model_label
from ..review_analysis import COMPARISON_STATUSES
from .baselines import resolve_request_baseline_scopes
from .catalogs import (
    _csv_filter_values,
    _parse_issue_id_filter,
    resolve_review_exclusion_filter,
)
from .common import _as_text, _detail


def _case_filter_kwargs(
    *,
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
    request: Request | None = None,
) -> dict[str, Any]:
    raw_comparison_values = _csv_filter_values(comparison)
    if any(value not in COMPARISON_STATUSES for value in raw_comparison_values):
        raise _detail(400, "comparison 不在支持范围内。")
    comparison_values = [
        value
        for value in raw_comparison_values
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
        "no_gt",
        "none",
    }:
        comparison_values = []
    comparison_status = ",".join(comparison_values) if comparison_values else "all"
    if comparison_status != "all" and not model_run_id:
        raise _detail(400, "筛选模型对比关系时必须选择 Model Run。")
    model_labels = [
        canonical_model_label(value) for value in _csv_filter_values(model_label)
    ]
    for label in model_labels:
        if label not in MODEL_LABELS:
            raise _detail(400, "model_label 不在支持的三分类或 Stage1 范围内。")
    if model_labels and not model_run_id:
        raise _detail(400, "按模型标注筛选时必须选择 Model Run。")
    gt_labels = _csv_filter_values(gt_label)
    for label in gt_labels:
        if label not in LABELS:
            raise _detail(400, "gt_label 不在三分类范围内。")
    requested_statuses = _csv_filter_values(review_status)
    for status in requested_statuses:
        if status not in REVIEW_STATUSES and status not in MODEL_REVIEW_STATUSES:
            raise _detail(400, "review_status 不在支持范围内。")
    # This filter now describes Run-bound model-review state. Legacy GT-derived
    # statuses remain accepted for old links, but an overlapping "pending" is
    # interpreted in the current Run-bound domain.
    review_statuses = tuple(
        status for status in requested_statuses
        if status in REVIEW_STATUSES and status not in MODEL_REVIEW_STATUSES
    )
    model_review_statuses = tuple(
        status for status in requested_statuses if status in MODEL_REVIEW_STATUSES
    )
    raw_label_states = _csv_filter_values(label_state)
    if any(value not in {"all", *ISSUE_LABEL_STATE_FILTERS} for value in raw_label_states):
        raise _detail(400, "label_state 不在支持范围内。")
    label_states = tuple(value for value in raw_label_states if value != "all")
    exclusion_filter, is_excluded = resolve_review_exclusion_filter(exclusion)
    normalized_comment_state = _as_text(comment_state).strip().lower() or "all"
    if normalized_comment_state not in {"all", "with", "without"}:
        raise _detail(400, "comment_state 仅支持 all、with 或 without。")
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "baseline_scope": scopes[0] if len(scopes) == 1 else "",
        "baseline_scopes": scopes,
        "search": search,
        "gt_label": ",".join(gt_labels),
        "model_label": ",".join(model_labels),
        "annotation_label": annotation_label,
        "annotation_author": annotation_author,
        # Case status is derived from effective expected output versus GT in
        # the router so historical Tag-only Reviews stay aligned with analysis.
        "review_statuses": review_statuses,
        "model_review_status": ",".join(model_review_statuses),
        "label_states": label_states,
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": failure_only,
        "missing_evidence": missing_evidence,
        "issue_ids": _parse_issue_id_filter(issue_ids),
        "work_assignee": _as_text(work_assignee).strip(),
        "work_split_id": _as_text(work_split_id).strip(),
        "comment_state": normalized_comment_state,
        "is_excluded": is_excluded,
        "exclusion": exclusion_filter,
    }
