"""One allocation position per group and Case, backed by the existing task JSON."""
from collections import Counter, defaultdict
import random
import re

from .allocation_coverage import CoverageConstraintError, coverage_summary
from .task_allocation_policy import percentage_weights, review_percent
from .task_reallocation import bounded_shares, reallocate_slots


def group_settings(groups):
    return [{key: group[key] for key in ("group_id", "coverage_percent", "coverage_strategy", "members")}
            for group in groups]


def _group_role(group_id):
    match = re.fullmatch(r"(rd|te)(?:-[0-9]+)?", group_id)
    return match[1] if match else None


def normalize_groups(raw, eligible, *, roles=None):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
        raise ValueError("请选择 1–100 个分配组 / Select 1–100 allocation groups")
    groups = []
    ids = set()
    for item in raw:
        group_id = item.get("group_id") if isinstance(item, dict) else None
        if not isinstance(group_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", group_id) or group_id in ids:
            raise ValueError("分配组标识无效或重复 / Invalid or duplicate allocation group ID")
        ids.add(group_id)
        coverage = review_percent(item.get("coverage_percent"))
        strategy = item.get("coverage_strategy", "overlap")
        if strategy not in ("overlap", "fill"):
            raise ValueError("请选择有效覆盖策略 / Select a valid coverage strategy")
        people = item.get("members")
        if not isinstance(people, list) or not 1 <= len(people) <= 100:
            raise ValueError("每组需要 1–100 位成员 / Each group needs 1–100 members")
        members = []
        seen = set()
        required_role = _group_role(group_id) if roles is not None else None
        for person in people:
            name = str(person.get("name") or "").strip().lower() if isinstance(person, dict) else ""
            if not name or name in seen or name not in eligible or required_role and roles.get(name) != required_role:
                raise ValueError("组内成员须不同且拥有相应标注资格 / Group members must be distinct and eligible for the group")
            seen.add(name)
            members.append(dict(name=name, review_percent=review_percent(person.get("review_percent"))))
        if sum(percentage_weights(members).values()) != 10000:
            raise ValueError("每组成员比例须合计 100% / Member shares must total 100% in each group")
        groups.append(dict(group_id=group_id, coverage_percent=coverage, coverage_strategy=strategy, members=members))
    if roles is not None:
        full = {g["group_id"] for g in groups if g["coverage_percent"] == 100}
        if not {"rd", "te"} <= full:
            raise ValueError("正式任务需要 RD、TE 各覆盖 100% / Formal tasks require 100% RD and 100% TE coverage")
        group_order = {"rd": 0, "te": 1}
        groups.sort(key=lambda group: group_order.get(group["group_id"], 2))
    return groups


def group_history(config, rows, evidence, *, roles=None):
    """Recover actual Case occupants, including tasks created before groups existed."""
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["issue_id"]].append(row)
    stored = config.get("groups") or []
    ids = [group["group_id"] for group in stored]
    bindings = {g["group_id"]: g.get("assignments", {}) for g in stored}
    occupied = defaultdict(dict)
    if roles is not None:
        ids = list(dict.fromkeys(["rd", "te", *ids]))
        captured = evidence.get("captured_roles", {})
        for issue, work in by_case.items():
            people = {row["assignee"]: captured.get((issue, row["assignee"])) for row in work}
            if not set(people.values()) <= {"rd", "te"}:
                raise CoverageConstraintError("正式任务的历史角色不完整 / Formal task has incomplete captured roles")
            for gid in ids:
                name = bindings.get(gid, {}).get(issue)
                role = _group_role(gid)
                if name in people and (role is None or people[name] == role):
                    occupied[issue][gid] = name
                    del people[name]
            for name, role in people.items():
                gid, index = role, 2
                while gid in occupied[issue]:
                    gid = f"{role}-{index}"
                    index += 1
                if gid not in ids:
                    ids.append(gid)
                occupied[issue][gid] = name
    else:
        width = max((len(group) for group in by_case.values()), default=1)
        while len(ids) < width:
            group_id = next(f"group-{i}" for i in range(1, len(ids) + 2) if f"group-{i}" not in ids)
            ids.append(group_id)
        for issue, work in by_case.items():
            names = {row["assignee"] for row in work}
            for gid in ids:
                name = bindings.get(gid, {}).get(issue)
                if name in names:
                    occupied[issue][gid] = name
                    names.remove(name)
            ordered = sorted(work, key=lambda row: (
                row["assignment_kind"] == "cross", row["ordinal"], row["assignee"]))
            unbound_names = (row["assignee"] for row in ordered if row["assignee"] in names)
            free = (gid for gid in ids if gid not in occupied[issue])
            occupied[issue].update(zip(free, unbound_names))

    current = {group["group_id"]: group for group in stored}
    protected = evidence.get("protected", ())
    basis = config.get("quota_basis", "remaining")
    actual = defaultdict(Counter)
    pending = defaultdict(Counter)
    for issue, owners in occupied.items():
        for gid, name in owners.items():
            actual[gid][name] += 1
            if (issue, name) not in protected:
                pending[gid][name] += 1
    configured = {p["name"]: p for p in config.get("assignees", [])}
    groups = []
    for gid in ids:
        if gid in current:
            groups.extend(group_settings([current[gid]]))
            continue
        shares = pending[gid] if basis == "remaining" and pending[gid] else actual[gid]
        weights = {name: shares[name] for name in actual[gid]}
        if roles is not None and gid in {"rd", "te"} and any("review_percent" in p for p in configured.values()):
            weights = {name: round(p.get("review_percent", 0) * 100)
                       for name, p in configured.items() if roles.get(name) == gid}
        if roles is not None and not sum(weights.values()):
            weights = {name: 1 for name in configured if roles.get(name) == gid}
        eligible = config.get("group_eligible_names", weights)
        weights = {name: amount for name, amount in weights.items() if name in eligible}
        if not sum(weights.values()):
            weights = dict.fromkeys(weights, 1)
        shares = bounded_shares(weights, 10000) if weights else {}
        coverage = 100 if roles is not None and gid in {"rd", "te"} else round(100 * sum(actual[gid].values()) / max(1, len(by_case)), 2)
        groups.append(dict(group_id=gid, coverage_percent=coverage, coverage_strategy="overlap",
                           members=[dict(name=name, review_percent=share / 100) for name, share in shares.items()]))
    return groups, dict(occupied)


def group_rules(rules, history):
    """Translate materialized, ungrouped legacy combinations to group positions."""
    by_members = defaultdict(list)
    grouped = []
    for rule in rules:
        if all(isinstance(person, dict) for person in rule["members"]):
            grouped.append(rule)
            continue
        names = set(rule["members"])
        for issue in rule.get("issue_ids", []):
            members = tuple(sorted((gid, name) for gid, name in history.get(issue, {}).items() if name in names))
            if len(members) == len(names):
                by_members[members].append(issue)
    return grouped + [dict(members=[dict(group_id=gid, name=name) for gid, name in members], issue_ids=issues)
                      for members, issues in by_members.items()]


def _specified_slots(rules, groups, ranks, history, locked, fixed, targets, forbidden, covered, match):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("最多支持 100 条指定搭档规则 / Specify up to 100 partner rules")
    allowed = {g["group_id"]: set(p["name"] for p in g["members"] if p["review_percent"] > 0) for g in groups}
    known = set(ranks)
    pinned = defaultdict(dict)
    materialized = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("members"), list):
            raise ValueError("请选择不同组的搭档 / Select partners from different groups")
        members = {}
        for person in rule["members"]:
            gid = person.get("group_id") if isinstance(person, dict) else None
            name = person.get("name") if isinstance(person, dict) else None
            if not isinstance(gid, str) or not isinstance(name, str) or gid not in allowed or gid in members:
                raise ValueError("每条规则每组只能选一人 / Select one member per group in each rule")
            members[gid] = name
        if len(members) < 2 or len(set(members.values())) != len(members):
            raise ValueError("每条规则至少需要两组不同成员 / Select distinct members from at least two groups")
        requested = rule.get("issue_ids", [])
        count = rule.get("count")
        if not isinstance(requested, list) or any(not isinstance(iid, str) or iid not in known for iid in requested):
            raise ValueError("指定 Case 必须位于任务范围内 / Specified Cases must be in the task scope")
        if requested and (count is not None or len(set(requested)) != len(requested)):
            raise ValueError("请填写唯一 Case ID 或数量 / Enter unique Case IDs or a count")
        if not requested and (type(count) is not int or not 0 < count <= len(ranks)):
            raise ValueError("请输入 Case ID 或有效数量 / Enter Case IDs or a valid count")

        def fits(issue):
            previous = history.get(issue, {})
            owners = {**fixed.get(issue, {}), **pinned.get(issue, {})}
            for gid, name in members.items():
                if gid in owners and owners[gid] != name or (issue, name) in forbidden:
                    return False
                if issue in locked and gid not in previous:
                    return False
                if name not in allowed[gid] and fixed.get(issue, {}).get(gid) != name:
                    return False
                if any(other != gid and owner == name for other, owner in owners.items()):
                    return False
                if issue not in covered[gid] and len(covered[gid]) >= targets[gid]:
                    return False
            if match is not None:
                groups_on_case = [gid for gid in allowed if gid in {"rd", "te"} or gid in members or issue in covered[gid]]
                return match(issue, groups_on_case, {**owners, **members})
            return True

        chosen = []
        candidates = requested or sorted(ranks, key=lambda iid: (
            iid in locked, -sum(history.get(iid, {}).get(gid) == name for gid, name in members.items())))
        for issue in candidates:
            if not fits(issue):
                if requested:
                    raise CoverageConstraintError(f"指定搭档与覆盖、权限或已保存工作冲突（{issue}） / Partner rule conflicts with coverage, access or saved work ({issue})")
                continue
            pinned[issue].update(members)
            for gid in members:
                covered[gid].add(issue)
            chosen.append(issue)
            if not requested and len(chosen) == count:
                break
        if not requested and len(chosen) != count:
            raise CoverageConstraintError("没有足够可用 Case 满足指定搭档数量 / Too few eligible Cases for the requested partners")
        materialized.append(dict(members=[dict(group_id=gid, name=name) for gid, name in members.items()],
                                 issue_ids=sorted(chosen)))
    return pinned, materialized


def _coverage(groups, prior_groups, history, ranks, locked, covered, targets, *, match_extra=None, optional=()):
    previous_settings = {g["group_id"]: g for g in prior_groups}
    previous_cases = defaultdict(set)
    for issue, members in history.items():
        for gid in members:
            previous_cases[gid].add(issue)
    occupied = Counter()
    scope = set(ranks)
    required = {gid: set(cases) for gid, cases in covered.items()}
    for group in groups:
        gid = group["group_id"]
        old_cases = previous_cases[gid]
        strategy = group["coverage_strategy"]
        unchanged = previous_settings.get(gid, {}).get("coverage_strategy") == strategy and len(old_cases) == targets[gid]
        free = targets[gid] - len(covered[gid])
        candidates = sorted((iid for iid in ranks if iid not in locked and iid not in covered[gid]), key=lambda iid: (
            unchanged and iid not in old_cases,
            -occupied[iid] if strategy == "overlap" else occupied[iid],
            iid not in old_cases,
        ))
        if match_extra is None or gid in {"rd", "te"}:
            chosen = candidates[:free]
        else:
            chosen = []
            for iid in candidates:
                if len(chosen) == free:
                    break
                issue_groups = [group_id for group_id, cases in covered.items() if group_id == gid or iid in cases]
                if match_extra(iid, issue_groups):
                    chosen.append(iid)
        if len(chosen) < free and gid not in optional:
            raise CoverageConstraintError(
                f"此组最多可覆盖 {len(covered[gid]) + len(chosen)} 个 Case，请调整覆盖率或成员"
                f" / This group can cover up to {len(covered[gid]) + len(chosen)} cases; adjust coverage or members")
        covered[gid].update(chosen)
        occupied.update(covered[gid])
    # Tasks always cover their original Case scope. Displace adjustable overlaps
    # only when the independent coverage targets would otherwise leave gaps.
    for missing in (iid for iid in ranks if not occupied[iid]):
        if missing in locked:
            raise CoverageConstraintError("已保存 Case 的原分配组须保留 / Keep groups with saved assignments")
        for group in reversed(groups):
            gid = group["group_id"]
            donor = next((iid for iid in ranks if iid in covered[gid] and iid not in required[gid] and occupied[iid] > 1), None)
            if donor is not None:
                covered[gid].remove(donor)
                covered[gid].add(missing)
                occupied[donor] -= 1
                occupied[missing] += 1
                break
        else:
            raise CoverageConstraintError("各组覆盖范围须合计覆盖所有 Case / Allocation groups must cover the full task scope")
    assert occupied.keys() <= scope
    return covered


def _match_case(issue, groups, candidates, old, pinned):
    """Start with a feasible, distinct owner per position, retaining old owners first."""
    assigned = {name: gid for gid, name in pinned.items()}

    def place(gid, visited):
        for name in candidates[gid]:
            if name in visited:
                continue
            visited.add(name)
            other = assigned.get(name)
            if other is None or other not in pinned and place(other, visited):
                assigned[name] = gid
                return True
        return False

    for gid in groups:
        name = old.get(gid)
        if gid not in pinned and name in candidates[gid] and name not in assigned:
            assigned[name] = gid
    for gid in groups:
        if gid not in assigned.values() and not place(gid, set()):
            raise CoverageConstraintError(f"此 Case 无法在各组找到不同成员（{issue}） / Distinct members cannot be assigned across groups ({issue})")
    return {gid: name for name, gid in assigned.items()}


def plan_groups(issue_ids, groups, rules, *, seed, old_groups=(), history=None,
                old_rows=(), evidence=None, basis="remaining", roles=None, append=False):
    history = history or {}
    evidence = evidence or {}
    original_locks = set(evidence.get("coverage_locked", ()))
    # Extra formal review seats can be added without moving saved work.
    # Decisions, conflicting submissions and earlier append packets keep their seats.
    locked = original_locks if roles is None or append else set(evidence.get("frozen_cases", ()))
    protected = set(evidence.get("protected", ()))
    forbidden = set(evidence.get("forbidden", ()))
    case_count = len(issue_ids)
    ranks = sorted(issue_ids)
    random.Random(seed).shuffle(ranks)
    weights = {g["group_id"]: percentage_weights(g["members"]) for g in groups}
    previous_cases = Counter(gid for members in history.values() for gid in members)
    fixed = {iid: {gid: name for gid, name in owners.items() if (iid, name) in protected}
             for iid, owners in history.items()}
    required = defaultdict(set)
    for iid, owners in history.items():
        for gid in owners if iid in locked else fixed[iid]:
            required[gid].add(iid)
    if required.keys() - weights.keys():
        raise CoverageConstraintError("请保留已有保存工作的分配组 / Keep allocation groups with saved work")
    covered = {gid: required[gid] for gid in weights}
    targets = {}
    for group in groups:
        gid = group["group_id"]
        coverage = group["coverage_percent"]
        target = round(case_count * coverage / 100)
        if coverage == round(100 * previous_cases[gid] / case_count, 2):
            target = previous_cases[gid]
        minimum, maximum = len(covered[gid]), case_count - len(locked - covered[gid])
        if append:
            target = min(maximum, max(target, minimum))
        if not minimum <= target <= maximum:
            raise CoverageConstraintError(f"此组可覆盖 {minimum}–{maximum} 个 Case / This group can cover {minimum}–{maximum} Cases")
        targets[gid] = target

    names_by_group = {gid: sorted(name for name, share in pool.items() if share > 0) for gid, pool in weights.items()}

    def candidates(iid, gids):
        old = history.get(iid, {})
        old_names = set(old.values()) if roles is not None else set()
        return {gid: [name for name in names_by_group[gid] if (iid, name) not in forbidden
                      and (name not in old_names or old.get(gid) == name)] for gid in gids}

    def match(iid, gids, pinned):
        eligible = candidates(iid, gids)
        if any(name not in eligible[gid] and name != fixed.get(iid, {}).get(gid) for gid, name in pinned.items()):
            return False
        try:
            _match_case(iid, gids, eligible, history.get(iid, {}), pinned)
        except CoverageConstraintError:
            return False
        return True

    extra_groups = set(weights) - {"rd", "te"} if roles is not None else set()
    explicit, materialized = _specified_slots(rules, groups, ranks, history, locked, fixed, targets, forbidden,
                                               covered, match if extra_groups else None)
    if append:
        # Rounding several partial groups independently can leave one incoming
        # Case short. Its primary position is required even in a one-Case packet.
        deficit = case_count - sum(targets.values())
        if deficit > 0:
            targets[groups[0]["group_id"]] += deficit

    def match_extra(iid, gids):
        return match(iid, gids, {**fixed.get(iid, {}), **explicit.get(iid, {})})

    covered = _coverage(groups, old_groups, history, ranks, locked, covered, targets,
                        match_extra=match_extra if extra_groups else None, optional=extra_groups if append else ())
    by_issue = defaultdict(list)
    for gid, cases in covered.items():
        for issue in cases:
            by_issue[issue].append(gid)
    placed = {}
    for issue in ranks:
        gids = by_issue[issue]
        pinned = {**fixed.get(issue, {}), **explicit.get(issue, {})}
        placed[issue] = _match_case(issue, gids, candidates(issue, gids), history.get(issue, {}), pinned)

    ordinal = {iid: index for index, iid in enumerate(issue_ids, 1)}
    for gid, pool in weights.items():
        cases = covered[gid]
        if not cases:
            continue
        blocked = forbidden | {(iid, name) for iid in cases for other, name in placed[iid].items() if other != gid}
        if roles is not None:
            blocked |= {(iid, name) for iid in cases for other, name in history.get(iid, {}).items() if other != gid}
        anchors = {(iid, name) for iid in cases if (name := fixed.get(iid, {}).get(gid)) is not None}
        wanted = {iid: [explicit[iid][gid]] for iid in cases if gid in explicit.get(iid, {})}
        templates = []
        for iid in sorted(cases):
            old = history.get(iid, {}).get(gid)
            # Using the old owner as the cost baseline minimizes transfers;
            # the feasible incumbent is available for every new position.
            owner = old if old is not None else placed[iid][gid]
            templates.append(dict(issue_id=iid, assignee=owner, assignment_kind="base", ordinal=ordinal[iid]))
        assigned, _ = reallocate_slots(templates, pool, basis=basis, protected=anchors,
                                        forbidden=blocked, pinned_members=wanted)
        for row in assigned:
            placed[row["issue_id"]][gid] = row["assignee"]

    existing = {(row["issue_id"], row["assignee"]): row for row in old_rows}
    result = []
    for iid in issue_ids:
        owners = placed[iid]
        for index, (gid, name) in enumerate(sorted(owners.items(), key=lambda item: by_issue[iid].index(item[0]))):
            old = existing.get((iid, name))
            kind = "base" if index == 0 else "cross"
            if iid in original_locks and (original := history.get(iid, {}).get(gid)):
                kind = existing[iid, original]["assignment_kind"]
            result.append(dict(issue_id=iid, assignee=name, assignment_kind=kind,
                               ordinal=old["ordinal"] if old else ordinal[iid], group_id=gid))
    return result, placed, materialized


def grouped_config(groups, placed, rules, basis):
    weighted = Counter()
    for group in groups:
        weighted.update(percentage_weights(group["members"]))
    # Keep the pre-existing flat fields usable by compatibility readers.
    shares = bounded_shares(weighted, 10000)
    counts = [len(owners) for owners in placed.values()]
    by_group = defaultdict(dict)
    for iid, owners in sorted(placed.items()):
        for gid, name in owners.items():
            by_group[gid][iid] = name
    return dict(
        groups=[{**g, "assignments": by_group[g["group_id"]]} for g in groups],
        cross_groups=rules, quota_basis=basis,
        assignees=[dict(name=name, count=None, review_percent=share / 100) for name, share in shares.items()],
        reviewers_per_issue=max(counts), overlap_ratio=sum(count > 1 for count in counts) / len(counts),
    )


def group_projection(groups, placed, completed):
    group_ids = [group["group_id"] for group in groups]
    totals = Counter((gid, name) for owners in placed.values() for gid, name in owners.items())
    done = Counter((gid, name) for iid, owners in placed.items() for gid, name in owners.items()
                   if (iid, name) in completed)
    combinations = Counter(tuple(owners.get(gid) for gid in group_ids) for owners in placed.values())
    by_group = defaultdict(list)
    for gid, name in sorted(totals):
        by_group[gid].append(dict(name=name, total=totals[gid, name], completed=done[gid, name]))
    return dict(case_count=len(placed), groups=[dict(group_id=gid, members=by_group[gid]) for gid in group_ids],
                combinations=[dict(owners=list(owners), count=combinations[owners])
                              for owners in sorted(combinations, key=lambda names: tuple(name or "" for name in names))])


def grouped_preview(groups, old_rows, new_rows, placed, evidence):
    before, after = ({(r["issue_id"], r["assignee"]) for r in rows} for rows in (old_rows, new_rows))
    incoming = Counter(p for _, p in after - before)
    outgoing = Counter(p for _, p in before - after)
    old_counts = Counter(p for _, p in before)
    new_counts = Counter(p for _, p in after)
    done = Counter(p for _, p in evidence["completed"])
    locked = Counter(p for _, p in evidence["protected"])
    members = [dict(name=name, before=old_counts[name], total_after=new_counts[name],
                    completed=done[name], saved_pending=locked[name]-done[name],
                    retained_pending=old_counts[name]-outgoing[name]-done[name],
                    pending_after=new_counts[name]-done[name], incoming=incoming[name], outgoing=outgoing[name])
               for name in sorted(old_counts.keys() | new_counts.keys())]
    old_by_issue = defaultdict(list)
    for iid, name in before:
        old_by_issue[iid].append(name)
    changes = [dict(issue_id=iid, before=sorted(old_by_issue[iid]), after=sorted(owners.values()))
               for iid, owners in sorted(placed.items()) if set(owners.values()) != set(old_by_issue[iid])]
    locks = evidence["coverage_locked"]
    return dict(group_coverage=group_projection(groups, placed, evidence["completed"]), members=members,
                changes=changes, changed_cases=len(changes), total_slots=len(after), moved_slots=sum(incoming.values()),
                completed_slots=sum(done.values()), saved_pending_slots=sum(locked.values())-sum(done.values()),
                movable_slots=len(after)-sum(locked.values()),
                coverage_before=coverage_summary(Counter(iid for iid, _ in before), locks),
                coverage_after=coverage_summary(Counter(iid for iid, _ in after), locks))
