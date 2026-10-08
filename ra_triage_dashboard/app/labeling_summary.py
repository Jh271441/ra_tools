"""Aggregate current Case projections in the legacy reason-analysis shape."""
from collections import Counter, defaultdict
from math import ceil

from .labeling_rules import current_adjudication, expected_output_source

LABELS = ("误触发", "正确触发", "无需协助")


def _head_identity(head):
    revision_id = head.get("id")
    if revision_id is not None:
        return ("id", str(revision_id))
    return (
        "value",
        str(head.get("author") or ""),
        str(head.get("created_at") or ""),
        str(head.get("expected_output") or ""),
        str(head.get("rationale") or ""),
        tuple(sorted(str(value) for value in head.get("tags") or [])),
        tuple(sorted(str(value) for value in head.get("evidence_gaps") or [])),
    )


def _current_heads(item):
    heads, seen = [], set()
    for case in item.get("label_cases", []):
        for head in case.get("resolution", {}).get("heads", []):
            identity = _head_identity(head)
            if identity in seen:
                continue
            seen.add(identity)
            heads.append(head)
    return heads



def summarize_labeling_cases(items, *, page=1, page_size=20):
    states, submitted_states, outputs, pairs, tags, evidence, scenarios = (
        Counter() for _ in range(7)
    )
    people = defaultdict(set)
    compact_items = []
    reason_count = structured_evidence_count = adjudicated_count = 0
    for item in items:
        status = item.get("label_state", "pending")
        states[status] += 1
        output, gt = item.get("expected_output"), item.get("gt_label")
        if status == "resolved" and output in LABELS:
            outputs[output] += 1
            if gt in LABELS:
                pairs[(gt, output)] += 1
        heads = _current_heads(item)
        primary_result = current_adjudication(item)
        original_conflict = any(
            case.get("resolution", {}).get("original_conflict")
            or len({head.get("expected_output") for head in case.get("resolution", {}).get("heads", []) if head.get("expected_output") in LABELS}) > 1
            for case in item.get("label_cases", [])
        ) or len({head.get("expected_output") for head in heads if head.get("expected_output") in LABELS}) > 1
        original_votes = [{"author": h.get("author", ""), "expected_output": h.get("expected_output", ""), "rationale": h.get("rationale", "")} for h in heads]
        display_heads = [primary_result] if primary_result else heads
        case_tags, case_evidence, authors, rationales = set(), set(), set(), []
        created_at = ""
        is_excluded = any(bool(head.get("is_excluded")) for head in heads) if primary_result and primary_result.get("kind") == "issue" else False
        for head in display_heads:
            case_tags.update(str(value) for value in head.get("tags") or [] if value)
            case_evidence.update(
                str(value) for value in head.get("evidence_gaps") or [] if value
            )
            author = str(head.get("author") or "").strip().lower()
            if author:
                authors.add(author)
            rationale = str(head.get("rationale") or "").strip()
            if rationale and rationale not in rationales:
                rationales.append(rationale)
            created_at = max(created_at, str(head.get("created_at") or ""))
            is_excluded = is_excluded or bool(head.get("is_excluded"))
        decision = item.get("decision") or {}
        decision_rationale = str(decision.get("rationale") or "").strip()
        if not decision.get("stale") and decision_rationale and decision_rationale not in rationales:
            rationales.insert(0, decision_rationale)
        if decision and not decision.get("stale"):
            created_at = max(created_at, str(decision.get("created_at") or ""))
        if not heads:
            if item.get("scenario"):
                scenarios[item["scenario"]] += 1
            continue
        submitted_states[status] += 1
        if primary_result:
            adjudicated_count += 1
        if rationales:
            reason_count += 1
        if case_evidence:
            structured_evidence_count += 1
        for author in authors | {str(head.get("author") or "").strip().lower() for head in heads if head.get("author")}:
            people[author].add(item["issue_id"])
        tags.update(case_tags)
        evidence.update(case_evidence)
        if item.get("scenario"):
            scenarios[item["scenario"]] += 1
        compact_items.append(
            {
                "issue_id": str(item.get("issue_id") or ""),
                "baseline_scope": str(item.get("baseline_scope") or ""),
                "title": str(item.get("title") or ""),
                "scenario": str(item.get("scenario") or ""),
                "gt_label": str(gt or ""),
                "label_state": str(status or "pending"),
                "expected_output": str(output or ""),
                "expected_output_source": expected_output_source(item),
                "authors": sorted(authors),
                "rationales": rationales,
                "adjudication": primary_result,
                "original_conflict": original_conflict,
                "original_votes": original_votes,
                "tags": sorted(case_tags),
                "evidence_gaps": sorted(case_evidence),
                "is_excluded": is_excluded,
                "created_at": created_at,
                "source_count": int(item.get("source_count") or 0),
                "decision": (
                    {
                        "id": int(decision["id"]),
                        "created_by": str(decision.get("created_by") or ""),
                        "created_at": str(decision.get("created_at") or ""),
                        "stale": bool(decision.get("stale")),
                    }
                    if decision.get("id") not in (None, "")
                    else None
                ),
            }
        )
    compact_items.sort(
        key=lambda item: (item["created_at"], item["issue_id"]), reverse=True
    )
    safe_page_size = min(100, max(1, int(page_size or 20)))
    total_submitted = len(compact_items)
    page_count = ceil(total_submitted / safe_page_size) if total_submitted else 0
    safe_page = min(max(1, int(page or 1)), page_count or 1)
    start = (safe_page - 1) * safe_page_size
    return {
        "total": len(items), "annotated": total_submitted,
        "states": dict(states), "submitted_states": dict(submitted_states),
        "reason_count": reason_count,
        "adjudicated_count": adjudicated_count,
        "empty_reason_count": total_submitted - reason_count,
        "structured_evidence_count": structured_evidence_count,
        "outputs": dict(outputs),
        "pairs": [{"gt": gt, "label": output, "count": count}
                  for (gt, output), count in sorted(pairs.items())],
        "tags": dict(tags), "evidence": dict(evidence),
        "scenarios": dict(scenarios),
        "people": [{"name": name, "count": len(ids)} for name, ids in
                   sorted(people.items(), key=lambda entry: (-len(entry[1]), entry[0]))],
        "items": compact_items[start:start + safe_page_size],
        "page": safe_page,
        "page_size": safe_page_size,
        "page_count": page_count,
    }
