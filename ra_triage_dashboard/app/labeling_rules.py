"""Pure rules for the final adjudication in a shared Case projection.

No runtime, database or presentation dependencies. Query filters and summary
projections must use this same decision precedence and freshness policy.
"""

def current_adjudication(item):
    if item.get("label_state") != "resolved":
        return None
    decision = item.get("decision") or {}
    if decision and not decision.get("stale"):
        return {
            "kind": "issue", "id": decision.get("id"),
            "author": decision.get("created_by", ""), "created_at": decision.get("created_at", ""),
            "rationale": decision.get("rationale", ""), "expected_output": item.get("expected_output", ""),
            "tags": [], "evidence_gaps": [],
        }
    decisions = []
    for case in item.get("label_cases", []):
        resolution = case.get("resolution") or {}
        result = resolution.get("result_revision") or {}
        if resolution.get("state") == "resolved" and resolution.get("method") == "adjudication" and result.get("expected_output") == item.get("expected_output"):
            decisions.append({**result, "kind": "task", "task_id": case.get("task_id", "")})
    return max(decisions, key=lambda value: int(value.get("id") or 0)) if decisions else None

