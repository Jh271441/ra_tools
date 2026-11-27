"""Match a chart's complete review population for native gallery filters."""
from urllib.parse import parse_qsl

from .catalogs import _parse_issue_id_filter
from .common import _detail
from .review_payloads import _review_reason_analysis_payload


def chart_issue_ids(raw, scopes, allowed_ids):
    # Task and dataset membership is enforced by the outer gallery request.
    keys = {
        "comparison", "model_run_id", "annotation_author", "review_status", "chart_review",
        "chart_gt", "label_state", "gt_relation", "gt_label", "model_label", "missing_evidence",
        "scene_tag", "trigger_tag", "egress_tag", "search", "comment_state", "comment_search",
        "exclusion", "work_agreement", "work_split_id", "issue_ids", "baselines", "task_view",
    }
    try:
        params = dict(parse_qsl(raw, max_num_fields=len(keys)))
    except ValueError as exc:
        raise _detail(400, "图表筛选无效 / Invalid chart filter") from exc
    if params.keys() - keys or not (params.get("chart_gt") or params.get("chart_review")):
        raise _detail(400, "图表筛选无效 / Invalid chart filter")
    params.pop("task_view", None)
    params.pop("baselines", None)
    raw_ids = params.pop("issue_ids", "")
    ids = _parse_issue_id_filter(raw_ids)
    if raw_ids and not ids:
        raise _detail(400, "Issue ID 筛选无效 / Invalid Issue ID filter")
    if allowed_ids:
        ids = sorted(set(allowed_ids).intersection(ids)) if ids else allowed_ids
        if not ids:
            return ("__empty_chart_scope__",)
    result = _review_reason_analysis_payload(
        **params, issue_ids=ids, baseline_scopes=scopes, include_multi_reviews=True, issue_ids_only=True,
    )
    return tuple(result["issue_ids"]) or ("__empty_chart_scope__",)
