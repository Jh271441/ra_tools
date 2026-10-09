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


def expected_output_source(item):
    """Describe provenance of the existing projection, without resolving it again.

    A task decision is authoritative only within its own source. Several resolved
    sources still require agreement unless a current Issue decision supersedes them.
    """
    if item.get("label_state") != "resolved":
        return {"kind": "unresolved", "sources": []}
    decision = item.get("decision") or {}
    if decision and not decision.get("stale"):
        return {
            "kind": "issue_adjudication", "decision_id": decision.get("id"),
            "authors": [decision["created_by"]] if decision.get("created_by") else [],
            "sources": [],
        }
    sources = []
    for case in item.get("label_cases") or []:
        resolution = case.get("resolution") or {}
        if resolution.get("state") != "resolved":
            continue
        adjudicated = resolution.get("method") == "adjudication"
        revisions = ([resolution.get("result_revision") or {}] if adjudicated
                     else resolution.get("heads") or [])
        sources.append({
            "kind": "task_adjudication" if adjudicated else resolution.get("method", "single"),
            "task_id": str(case.get("task_id") or ""),
            "source_run_id": str(case.get("source_run_id") or ""),
            "label_case_id": str(case.get("id") or ""),
            "revision_ids": [value["id"] for value in revisions if value.get("id") is not None],
            "authors": sorted({str(value["author"]) for value in revisions if value.get("author")}),
        })
    if len(sources) > 1:
        kind = "source_consensus"
    elif sources:
        kind = sources[0]["kind"]
    else:
        kind = "unknown"
    return {"kind": kind, "sources": sources,
            "authors": sorted({author for source in sources for author in source["authors"]})}
