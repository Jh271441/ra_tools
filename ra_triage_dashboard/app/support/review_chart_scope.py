"""Match a chart's complete review population for native gallery filters."""
from typing import Sequence
from urllib.parse import parse_qsl

from ..labeling_gt import GT_CHART_BUCKETS, chart_filter_values
from ..timed_cache import TimedSingleFlightCache
from . import review_payloads
from .catalogs import _parse_issue_id_filter
from .common import _detail


_REVIEW_BUCKETS = frozenset({"pending", "in_progress", "completed"})
_SCOPE_KEYS = {
    "comparison", "model_run_id", "annotation_author", "review_status", "chart_review",
    "chart_gt", "label_state", "gt_relation", "gt_label", "model_label", "missing_evidence",
    "scene_tag", "trigger_tag", "egress_tag", "search", "comment_state", "comment_search",
    "exclusion", "work_agreement", "work_split_id", "issue_ids", "baselines", "task_view",
}
_ALL_FILTERS = {"comparison", "comment_state", "exclusion", "work_agreement"}
_chart_cache = TimedSingleFlightCache(ttl_seconds=45, max_entries=48)


def _cache_key(revision, params, scopes, ids):
    # Source pagination and chart selection do not change the base population.
    fields = tuple(sorted(
        (key, value) for key, value in params.items()
        if key in _SCOPE_KEYS - {"baselines", "task_view", "issue_ids", "chart_review", "chart_gt"}
        and value and not (key in _ALL_FILTERS and value == "all")
    ))
    return review_payloads.database, revision, tuple(sorted(scopes)), tuple(sorted(set(ids))), fields


def _take_chart_membership(payload):
    return payload.pop("_chart_gt_issue_ids"), payload.pop("_chart_review_issue_ids")


def analysis_with_chart_membership(load_payload, **params):
    # Bespoke export/legacy predicates are not present in gallery chart URLs.
    capture = not any(params.get(key) for key in ("chart_gt", "chart_review", "tag", "theme", "annotation_label", "failure_only"))
    payload = load_payload(**params, include_chart_issue_ids=capture)
    revision = payload.pop("_chart_revision", None)
    if revision is not None:
        ids = params["issue_ids"]
        if isinstance(ids, str):
            ids = _parse_issue_id_filter(ids)
        membership = _take_chart_membership(payload)
        key = _cache_key(revision, params, params["baseline_scopes"], ids)
        _chart_cache.get_or_load(key, lambda: membership)
    return payload


def chart_issue_ids(raw: str, scopes: Sequence[str], allowed_ids: Sequence[str]) -> tuple[str, ...]:
    # Task and dataset membership is enforced by the outer gallery request.
    try:
        params = dict(parse_qsl(raw, max_num_fields=len(_SCOPE_KEYS)))
        gt_buckets = chart_filter_values(
            params.pop("chart_gt", ""), GT_CHART_BUCKETS, "GT 图表筛选无效 / Invalid GT chart filter",
        )
        review_buckets = chart_filter_values(
            params.pop("chart_review", ""), _REVIEW_BUCKETS, "模型复核图表筛选无效 / Invalid model review chart filter",
        )
    except ValueError as exc:
        raise _detail(400, "图表筛选无效 / Invalid chart filter") from exc
    if params.keys() - _SCOPE_KEYS or not (gt_buckets or review_buckets):
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
    revision = review_payloads.database.change_revision()
    key = _cache_key(revision, params, scopes, ids)

    def load_membership():
        payload = review_payloads._review_reason_analysis_payload(
            **params, issue_ids=ids, baseline_scopes=scopes, include_multi_reviews=True,
            issue_ids_only=True, include_chart_issue_ids=True,
        )
        return _take_chart_membership(payload)

    gt_ids, review_ids = _chart_cache.get_or_load(key, load_membership)
    selected = [
        {issue_id for bucket in buckets for issue_id in by_bucket.get(bucket, ())}
        for buckets, by_bucket in ((gt_buckets, gt_ids), (review_buckets, review_ids))
        if buckets
    ]
    return tuple(sorted(set.intersection(*selected))) or ("__empty_chart_scope__",)
