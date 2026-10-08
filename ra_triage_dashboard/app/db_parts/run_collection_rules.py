"""Run collection workflow: rules. Transaction ownership remains in methods."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Sequence
from .shared import LABELS, MODEL_LABELS

class RunCollectionConflictError(ValueError):
    """An optimistic revision or idempotency check failed."""


class RunRulesMixin:
    MAX_COLLECTION_RUNS = 32
    MAX_EVALUATION_ITEMS = 50000
    RUN_EVALUATION_POLICY_VERSION = "run-evaluation-v1"
    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _content_sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical_json(value).encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_collection_members(cls, members: Sequence[Any]) -> list[dict[str, Any]]:
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
            raise ValueError("Collection members 必须为数组。")
        if not members or len(members) > cls.MAX_COLLECTION_RUNS:
            raise ValueError(f"Collection 必须包含 1 到 {cls.MAX_COLLECTION_RUNS} 个 Run。")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        reference_count = 0
        for ordinal, raw in enumerate(members, 1):
            item = {"run_id": raw} if isinstance(raw, str) else raw
            if not isinstance(item, dict):
                raise ValueError(f"第 {ordinal} 个 Collection member 格式无效。")
            run_id = str(item.get("run_id") or item.get("id") or "").strip()
            if not run_id or len(run_id) > 160:
                raise ValueError(f"第 {ordinal} 个 Collection member 缺少有效 Run ID。")
            if run_id in seen:
                raise ValueError("Collection 中不能重复添加同一个 Run。")
            seen.add(run_id)
            role = str(item.get("role") or "").strip()[:48]
            is_reference = bool(item.get("is_reference", item.get("reference", False)))
            reference_count += int(is_reference)
            normalized.append({
                "ordinal": ordinal,
                "run_id": run_id,
                "role": role,
                "is_reference": is_reference,
            })
        if reference_count > 1:
            raise ValueError("Collection 最多只能标记一个参考 Run。")
        return normalized

    @staticmethod
    def _evaluation_policy(reference_type: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
        policy = {
            "version": "run-evaluation-v1",
            "label_normalization_version": "triage-labels-v1",
            "valid_reference_labels": list(LABELS),
            "valid_prediction_labels": list(MODEL_LABELS),
            "missing_predictions": "NONE; incorrect; included when any selected Run has a supported output",
            "unknown_labels": "UNKNOWN; incorrect; counted separately and not treated as a supported output",
            "exclusions": "remove issue from accuracy, confusion and transition denominators",
            "accuracy_denominator": "v1 pairwise union: valid non-excluded reference items with a supported output from at least one Collection Run",
            "supported_coverage_denominator": "all valid non-excluded reference items for each Run, including absent and UNKNOWN outputs",
            "transition_status": "P means prediction matches frozen reference; F includes missing and unknown output",
        }
        if supplied:
            if not isinstance(supplied, dict):
                raise ValueError("scoring_policy 必须是 JSON 对象。")
            if str(supplied.get("version") or policy["version"]) != policy["version"]:
                raise ValueError("不支持的 scoring_policy 版本。")
            for key, value in supplied.items():
                if key in policy and key not in {"version"} and value != policy[key]:
                    raise ValueError(f"scoring_policy 不允许覆盖已定义语义：{key}。")
                if key not in policy and key not in {"display_name", "notes", "extensions"}:
                    raise ValueError(f"scoring_policy 不支持字段：{key}。")
                if key in {"display_name", "notes", "extensions"}:
                    policy[key] = value
        return policy

    @staticmethod
    def _chunks(values: Sequence[str], size: int = 400):
        for start in range(0, len(values), size):
            yield values[start : start + size]
