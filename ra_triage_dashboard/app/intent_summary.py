"""Reveal-safe aggregation of current per-person intent trajectories, no media I/O."""
from collections import Counter, defaultdict
from typing import Any


def summarize_intent(data: dict[str, Any], case_ids: tuple[str, ...], *, username: str,
                     experiment_id: str = "", assignees: tuple[str, ...] = (),
                     reveal_answers: bool = False, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    allowed = set(case_ids)
    assignments = [row for row in data["assignments"] if row["case_id"] in allowed]
    # ANY active experiment protects a Case, even when viewing a closed experiment.
    blind_cases = {row["case_id"] for row in assignments if row["status"] == "active"}
    scoped = [row for row in assignments if not experiment_id or row["experiment_id"] == experiment_id]
    if experiment_id:
        allowed &= {row["case_id"] for row in scoped}
    owners: dict[str, set[str]] = defaultdict(set)
    for row in scoped:
        owners[row["case_id"]].add(row["username"])
    if not experiment_id:
        for row in data["heads"]:
            if row["case_id"] in allowed:
                owners[row["case_id"]].add(row["username"])
    if assignees:
        allowed = {case for case in allowed if set(assignees) <= owners[case]}
    heads = {(row["case_id"], row["username"]): row for row in data["heads"] if row["case_id"] in allowed}
    keys = set(heads)
    if experiment_id:
        keys = {(row["case_id"], row["username"]) for row in scoped if row["case_id"] in allowed}
    if assignees:
        keys = {key for key in keys if key[1] in assignees}
    keys = {key for key in keys if reveal_answers or key[0] not in blind_cases or key[1] == username.lower()}
    rows = []
    for case, author in sorted(keys):
        head = heads.get((case, author), {})
        rows.append({
            "case_id": case, "username": author,
            "routing_default": head.get("routing_default") or "",
            "lane_change_default": head.get("lane_change_default") or "",
            "overrides": head.get("overrides") or [], "updated_at": head.get("updated_at") or "",
        })
    distributions = {axis: dict(Counter(row[axis] or "None" for row in rows))
                     for axis in ("routing_default", "lane_change_default")}
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        if row["routing_default"] and row["lane_change_default"]:
            normalized = tuple((item["offset_ms"], item["routing_intent"] or row["routing_default"],
                                item["lane_change_intent"] or row["lane_change_default"])
                               for item in row["overrides"]
                               if (item["routing_intent"] or row["routing_default"],
                                   item["lane_change_intent"] or row["lane_change_default"])
                               != (row["routing_default"], row["lane_change_default"]))
            grouped[row["case_id"]].append((row["routing_default"], row["lane_change_default"], normalized))
    comparable = [values for case, values in grouped.items() if len(values) >= 2
                  and (reveal_answers or case not in blind_cases)]
    page_size = max(1, min(100, page_size))
    page = max(1, min(page, max(1, (len(rows) + page_size - 1) // page_size)))
    return {
        "case_count": len(allowed), "total": len(rows), "page": page, "page_size": page_size,
        "annotated_cases": len({row["case_id"] for row in rows if row["updated_at"]}),
        "complete_records": sum(bool(row["routing_default"] and row["lane_change_default"]) for row in rows),
        "blind_active": bool(blind_cases & allowed), "answers_revealed": reveal_answers,
        "distributions": distributions,
        "agreement": {"comparable_cases": len(comparable),
                      "matching_cases": sum(len(set(values)) == 1 for values in comparable)},
        "items": rows[(page - 1) * page_size:page * page_size],
    }
