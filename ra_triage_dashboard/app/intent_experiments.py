from __future__ import annotations

import random
from typing import Any


def build_intent_experiment_assignments(
    case_ids: list[str], members: list[str], mode: str, overlap_ratio: float, seed: int
) -> list[dict[str, Any]]:
    """Build a deterministic, balanced assignment snapshot."""

    shuffled = list(case_ids)
    random.Random(seed).shuffle(shuffled)
    assignments: list[dict[str, Any]] = []
    ordinals = {member: 0 for member in members}
    if mode == "full":
        for member in members:
            for case_id in shuffled:
                ordinals[member] += 1
                assignments.append(
                    {
                        "username": member,
                        "case_id": case_id,
                        "assignment_kind": "full",
                        "ordinal": ordinals[member],
                    }
                )
        return assignments

    base_owner: dict[str, str] = {}
    for index, case_id in enumerate(shuffled):
        member = members[index % len(members)]
        base_owner[case_id] = member
        ordinals[member] += 1
        assignments.append(
            {
                "username": member,
                "case_id": case_id,
                "assignment_kind": "base",
                "ordinal": ordinals[member],
            }
        )
    overlap_count = min(len(shuffled), round(len(shuffled) * overlap_ratio))
    cross_counts = {member: 0 for member in members}
    for index, case_id in enumerate(shuffled[:overlap_count]):
        eligible = [member for member in members if member != base_owner[case_id]]
        eligible.sort(
            key=lambda member: (
                cross_counts[member],
                (members.index(member) - index) % len(members),
            )
        )
        member = eligible[0]
        cross_counts[member] += 1
        ordinals[member] += 1
        assignments.append(
            {
                "username": member,
                "case_id": case_id,
                "assignment_kind": "cross",
                "ordinal": ordinals[member],
            }
        )
    return assignments
