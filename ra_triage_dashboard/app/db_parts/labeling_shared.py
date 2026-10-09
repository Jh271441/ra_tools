"""Independent RA Case-labeling storage and projection helpers."""

from __future__ import annotations


import hashlib
from typing import Any, Iterable, Sequence

from .shared import LABELS


LABEL_TASK_KINDS = ("labeling", "model_review", "legacy")
ISSUE_LABEL_STATES = ("none", "pending", "resolved", "conflict", "stale")
ISSUE_LABEL_STATE_FILTERS = (
    *ISSUE_LABEL_STATES,
    "matches_gt",
    "needs_gt_review",
    "unknown",
)
ISSUE_LABEL_GT_RELATIONS = (
    "matches_gt",
    "differs_from_gt",
    "fills_missing_gt",
    "unknown",
)


def _clean_values(values: Iterable[Any]) -> list[str]:
    return sorted({str(value or "").strip() for value in values if str(value or "").strip()})


def _filter_values(value: Any) -> list[str]:
    """Normalize legacy scalar and current multi-select filter values."""

    if isinstance(value, str):
        values: Iterable[Any] = value.split(",")
    elif isinstance(value, Iterable):
        values = value
    else:
        values = ()
    return _clean_values(values)


def _source_fingerprint(values: Iterable[int]) -> str:
    payload = ",".join(str(value) for value in sorted({int(value) for value in values}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue_label_gt_relation(expected_output: Any, gt_label: Any) -> str:
    expected = str(expected_output or "").strip()
    gt = str(gt_label or "").strip()
    if expected not in LABELS:
        return "unknown"
    if gt in LABELS:
        return "matches_gt" if expected == gt else "differs_from_gt"
    if not gt:
        return "fills_missing_gt"
    return "unknown"


def _issue_decision_source_payload(
    sources: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the stable source facts an Issue-level decision is bound to."""

    payload = [
        {
            "label_case_id": str(source.get("label_case_id") or ""),
            "task_id": str(source.get("task_id") or ""),
            "state": str(source.get("state") or "pending"),
            "expected_output": str(source.get("expected_output") or ""),
            "method": str(source.get("method") or "single"),
            "assigned_count": int(source.get("assigned_count") or 0),
            "submitted_count": int(source.get("submitted_count") or 0),
            "resolution_id": source.get("resolution_id"),
            "source_revision_ids": sorted(
                int(value) for value in source.get("source_revision_ids") or []
            ),
        }
        for source in sources
        if str(source.get("label_case_id") or "")
    ]
    return sorted(payload, key=lambda item: (item["task_id"], item["label_case_id"]))


def _parse_labeling_cluster(value: Any) -> tuple[str, str] | tuple[str, str, str] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw == "adjudicated":
        return ("adjudicated", "")
    if raw.startswith("pair:"):
        gt, sep, output = raw[5:].partition("|")
        if sep and gt in LABELS and output in LABELS:
            return ("pair", gt, output)
        raise ValueError("聚类筛选不合法。")
    if raw.startswith("scenario:"):
        name = raw[9:].strip()
        if name:
            return ("scenario", name)
        raise ValueError("聚类筛选不合法。")
    raise ValueError("聚类筛选不合法。")
