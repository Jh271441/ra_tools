"""Reveal-safe aggregation of current per-person intent trajectories, no media I/O."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def intent_labels_complete(
    routing: str, lane_change: str, *, label_scope: str = "all"
) -> bool:
    """Return completion using the immutable experiment labeling dimension."""

    if label_scope == "routing":
        return bool(routing)
    if label_scope == "lane_change":
        return bool(lane_change)
    return bool(routing and lane_change)


def intent_frame_counts(
    timeline: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    routing_default: str = "",
    lane_change_default: str = "",
    overrides: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Return frame-level effective intent counts without touching media.

    Intent labels are sparse: a frame override only replaces one axis while
    the other axis continues to inherit the case default.  Keeping this
    calculation in one place makes the detail rail and summary table agree
    on the exact frame-level numbers.
    """

    by_id = {
        str(item.get("timepoint_id")): item
        for item in (overrides or ())
        if item.get("timepoint_id")
    }
    routing = Counter()
    lane_change = Counter()
    for timepoint in timeline or ():
        override = by_id.get(str(timepoint.get("id") or timepoint.get("timepoint_id")), {})
        routing_value = str(override.get("routing_intent") or routing_default or "")
        lane_value = str(override.get("lane_change_intent") or lane_change_default or "")
        if routing_value:
            routing[routing_value] += 1
        if lane_value:
            lane_change[lane_value] += 1
    return {
        "frame_count": len(timeline or ()),
        "labeled_routing_frames": sum(routing.values()),
        "labeled_lane_change_frames": sum(lane_change.values()),
        "routing": dict(routing),
        "lane_change": dict(lane_change),
    }


def intent_completion(
    timeline: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    routing_default: str = "",
    lane_change_default: str = "",
    overrides: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    label_scope: str = "all",
) -> dict[str, Any]:
    """Explain whether every required frame has an effective label.

    A Case may be labeled entirely through frame overrides and have no Case
    default.  Completion therefore has to inspect effective frame values,
    rather than treating a missing default as an incomplete annotation.
    """

    counts = intent_frame_counts(
        timeline,
        routing_default=routing_default,
        lane_change_default=lane_change_default,
        overrides=overrides,
    )
    frame_count = int(counts["frame_count"])
    if not frame_count:
        complete = intent_labels_complete(
            routing_default, lane_change_default, label_scope=label_scope
        )
        return {
            "complete": complete,
            "status": "completed" if complete else "partial",
            "reason": "Case 默认标签完整" if complete else "暂无可校验帧",
            "frame_counts": counts,
            "missing_routing_frames": 0,
            "missing_lane_change_frames": 0,
        }

    need_routing = label_scope != "lane_change"
    need_lane_change = label_scope != "routing"
    missing_routing = max(0, frame_count - int(counts["labeled_routing_frames"])) if need_routing else 0
    missing_lane_change = max(0, frame_count - int(counts["labeled_lane_change_frames"])) if need_lane_change else 0
    complete = missing_routing == 0 and missing_lane_change == 0
    if complete:
        axes = []
        if need_routing:
            axes.append(f"Routing {frame_count}/{frame_count} 帧")
        if need_lane_change:
            axes.append(f"变道意图 {frame_count}/{frame_count} 帧")
        reason = "、".join(axes)
    else:
        missing = []
        if missing_routing:
            missing.append(f"Routing 缺 {missing_routing} 帧")
        if missing_lane_change:
            missing.append(f"变道意图缺 {missing_lane_change} 帧")
        reason = "、".join(missing)
    return {
        "complete": complete,
        "status": "completed" if complete else "partial",
        "reason": reason,
        "frame_counts": counts,
        "missing_routing_frames": missing_routing,
        "missing_lane_change_frames": missing_lane_change,
    }


def public_intent_contributors(
    *,
    username: str,
    contributors: list[dict[str, Any]],
    assignees: list[str] | tuple[str, ...] = (),
    answers_revealed: bool,
    timeline: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    label_scope: str = "all",
) -> list[dict[str, Any]]:
    """Reveal-safe contributor rows for the labeling rail.

    Blind peers stay visible as labeled/pending status.  Routing / lane-change
    values and frame distributions remain private until the Case is revealed.
    """

    current = str(username or "").strip().lower()
    assignee_set = {
        str(item).strip().lower()
        for item in assignees
        if str(item or "").strip()
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for contributor in contributors:
        name = str(contributor.get("username") or "").strip().lower()
        if not name:
            continue
        is_current = name == current
        if not answers_revealed and not is_current and assignee_set and name not in assignee_set:
            continue
        revealed = is_current or answers_revealed
        completion = intent_completion(
            timeline,
            routing_default=str(contributor.get("routing_default") or ""),
            lane_change_default=str(contributor.get("lane_change_default") or ""),
            overrides=contributor.get("overrides") or [],
            label_scope=label_scope,
        )
        item = {
            "username": name,
            "version": int(contributor.get("version") or 0),
            "updated_at": str(contributor.get("updated_at") or ""),
            "labeled": True,
            "completed": completion["complete"],
            "completion_reason": completion["reason"] if revealed else "",
            "is_current": is_current,
            "revealed": revealed,
            "frame_counts": completion["frame_counts"] if revealed else {},
        }
        if revealed:
            item["routing_default"] = contributor.get("routing_default") or ""
            item["lane_change_default"] = contributor.get("lane_change_default") or ""
            item["overrides"] = list(contributor.get("overrides") or [])
        rows.append(item)
        seen.add(name)
    for name in sorted(assignee_set):
        if name in seen:
            continue
        is_current = name == current
        rows.append({
            "username": name,
            "version": 0,
            "updated_at": "",
            "labeled": False,
            "completed": False,
            "completion_reason": "尚未开始",
            "is_current": is_current,
            "revealed": is_current or answers_revealed,
            "frame_counts": {},
        })
    return rows


def summarize_intent(data: dict[str, Any], case_ids: tuple[str, ...], *, username: str,
                     experiment_id: str = "", assignees: tuple[str, ...] = (),
                     reveal_answers: bool = False, axis: str = "all",
                     page: int = 1, page_size: int = 20,
                     label_scope: str = "all") -> dict[str, Any]:
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
        assigned = {(row["case_id"], row["username"]) for row in scoped if row["case_id"] in allowed}
        keys &= assigned
    if assignees:
        keys = {key for key in keys if key[1] in assignees}
    keys = {key for key in keys if reveal_answers or key[0] not in blind_cases or key[1] == username.lower()}
    current_username = username.lower()
    visible_comments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comment in data.get("comments", []):
        case_id = str(comment.get("case_id") or "")
        author = str(comment.get("author") or "").lower()
        if case_id not in allowed:
            continue
        if not reveal_answers and case_id in blind_cases and author != current_username:
            continue
        visible_comments[case_id].append(comment)
    rows = []
    for case, author in sorted(keys):
        head = heads[(case, author)]
        overrides = head.get("overrides") or []
        has_routing = bool(head.get("routing_default") or any(item.get("routing_intent") for item in overrides))
        has_lane_change = bool(head.get("lane_change_default") or any(item.get("lane_change_intent") for item in overrides))
        if label_scope == "routing" and not has_routing:
            continue
        if label_scope == "lane_change" and not has_lane_change:
            continue
        if label_scope == "all" and not has_routing and not has_lane_change:
            continue
        if axis == "routing" and not has_routing:
            continue
        if axis == "lane_change" and not has_lane_change:
            continue
        case_comments = visible_comments.get(case, [])
        rows.append({
            "case_id": case, "username": author,
            "revision_id": int(head.get("revision_id") or 0),
            "routing_default": head.get("routing_default") or "",
            "lane_change_default": head.get("lane_change_default") or "",
            "overrides": overrides, "updated_at": head.get("updated_at") or "",
            "comments": list(reversed(case_comments[-3:])),
            "comment_count": len(case_comments),
        })
    distributions = {axis: dict(Counter(row[axis] or "None" for row in rows))
                     for axis in ("routing_default", "lane_change_default")}
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        if intent_labels_complete(
            row["routing_default"], row["lane_change_default"], label_scope=label_scope
        ):
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
        "axis": axis, "label_scope": label_scope,
        "annotated_cases": len({row["case_id"] for row in rows if row["updated_at"]}),
        "complete_records": sum(intent_labels_complete(
            row["routing_default"], row["lane_change_default"], label_scope=label_scope
        ) for row in rows),
        "blind_active": bool(blind_cases & allowed), "answers_revealed": reveal_answers,
        "distributions": distributions,
        "agreement": {"comparable_cases": len(comparable),
                      "matching_cases": sum(len(set(values)) == 1 for values in comparable)},
        "_all_items": rows,
        "items": rows[(page - 1) * page_size:page * page_size],
    }
