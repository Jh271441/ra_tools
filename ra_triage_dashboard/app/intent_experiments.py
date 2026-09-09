from __future__ import annotations

from typing import Any

from .assignment_planner import build_balanced_assignments


def build_intent_experiment_assignments(
    case_ids: list[str],
    members: list[str],
    mode: str,
    overlap_ratio: float,
    seed: int,
    reviewers_per_overlap_case: int = 2,
) -> list[dict[str, Any]]:
    """Build a deterministic, balanced assignment snapshot."""

    return [
        {
            "username": item["username"],
            "case_id": item["item_id"],
            "assignment_kind": item["assignment_kind"],
            "ordinal": item["ordinal"],
        }
        for item in build_balanced_assignments(
            case_ids,
            members,
            mode,
            overlap_ratio,
            seed,
            reviewers_per_overlap_case,
        )
    ]
