"""Shared task visibility rules; historical records remain intact."""
from __future__ import annotations
from typing import Any, Sequence

TERMINAL_TASK_LIFECYCLES = ("superseded", "cancelled")
TASK_LIFECYCLE_FILTERS = {"current", "history", "all", "draft", "active", "closed", *TERMINAL_TASK_LIFECYCLES}

def normalize_task_lifecycle(value: str = "current") -> str:
    mode = str(value or "current").strip().lower()
    if mode not in TASK_LIFECYCLE_FILTERS:
        raise ValueError("任务生命周期筛选不合法。")
    return mode

def task_lifecycle_where(value: str = "current") -> tuple[str, list[Any]]:
    mode = normalize_task_lifecycle(value)
    column = "COALESCE(split.lifecycle, 'active')"
    if mode == "all":
        return "1 = 1", []
    if mode in {"current", "history"}:
        operator = "NOT IN" if mode == "current" else "IN"
        return f"{column} {operator} (?, ?)", list(TERMINAL_TASK_LIFECYCLES)
    return f"{column} = ?", [mode]

def task_reviewable(row: Any) -> bool:
    return str(row["lifecycle"] or "active") == "active" and not bool(row["legacy_read_only"])

def task_list_metrics(items: Sequence[dict[str, Any]], assignee: str = "") -> dict[str, int]:
    actor = str(assignee or "").strip().lower()
    metrics = {"batch_count": len(items), "current_count": sum(bool(item.get("is_current")) for item in items),
               "assignment_count": 0, "completed_count": 0, "pending_count": 0}
    for item in items:
        rows = [member for member in item.get("members", []) if str(member.get("username", "")).lower() == actor] if actor else [item]
        for row in rows:
            metrics["assignment_count"] += int(row.get("assigned_count" if actor else "assignment_count") or 0)
            metrics["completed_count"] += int(row.get("completed_count") or 0)
            metrics["pending_count"] += int(row.get("pending_count") or 0)
    return metrics
