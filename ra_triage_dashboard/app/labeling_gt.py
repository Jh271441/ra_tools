"""Read-only GT update queue, using the same candidates as audited GT exports."""
from __future__ import annotations
from .labeling_rules import has_label_submission


GT_CHART_BUCKETS = frozenset({"ready", "blocked", "aligned"})
LABEL_CHART_STATES = frozenset({"pending", "resolved", "conflict"})


def chart_filter_values(value: str, allowed: frozenset[str], error: str) -> set[str]:
    values = {part.strip() for part in value.split(",") if part.strip()}
    if values - allowed:
        raise ValueError(error)
    return values


def filter_label_chart_cases(items: list[dict], chart_label: str) -> list[dict]:
    states = chart_filter_values(
        chart_label, LABEL_CHART_STATES, "标注状态图表筛选无效 / Invalid labeling chart filter",
    )
    if not states:
        return items
    return [item for item in items if item.get("label_state") in states and has_label_submission(item)]


def normalize_gt_update(value: str) -> str:
    value = str(value or "").strip().lower()
    if value not in {"", "ready", "blocked"}:
        raise ValueError("GT 更新筛选不合法 / Invalid GT update filter.")
    return value


def gt_update_projection(candidate: dict) -> dict | None:
    status = candidate.get("status")
    if status == "ready":
        return {"state": "ready", "reason": "different" if candidate.get("gt_label") else "missing_gt",
                "expected_output": candidate.get("expected_output", "")}
    if status not in {"unresolved", "source_conflict"}:
        return None
    states = {source.get("state") for source in candidate.get("blocked_sources") or []}
    outputs = {source.get("expected_output") for source in candidate.get("sources") or [] if source.get("expected_output")}
    if (candidate.get("decision") or {}).get("stale") or "stale" in states:
        reason = "stale"
    elif status == "source_conflict" or "conflict" in states or len(outputs) > 1:
        reason = "conflict"
    else:
        reason = "pending"
    return {"state": "blocked", "reason": reason, "expected_output": ""}


def select_gt_update_cases(items: list[dict], candidates: list[dict], view: str = "", *, chart_gt: str = "", chart_label: str = "") -> tuple[list[dict], dict]:
    """Count submitted Issues before applying the queue view, then filter before paging.

    Empty assignments are not GT work. A task-local result never establishes
    eligibility: callers must supply globally evaluated label_gt_candidates.
    """
    view = normalize_gt_update(view)
    gt_buckets = chart_filter_values(chart_gt, GT_CHART_BUCKETS, "GT 图表筛选无效 / Invalid GT chart filter")
    by_issue = {item["issue_id"]: gt_update_projection(item) for item in candidates}
    counts = {"all": 0, "ready": 0, "blocked": 0}
    selected = []
    for item in filter_label_chart_cases(items, chart_label):
        submitted = has_label_submission(item)
        update = by_issue.get(item["issue_id"]) if submitted else None
        bucket = (update or {}).get("state", "aligned") if submitted else ""
        if gt_buckets and bucket not in gt_buckets:
            continue
        if submitted:
            counts["all"] += 1
            if update:
                counts[update["state"]] += 1
        if not view or (update and update["state"] == view):
            selected.append({**item, "gt_update": update})
    return selected, counts
