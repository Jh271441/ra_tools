"""Shared plan and preview for Review and Case labeling task creation."""
from collections import Counter, defaultdict
import hashlib

from .allocation_coverage import coverage_summary, plan_cross_coverage
from .db_parts.campaigns import CampaignConflictError, _fingerprint
from .group_allocation import grouped_config, grouped_preview, normalize_groups, plan_groups
from .task_allocation_policy import allocate_percentages, percentage_weights, review_percent, validate_percentages
from .task_reallocation import reallocate_slots
from .work_split import distribute_issue_ids


def prepare_creation_allocation(issue_ids, assignees, *, reviewers, overlap, seed,
                                request_id, body, eligible, identity):
    """Return the exact plan to preview or commit, without writing a Workset."""
    if not request_id:
        raise ValueError("请重新打开创建预览 / Open a new creation preview")
    if not issue_ids or "groups" not in body and not 1 <= reviewers <= len(assignees) <= 100:
        raise ValueError("请检查 Case 范围和所选人数 / Check the Case scope and the number of members")
    if seed is None:
        seed = int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:8], "big") % (2**31)
    if "groups" in body:
        groups = normalize_groups(body["groups"], eligible)
        rows, placed, rules = plan_groups(issue_ids, groups, body.get("cross_groups", []), seed=seed)
        config = grouped_config(groups, placed, rules, "remaining")
        by_person = defaultdict(list)
        for row in rows:
            by_person[row["assignee"]].append({key: row[key] for key in ("issue_id", "assignment_kind", "ordinal")})
        assignments = [
            dict(name=name, count=len(items), requested_count=None,
                 mode="blind" if config["reviewers_per_issue"] > 1 else "share",
                 issue_ids=[row["issue_id"] for row in items], items=items)
            for name, items in sorted(by_person.items())
        ]
        token = _creation_token(identity, request_id, seed, issue_ids, config, assignments, body)
        preview = grouped_preview(groups, [], rows, placed,
                                  dict(protected=set(), completed=set(), coverage_locked=set()))
        return seed, assignments, config, {**preview, "preview_token": token, "cross_groups": rules}
    names = [str(p.get("name") or "").strip().lower() if isinstance(p, dict) else "" for p in assignees]
    if len(set(names)) != len(names) or not set(names).issubset(eligible):
        raise ValueError("请选择不同且有标注权限的成员 / Select distinct members with labeling access")
    shares = any("review_percent" in p for p in assignees)
    people = [dict(name=name, count=p.get("count")) for name, p in zip(names, assignees)]
    if shares:
        if any(p["count"] is not None for p in people):
            raise ValueError("固定数量和个人比例不可混用 / Fixed quotas and personal shares cannot be mixed")
        for person, raw in zip(people, assignees):
            person["review_percent"] = review_percent(raw.get("review_percent"))
        validate_percentages(people, reviewers=reviewers, overlap=overlap)
        rows = allocate_percentages(issue_ids, people, reviewers=reviewers, overlap=overlap, seed=seed)
        weights = percentage_weights(people)
    else:
        assignments = distribute_issue_ids(issue_ids, people, seed=seed, reviewers_per_issue=reviewers, overlap_ratio=overlap)
        rows = [dict(assignee=p["name"], **item) for p in assignments for item in p.get("items", [
            dict(issue_id=iid, assignment_kind="base", ordinal=ordinal)
            for ordinal, iid in enumerate(p["issue_ids"], 1)
        ])]
        for person, assignment in zip(people, assignments):
            person["count"] = assignment["requested_count"]
        weights = {p["name"]: p["count"] if p["count"] is not None else max(1, a["count"])
                   for p, a in zip(people, assignments)}
    counts = Counter(row["issue_id"] for row in rows)
    groups = body.get("cross_groups", [])
    materialized = []
    if groups != []:
        counts, pinned, materialized = plan_cross_coverage(
            counts, target=sum(count > 1 for count in counts.values()), reviewers=reviewers,
            seed=seed, groups=groups, recipients={name for name, weight in weights.items() if weight > 0},
        )
        rows, _ = reallocate_slots(
            rows, weights, basis="total", protected=(), required_counts=counts, pinned_members=pinned,
            fixed_quotas={p["name"]: p["count"] for p in people if p["count"] is not None},
        )
    by_person = defaultdict(list)
    for row in rows:
        by_person[row["assignee"]].append({key: row[key] for key in ("issue_id", "ordinal", "assignment_kind")})
    assignments = [
        dict(name=name, count=len(by_person[name]), requested_count=person["count"],
             mode="blind" if reviewers > 1 else "fixed" if person["count"] is not None else "share",
             issue_ids=[item["issue_id"] for item in by_person[name]], items=by_person[name])
        for person in people for name in [person["name"]]
    ]
    config = dict(assignees=people, reviewers_per_issue=reviewers, overlap_ratio=overlap, cross_groups=materialized)
    token = _creation_token(identity, request_id, seed, issue_ids, config, assignments, body)
    total = len(rows)
    summary = []
    for p, assignment in zip(people, assignments):
        slots = assignment["count"]
        cross = sum(item["assignment_kind"] == "cross" for item in assignment["items"])
        ideal = total * weights[p["name"]] / sum(weights.values())
        summary.append(dict(name=p["name"], total_after=slots, base_after=slots - cross, cross_after=cross,
                            requested_percent=p.get("review_percent"), ideal=ideal, actual_percent=100 * slots / total,
                            constrained=abs(slots - ideal) >= 1))
    preview = dict(preview_token=token, coverage_after=coverage_summary(counts), total_slots=total,
                   cross_groups=materialized, members=summary)
    return seed, assignments, config, preview


def _creation_token(identity, request_id, seed, issue_ids, config, assignments, body):
    token = _fingerprint([identity, request_id, seed, issue_ids, config, assignments,
                          {k: v for k, v in body.items() if k not in {"preview_only", "preview_token"}}])
    if body.get("preview_only") is not True and body.get("preview_token") != token:
        raise CampaignConflictError("创建范围或人员已变化，请重新预览 / Scope or assignments changed; preview again")
    return token
