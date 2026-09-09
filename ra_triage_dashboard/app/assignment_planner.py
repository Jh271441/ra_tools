"""Deterministic balanced assignment snapshots shared by labeling workflows."""

from __future__ import annotations

import random
from typing import Any


def build_balanced_assignments(
    item_ids: list[str],
    members: list[str],
    mode: str,
    overlap_ratio: float,
    seed: int,
    reviewers_per_item: int = 2,
) -> list[dict[str, Any]]:
    """Build the base/cross/full allocation used by blind-review workflows."""

    shuffled = list(item_ids)
    random.Random(seed).shuffle(shuffled)
    assignments: list[dict[str, Any]] = []
    ordinals = {member: 0 for member in members}
    if mode == "full":
        for member in members:
            for item_id in shuffled:
                ordinals[member] += 1
                assignments.append(
                    {
                        "username": member,
                        "item_id": item_id,
                        "assignment_kind": "full",
                        "ordinal": ordinals[member],
                    }
                )
        return assignments

    base_owner: dict[str, str] = {}
    for index, item_id in enumerate(shuffled):
        member = members[index % len(members)]
        base_owner[item_id] = member
        ordinals[member] += 1
        assignments.append(
            {
                "username": member,
                "item_id": item_id,
                "assignment_kind": "base",
                "ordinal": ordinals[member],
            }
        )
    overlap_count = min(len(shuffled), round(len(shuffled) * overlap_ratio))
    cross_counts = {member: 0 for member in members}
    extra_reviewers = max(0, min(len(members), reviewers_per_item) - 1)
    for index, item_id in enumerate(shuffled[:overlap_count]):
        eligible = [member for member in members if member != base_owner[item_id]]
        eligible.sort(
            key=lambda member: (
                cross_counts[member],
                (members.index(member) - index) % len(members),
            )
        )
        for member in eligible[:extra_reviewers]:
            cross_counts[member] += 1
            ordinals[member] += 1
            assignments.append(
                {
                    "username": member,
                    "item_id": item_id,
                    "assignment_kind": "cross",
                    "ordinal": ordinals[member],
                }
            )
    return assignments
