from __future__ import annotations

"""Pure contracts for Manual Review expected-output handling."""

from collections.abc import Iterable, Mapping
from typing import Any


TRIAGE_LABELS = ("误触发", "正确触发", "无需协助")

EXPECTED_OUTPUT_BY_TAG_GROUP = {
    "false_trigger": "误触发",
    "ra": "正确触发",
    "no_assist": "无需协助",
}


def infer_expected_output_from_tags(
    tags: Iterable[Any],
    tag_catalog: Iterable[Mapping[str, Any]],
) -> str:
    """Infer one canonical output from the selected trigger/egress tag groups.

    ``true_trigger`` alone deliberately does not infer an output because the
    post-trigger outcome is still needed to distinguish 正确触发 from 无需协助.
    """

    selected = {str(tag or "").strip() for tag in tags if str(tag or "").strip()}
    group_by_key = {
        str(item.get("key") or "").strip(): str(
            item.get("group") or item.get("group_key") or ""
        ).strip()
        for item in tag_catalog
    }
    inferred = {
        EXPECTED_OUTPUT_BY_TAG_GROUP[group]
        for key in selected
        if (group := group_by_key.get(key)) in EXPECTED_OUTPUT_BY_TAG_GROUP
    }
    if len(inferred) > 1:
        raise ValueError(
            "Issue Tags 同时指向多个期望输出；请只保留一类："
            "误触发、正确触发或无需协助。"
        )
    return next(iter(inferred), "")


def resolve_expected_output(
    requested: Any,
    tags: Iterable[Any],
    tag_catalog: Iterable[Mapping[str, Any]],
) -> str:
    """Resolve the stored output, enforcing agreement with structured Tags."""

    normalized = str(requested or "").strip()
    if normalized and normalized not in TRIAGE_LABELS:
        raise ValueError("期望输出仅支持：误触发、正确触发、无需协助。")
    inferred = infer_expected_output_from_tags(tags, tag_catalog)
    if inferred and normalized and inferred != normalized:
        raise ValueError(
            f"期望输出“{normalized}”与 Issue Tags 推断的“{inferred}”不一致。"
        )
    return inferred or normalized


def derive_review_status(expected_output: Any, gt_label: Any) -> str:
    """Derive the persisted legacy status from expected output and baseline GT."""

    expected = str(expected_output or "").strip()
    gt = str(gt_label or "").strip()
    if not expected:
        return "pending"
    if expected != gt:
        return "needs_gt_review"
    return "reviewed"
