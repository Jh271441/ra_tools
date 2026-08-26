from __future__ import annotations

"""Model-output labels and their compatibility with three-class RA GT."""

from typing import Any


TRIAGE_LABELS = ("误触发", "正确触发", "无需协助")
STAGE1_TRUE_STUCK_LABEL = "真实卡住"
MODEL_LABELS = (*TRIAGE_LABELS, STAGE1_TRUE_STUCK_LABEL)

_MODEL_LABEL_ALIASES = {
    "false_positive": "误触发",
    "fp": "误触发",
    "false positive": "误触发",
    "true_positive": "正确触发",
    "tp": "正确触发",
    "true positive": "正确触发",
    "no_assist": "无需协助",
    "no_assistance": "无需协助",
    "不需要协助": "无需协助",
    "不需协助": "无需协助",
    "无需远程协助": "无需协助",
    "无需远程辅助": "无需协助",
    "无需人工协助": "无需协助",
    "非误触发": STAGE1_TRUE_STUCK_LABEL,
    STAGE1_TRUE_STUCK_LABEL: STAGE1_TRUE_STUCK_LABEL,
}


def canonical_model_label(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return _MODEL_LABEL_ALIASES.get(text.lower(), text)


def model_label_matches_gt(model_label: Any, gt_label: Any) -> bool:
    """Compare a model output against three-class GT without inventing Stage2.

    Stage1 ``真实卡住`` means only that the trigger-time scene is truly stuck.
    Both three-class outcomes after that gate (``正确触发`` and ``无需协助``)
    are therefore compatible matches.
    """

    model = canonical_model_label(model_label)
    gt = str(gt_label or "").strip()
    if model not in MODEL_LABELS or gt not in TRIAGE_LABELS:
        return False
    if model == STAGE1_TRUE_STUCK_LABEL:
        return gt in {"正确触发", "无需协助"}
    return model == gt
