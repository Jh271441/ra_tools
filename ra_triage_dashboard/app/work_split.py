"""Even/fixed-quota random split of issue IDs among reviewers."""

from __future__ import annotations

import random
from typing import Any

from .assignment_planner import build_balanced_assignments


def distribute_issue_ids(
    issue_ids: list[str],
    assignees: list[dict[str, Any]],
    *,
    seed: int | None = None,
    reviewers_per_issue: int = 1,
) -> list[dict[str, Any]]:
    """Assign issue IDs to people.

    Each assignee may set a non-negative integer ``count`` for a fixed quota.
    Assignees without a fixed count share the remaining IDs evenly (larger
    remainder goes to earlier people in the share pool).

    Returns one result dict per input assignee, in the same order:
    ``{name, count, requested_count, mode, issue_ids}``.
    """

    cleaned_ids = [str(item).strip() for item in issue_ids if str(item or "").strip()]
    if not cleaned_ids:
        raise ValueError("当前筛选没有可分配的 Issue。")
    if not assignees:
        raise ValueError("请至少填写一名复核人。")

    people: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in assignees:
        if not isinstance(raw, dict):
            raise ValueError("复核人条目必须是对象。")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("复核人姓名不能为空。")
        if len(name) > 64:
            raise ValueError("复核人姓名过长。")
        lowered = name.lower()
        if lowered in seen_names:
            raise ValueError(f"复核人重复：{name}")
        seen_names.add(lowered)
        raw_count = raw.get("count", None)
        if raw_count in (None, "", "null"):
            people.append({"name": name, "fixed": None})
            continue
        try:
            fixed = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 的数量必须是整数。") from exc
        if fixed < 0:
            raise ValueError(f"{name} 的数量不能为负数。")
        people.append({"name": name, "fixed": fixed})

    reviewer_count = int(reviewers_per_issue or 1)
    if reviewer_count < 1:
        raise ValueError("每个 Issue 的复核人数至少为 1。")
    if reviewer_count > len(people):
        raise ValueError("每个 Issue 的复核人数不能超过已选成员数。")
    if reviewer_count > 1:
        if any(person["fixed"] is not None for person in people):
            raise ValueError("多人盲标使用自动均衡分配，不支持个人固定数量。")
        resolved_seed = seed if seed is not None else random.SystemRandom().randrange(2**63)
        rows = build_balanced_assignments(
            cleaned_ids,
            [person["name"] for person in people],
            "blind",
            1.0,
            resolved_seed,
            reviewer_count,
        )
        by_person: dict[str, list[dict[str, Any]]] = {
            person["name"]: [] for person in people
        }
        for row in rows:
            by_person[row["username"]].append(
                {
                    "issue_id": row["item_id"],
                    "assignment_kind": row["assignment_kind"],
                    "ordinal": row["ordinal"],
                }
            )
        return [
            {
                "name": person["name"],
                "count": len(by_person[person["name"]]),
                "requested_count": None,
                "mode": "blind",
                "issue_ids": [item["issue_id"] for item in by_person[person["name"]]],
                "items": by_person[person["name"]],
            }
            for person in people
        ]

    fixed_people = [person for person in people if person["fixed"] is not None]
    share_people = [person for person in people if person["fixed"] is None]
    fixed_total = sum(int(person["fixed"] or 0) for person in fixed_people)
    if fixed_total > len(cleaned_ids):
        raise ValueError(
            f"指定数量合计 {fixed_total} 超过当前筛选 Issue 数 {len(cleaned_ids)}。"
        )
    if not share_people and fixed_total < len(cleaned_ids):
        raise ValueError(
            "还有未分配的 Issue，请增加「均分」人员，或提高已指定数量。"
        )

    rng = random.Random(seed)
    pool = list(cleaned_ids)
    rng.shuffle(pool)

    assignments: dict[str, list[str]] = {person["name"]: [] for person in people}
    cursor = 0
    for person in fixed_people:
        take = min(int(person["fixed"] or 0), len(pool) - cursor)
        assignments[person["name"]] = pool[cursor : cursor + take]
        cursor += take

    remaining = pool[cursor:]
    if share_people:
        base = len(remaining) // len(share_people)
        extra = len(remaining) % len(share_people)
        offset = 0
        for index, person in enumerate(share_people):
            size = base + (1 if index < extra else 0)
            assignments[person["name"]] = remaining[offset : offset + size]
            offset += size
    elif remaining:
        raise ValueError("还有未分配的 Issue，请增加「均分」人员。")

    results: list[dict[str, Any]] = []
    for person in people:
        ids = assignments[person["name"]]
        results.append(
            {
                "name": person["name"],
                "count": len(ids),
                "requested_count": person["fixed"],
                "mode": "fixed" if person["fixed"] is not None else "share",
                "issue_ids": ids,
            }
        )
    return results
