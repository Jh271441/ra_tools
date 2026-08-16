"""Fail-closed writer for the Dashboard Trail Attribute Update workflow.

The dashboard owns the review selection and audit payload, while the
``ra_auto_triage`` checkout remains the only source of Trail authentication
and transport details.  This module deliberately imports that client only
when an explicitly enabled, verified write is committed.  It never logs
tokens or the full request payload and never mutates caller-owned objects.
"""

from __future__ import annotations

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable


LABELS = ("误触发", "正确触发", "无需协助")
_LABEL_ALIASES = {
    "mismatch": "误触发",
    "match": "正确触发",
    "none": "无需协助",
    "false_positive": "误触发",
    "true_positive": "正确触发",
    "no_assist": "无需协助",
}


def normalise_model_label(value: Any) -> str:
    """Return the canonical three-class label or an empty string."""

    text = str(value or "").strip()
    if text in LABELS:
        return text
    return _LABEL_ALIASES.get(text.lower(), "")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries without mutating either argument."""

    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def build_trail_changes(
    items: Iterable[dict[str, Any]],
    *,
    current_rows: Iterable[dict[str, Any]] = (),
    result_field: str = "ra_stuck_auto_result",
    info_field: str = "ra_stuck_auto_result_info",
) -> list[dict[str, Any]]:
    """Build immutable Trail ``multi_update`` changes from a preview.

    The current info field is read from the same Trail view before commit and
    deep-merged with the Dashboard namespace.  Missing/invalid labels fail
    the whole operation before the first network request, preventing a
    partially valid batch from being written.
    """

    current_by_issue = {
        str(row.get("issue_id") or "").strip(): row
        for row in current_rows
        if str(row.get("issue_id") or "").strip()
    }
    changes: list[dict[str, Any]] = []
    for item in items:
        issue_id = str(item.get("issue_id") or "").strip()
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        label = normalise_model_label(model.get("label"))
        if not issue_id:
            raise ValueError("Trail 更新项缺少 issue_id。")
        if not label:
            raise ValueError(f"{issue_id} 的模型 label 不是三分类值，已停止提交。")
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        patch = target.get("patch") if isinstance(target.get("patch"), dict) else {}
        current = current_by_issue.get(issue_id) or {}
        current_info = _json_object(current.get(info_field))
        merged_info = deep_merge_dict(current_info, patch)
        # The JSON field is also useful outside the Dashboard namespace: keep
        # the model output in a stable, explicit object for Trail consumers.
        merged_info["model_result"] = {
            "label": label,
            "reason": str(model.get("reason") or "").strip(),
            "confidence": model.get("confidence"),
        }
        changes.append(
            {
                "issue_id": issue_id,
                result_field: label,
                info_field: merged_info,
            }
        )
    return changes


def _trail_interface_factory(ra_root: Path) -> Callable[[], Any]:
    root = str(Path(ra_root).expanduser().resolve())

    def factory() -> Any:
        if root not in sys.path:
            sys.path.insert(0, root)
        importlib.invalidate_caches()
        from utils.trail_api import TrailInterface  # type: ignore[import-not-found]

        return TrailInterface()

    return factory


def write_trail_model_results(
    changes: list[dict[str, Any]],
    *,
    ra_root: Path,
    chunk_size: int = 10,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Write model label + JSON result fields in bounded, checked chunks."""

    if not changes:
        return {
            "total": 0,
            "success_count": 0,
            "failed_count": 0,
            "failed_issue_ids": [],
            "chunks": [],
        }
    factory = client_factory or _trail_interface_factory(ra_root)
    client = factory()
    safe_size = max(1, min(50, int(chunk_size)))
    stats: dict[str, Any] = {
        "total": len(changes),
        "success_count": 0,
        "failed_count": 0,
        "failed_issue_ids": [],
        "chunks": [],
    }
    for start in range(0, len(changes), safe_size):
        chunk = changes[start : start + safe_size]
        issue_ids = [str(item["issue_id"]) for item in chunk]
        try:
            # TrailInterface currently pops issue_id/comment from its input;
            # pass a deep copy so the request remains available for audit/UI.
            response = client.update_issue_with_changes(
                deepcopy(chunk), replace=True
            )
            success = isinstance(response, dict) and response.get("msg") == "success"
            response_status = "success" if success else "failed"
        except Exception as exc:  # pragma: no cover - exercised with integration client
            success = False
            response_status = f"exception:{type(exc).__name__}"
        stats["chunks"].append(
            {"index": len(stats["chunks"]) + 1, "issue_count": len(chunk), "status": response_status}
        )
        if success:
            stats["success_count"] += len(chunk)
        else:
            stats["failed_count"] += len(chunk)
            stats["failed_issue_ids"].extend(issue_ids)
    return stats

