"""Role-free allocation groups with orthogonal cross-pairing and set-union convergence."""
from collections import Counter, defaultdict
import hashlib
import random
import re

from .allocation_coverage import CoverageConstraintError, coverage_summary
from .task_allocation_policy import percentage_weights, review_percent
from .task_reallocation import _Flow, bounded_shares, reallocate_slots


def group_settings(groups):
    return [{key: group[key] for key in ("group_id", "coverage_percent", "coverage_strategy", "members")}
            for group in groups]


def normalize_pairing_mode(value):
    if value in (None, "", "orthogonal"):
        return "orthogonal"
    if value == "paired":
        return "paired"
    raise ValueError("跨组配对方式无效 / Invalid cross-group pairing mode")


def _group_role(group_id):
    match = re.fullmatch(r"(rd|te)(?:-[0-9]+)?", group_id)
    return match[1] if match else None


def _seed_key(*parts):
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def normalize_groups(raw, eligible, *, roles=None):
    """Validate 1..100 role-free allocation groups whose member shares each sum to 100%."""
    del roles  # Groups are decoupled from RD/TE roles; any eligible reviewer may join any group.
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
        if coverage <= 0:
            raise ValueError("每组覆盖率须大于 0% / Group coverage must be greater than 0%")
        strategy = item.get("coverage_strategy", "overlap")
        if strategy not in ("overlap", "fill"):
            raise ValueError("请选择有效覆盖策略 / Select a valid coverage strategy")
        people = item.get("members")
        if not isinstance(people, list) or not 1 <= len(people) <= 100:
            raise ValueError("每组需要 1–100 位成员 / Each group needs 1–100 members")
        members = []
        seen = set()
        for person in people:
            name = str(person.get("name") or "").strip().lower() if isinstance(person, dict) else ""
            if not name or name in seen or name not in eligible:
                raise ValueError("组内成员须不同且拥有相应标注资格 / Group members must be distinct and eligible for the group")
            seen.add(name)
            members.append(dict(name=name, review_percent=review_percent(person.get("review_percent"))))
        if sum(percentage_weights(members).values()) != 10000:
            raise ValueError("每组成员比例须合计 100% / Member shares must total 100% in each group")
        groups.append(dict(group_id=group_id, coverage_percent=coverage, coverage_strategy=strategy, members=members))
    if len(groups) == 1 and groups[0]["coverage_percent"] != 100:
        raise CoverageConstraintError("单组分配须覆盖 100% Case / A single allocation group must cover 100% of Cases")
    return groups


def group_history(config, rows, evidence, *, roles=None):
    """Recover clean per-group Case occupants without polluting groups with non-members."""
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["issue_id"]].append(row)
    stored = config.get("groups") or []
    occupied = defaultdict(dict)
    if stored:
        ids = [group["group_id"] for group in stored]
        bindings = {g["group_id"]: g.get("assignments", {}) for g in stored}
        rosters = {g["group_id"]: {m["name"] for m in g.get("members", []) if m.get("name")} for g in stored}
        pos_rosters = {
            g["group_id"]: {m["name"] for m in g.get("members", []) if m.get("name") and (m.get("review_percent") or 0) > 0}
            for g in stored
        }
        has_bindings = any(bindings.values())
        for issue, work in by_case.items():
            names = {row["assignee"] for row in work}
            for gid in ids:
                allowed = pos_rosters[gid] or rosters[gid]
                name = bindings.get(gid, {}).get(issue)
                if name in names and name in allowed:
                    occupied[issue][gid] = name
                    names.remove(name)
            if not has_bindings and names:
                ordered = [r["assignee"] for r in sorted(work, key=lambda r: (r["assignment_kind"] == "cross", r["ordinal"], r["assignee"]))]
                for gid in ids:
                    if gid in occupied[issue]:
                        continue
                    allowed = pos_rosters[gid] or rosters[gid]
                    pick = next((n for n in ordered if n in names and n in allowed), None)
                    if pick is not None:
                        occupied[issue][gid] = pick
                        names.remove(pick)
        return group_settings(stored), dict(occupied)

    ids = []
    if roles is not None:
        ids = ["rd", "te"]
        captured = evidence.get("captured_roles", {})
        for issue, work in by_case.items():
            people = {row["assignee"]: captured.get((issue, row["assignee"])) for row in work}
            if not set(people.values()) <= {"rd", "te"}:
                # Fall back to generic group recovery if mixed/non-role history exists.
                ids = []
                occupied.clear()
                break
            for name, role in people.items():
                gid, index = role, 2
                while gid in occupied[issue]:
                    gid = f"{role}-{index}"
                    index += 1
                if gid not in ids:
                    ids.append(gid)
                occupied[issue][gid] = name
    if not ids:
        width = max((len(group) for group in by_case.values()), default=1)
        ids = [f"group-{i}" for i in range(1, width + 1)]
        for issue, work in by_case.items():
            ordered = sorted(work, key=lambda row: (row["assignment_kind"] == "cross", row["ordinal"], row["assignee"]))
            for gid, row in zip(ids, ordered):
                occupied[issue][gid] = row["assignee"]

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


def _match_group_owners(groups, candidates, old, pinned):
    """Match distinct owners to groups, preferring previous bindings when eligible."""
    assigned = {name: gid for gid, name in pinned.items()}

    def place(gid, visited):
        for name in candidates[gid]:
            if name in visited:
                continue
            visited.add(name)
            other = assigned.get(name)
            if other is None or (other not in pinned and place(other, visited)):
                assigned[name] = gid
                return True
        return False

    for gid in groups:
        name = old.get(gid)
        if gid not in pinned and name in candidates[gid] and name not in assigned:
            assigned[name] = gid
    for gid in groups:
        if gid not in assigned.values():
            place(gid, set())
    return {gid: name for name, gid in assigned.items()}


def _match_case(issue, groups, candidates, old, pinned):
    owners = _match_group_owners(groups, candidates, old, pinned)
    if len(owners) != len(groups):
        raise CoverageConstraintError(f"此 Case 无法在各组找到不同成员（{issue}） / Distinct members cannot be assigned across groups ({issue})")
    return owners


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
                if issue in locked and gid not in previous and fixed.get(issue, {}).get(gid) != name:
                    return False
                if name not in allowed[gid] and fixed.get(issue, {}).get(gid) != name:
                    return False
                if any(other != gid and owner == name for other, owner in owners.items()):
                    return False
                if issue not in covered[gid] and len(covered[gid]) >= targets[gid]:
                    return False
            if match is not None:
                groups_on_case = [
                    g["group_id"] for g in groups
                    if g["coverage_percent"] == 100 or g["group_id"] in members or issue in covered[g["group_id"]]
                ]
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


def _stratified_order(candidates, sig_fn):
    """Interleave candidates evenly across earlier-group partner buckets while preserving within-bucket priority."""
    buckets = defaultdict(list)
    order_keys = []
    for iid in candidates:
        sig = sig_fn(iid)
        if sig not in buckets:
            order_keys.append(sig)
        buckets[sig].append(iid)
    if len(order_keys) <= 1:
        return list(candidates)
    total = len(candidates)
    sizes = {sig: len(buckets[sig]) for sig in order_keys}
    taken = Counter()
    cursors = Counter()
    out = []
    while len(out) < total:
        available = [sig for sig in order_keys if cursors[sig] < sizes[sig]]
        # Pick the bucket whose sampled fraction taken/size is currently lowest.
        best = min(available, key=lambda sig: (taken[sig] / sizes[sig], order_keys.index(sig)))
        out.append(buckets[best][cursors[best]])
        cursors[best] += 1
        taken[best] += 1
    return out


def _allocate_group_orthogonal(cases, pool, *, basis, anchors, blocked, wanted, old_owners,
                               partner_sigs, seed, gid, ordinal, pairing_mode="orthogonal",
                               preferred_partners=None):
    """Assign exact group quotas while balancing cross-group partner buckets orthogonally (or 1-to-1 paired)."""
    # Shuffle Case IDs via surrogate keys so base flow never clumps alphabetically.
    shuffled = sorted(cases, key=lambda iid: _seed_key(seed, gid, iid))
    width = len(str(max(1, len(shuffled))))
    fwd = {iid: f"s{idx:0{width}d}" for idx, iid in enumerate(shuffled)}
    rev = {surrogate: iid for iid, surrogate in fwd.items()}

    templates = []
    for iid in shuffled:
        anchor_owner = next((p for i, p in anchors if i == iid), None)
        pin_owner = wanted.get(iid)
        fallback = next((p for p, w in sorted(pool.items()) if w > 0 and (iid, p) not in blocked), next(iter(pool)))
        owner = anchor_owner or pin_owner or (old_owners.get(iid) if old_owners.get(iid) in pool and (iid, old_owners.get(iid)) not in blocked else fallback)
        templates.append(dict(issue_id=fwd[iid], assignee=owner, assignment_kind="base", ordinal=ordinal[iid]))

    s_anchors = {(fwd[iid], p) for iid, p in anchors if iid in fwd}
    s_blocked = {(fwd[iid], p) for iid, p in blocked if iid in fwd}
    s_wanted = {fwd[iid]: [p] for iid, p in wanted.items() if iid in fwd}

    try:
        base_rows, _ = reallocate_slots(
            templates, pool, basis=basis, protected=s_anchors, forbidden=s_blocked, pinned_members=s_wanted,
        )
    except ValueError as exc:
        raise CoverageConstraintError(
            "成员跨组累计占比超过可用不重复 Case 上限，请调低比例或调整分组 / "
            "Member shares across groups exceed distinct Case capacity; adjust shares or groups"
        ) from exc

    base_map = {rev[row["issue_id"]]: row["assignee"] for row in base_rows}
    if pairing_mode != "paired":
        distinct_sigs = {partner_sigs[iid] for iid in cases}
        if len(distinct_sigs) <= 1:
            return base_map

    # Exact per-member total counts proved feasible by reallocate_slots.
    target_counts = Counter(base_map.values())
    fixed_owner = {**wanted, **{iid: p for iid, p in anchors if iid in cases}}
    locked_counts = Counter(fixed_owner.values())
    free_quotas = {p: target_counts[p] - locked_counts[p] for p in target_counts if target_counts[p] > locked_counts[p]}
    free_cases = [iid for iid in shuffled if iid not in fixed_owner]
    if not free_cases or len(free_quotas) <= 1:
        return base_map

    people = sorted(free_quotas)
    if pairing_mode == "paired" and preferred_partners:
        flow = _Flow()
        source = flow.node()
        sink = flow.node()
        case_idx_map = {iid: flow.node() for iid in free_cases}
        person_nodes = {p: flow.node() for p in people}
        for iid in free_cases:
            flow.edge(source, case_idx_map[iid], 1, 0)
        for p in people:
            flow.edge(person_nodes[p], sink, free_quotas[p], 0)
        case_edges = defaultdict(list)
        for iid in free_cases:
            pref = preferred_partners.get(iid)
            for p in people:
                if (iid, p) in blocked:
                    continue
                is_pref = pref is not None and p == pref
                keep_old = old_owners.get(iid) == p
                cost = (0 if keep_old else 1) if is_pref else (100 if keep_old else 101)
                case_edges[iid].append((p, flow.edge(case_idx_map[iid], person_nodes[p], 1, cost)))
        try:
            flow.send(source, sink, len(free_cases))
        except ValueError:
            return base_map
        result = dict(fixed_owner)
        for iid in free_cases:
            chosen = next((p for p, edge in case_edges[iid] if edge[1] == 0), None)
            result[iid] = chosen or base_map[iid]
        return result

    buckets_all = defaultdict(list)
    buckets_free = defaultdict(list)
    for iid in shuffled:
        buckets_all[partner_sigs[iid]].append(iid)
    for iid in free_cases:
        buckets_free[partner_sigs[iid]].append(iid)

    # Build min-cost max-flow: Source -> Case -> (Bucket, Person) -> Person -> Sink
    # Node layout: 0=source, 1=sink, 2..2+F-1=free_cases, next=people, dynamic=(bucket, person)
    source, sink = 0, 1
    case_offset = 2
    person_offset = case_offset + len(free_cases)
    person_nodes = {p: person_offset + idx for idx, p in enumerate(people)}
    bp_specs = []
    for sig, b_free in sorted(buckets_free.items(), key=lambda item: str(item[0])):
        b_all = buckets_all[sig]
        locked_in_b = Counter(fixed_owner[iid] for iid in b_all if iid in fixed_owner)
        # Eligible people in this bucket: those not already occupying an earlier seat in sig
        sig_names = {name for name in sig if name}
        denom = sum(target_counts[q] for q in target_counts if q not in sig_names)
        for p in people:
            elig_cases = [iid for iid in b_free if (iid, p) not in blocked]
            if not elig_cases:
                continue
            ideal = (len(b_all) * target_counts[p] / denom) if denom > 0 and p not in sig_names else 0.0
            rem = max(0.0, ideal - locked_in_b[p])
            bp_specs.append((sig, p, elig_cases, rem, len(b_free)))

    flow = _Flow()
    source = flow.node()
    sink = flow.node()
    case_idx_map = {iid: flow.node() for iid in free_cases}
    person_nodes = {p: flow.node() for p in people}
    for iid in free_cases:
        flow.edge(source, case_idx_map[iid], 1, 0)
    for p in people:
        flow.edge(person_nodes[p], sink, free_quotas[p], 0)

    case_edges = defaultdict(list)
    for _, p, elig_cases, rem, cap_max in bp_specs:
        bp_node = flow.node()
        for iid in elig_cases:
            # Prefer retaining previous untouched owner within the same orthogonal bucket.
            cost = 0 if old_owners.get(iid) == p else 1
            case_edges[iid].append((p, flow.edge(case_idx_map[iid], bp_node, 1, cost)))
        whole = int(rem)
        if whole > 0:
            flow.edge(bp_node, person_nodes[p], whole, 0)
        if rem - whole > 1e-9:
            flow.edge(bp_node, person_nodes[p], 1, 4)
        flow.edge(bp_node, person_nodes[p], cap_max, 100)

    try:
        flow.send(source, sink, len(free_cases))
    except ValueError:
        return base_map

    result = dict(fixed_owner)
    for iid in free_cases:
        chosen = next((p for p, edge in case_edges[iid] if edge[1] == 0), None)
        result[iid] = chosen or base_map[iid]
    return result


def plan_groups(issue_ids, groups, rules, *, seed, old_groups=(), history=None,
                old_rows=(), evidence=None, basis="remaining", roles=None, append=False,
                pairing_mode="orthogonal"):
    del roles
    pairing_mode = normalize_pairing_mode(pairing_mode)
    history = history or {}
    evidence = evidence or {}
    locked = set(evidence.get("coverage_locked" if append else "frozen_cases", ()))
    protected = set(evidence.get("protected", ()))
    forbidden = set(evidence.get("forbidden", ()))
    case_count = len(issue_ids)
    ranks = sorted(issue_ids)
    random.Random(seed).shuffle(ranks)
    rank_index = {iid: idx for idx, iid in enumerate(ranks)}

    weights = {g["group_id"]: percentage_weights(g["members"]) for g in groups}
    ordered_pos = {g["group_id"]: [m["name"] for m in g["members"] if m["review_percent"] > 0] for g in groups}
    pos_names = {gid: sorted(name for name, share in pool.items() if share > 0) for gid, pool in weights.items()}
    previous_cases = Counter(gid for members in history.values() for gid in members)

    targets = {}
    for group in groups:
        gid = group["group_id"]
        coverage = group["coverage_percent"]
        target = round(case_count * coverage / 100)
        if previous_cases[gid] and coverage == round(100 * previous_cases[gid] / case_count, 2):
            target = previous_cases[gid]
        if append:
            minimum = previous_cases[gid]
            target = min(minimum + case_count - len(locked), max(target, minimum))
        targets[gid] = target

    # Step 1: Roster-aware stateless matching of protected work to current groups.
    # Process single-author protected Cases before multi-author intersections so
    # quota-guided tie-breaking hands intersection seats to under-quota members.
    prot_by_issue = defaultdict(list)
    for iid, name in sorted(protected):
        if iid in rank_index:
            prot_by_issue[iid].append(name)

    ideal_seat = {
        (gid, name): targets[gid] * share / 10000.0
        for gid, pool in weights.items() for name, share in pool.items() if share > 0
    }
    active_prot_counts = Counter()
    fixed = defaultdict(dict)
    covered = {gid: set() for gid in weights}
    unmatched_prot = defaultdict(list)

    ordered_prot_cases = sorted(prot_by_issue, key=lambda iid: (len(prot_by_issue[iid]), rank_index[iid]))
    for iid in ordered_prot_cases:
        authors = prot_by_issue[iid]
        available = [gid for gid in weights if len(covered[gid]) < targets[gid]]
        if append and iid in locked:
            bound = {gid: history[iid][gid] for gid in available
                     if gid in history.get(iid, {}) and history[iid][gid] in authors}
        else:
            # Prefer positive-share members in each group; rank by most under-quota first.
            cand = {
                gid: sorted(
                    [a for a in authors if a in pos_names[gid]],
                    key=lambda a: (active_prot_counts[gid, a] - ideal_seat[gid, a],
                                   history.get(iid, {}).get(gid) != a, a),
                )
                for gid in available
            }
            old_pref = {
                gid: name for gid, name in history.get(iid, {}).items()
                if gid in cand and name in cand[gid]
                and len(cand[gid]) == 1
            }
            bound = _match_group_owners(available, cand, old_pref, {})
        fixed[iid] = bound
        for gid, name in bound.items():
            covered[gid].add(iid)
            active_prot_counts[gid, name] += 1
        unmatched_prot[iid] = [a for a in authors if a not in bound.values()]

    # Step 1b: Set-Union satisfaction when shrinking to single-group (or when an
    # adjudicated/frozen Case cannot accept new reviewers beyond its saved ones).
    union_covered = defaultdict(dict)
    if len(groups) == 1:
        gid0 = groups[0]["group_id"]
        for iid in ordered_prot_cases:
            if gid0 not in fixed[iid] and unmatched_prot[iid] and len(covered[gid0]) < targets[gid0]:
                # Case already has a saved/completed owner in the set union; do not duplicate pending work
                # and do NOT write this non-recipient into groups[0].assignments!
                union_covered[iid][gid0] = unmatched_prot[iid].pop(0)
                covered[gid0].add(iid)
    else:
        for iid in (i for i in ordered_prot_cases if i in locked and unmatched_prot[i]):
            for gid in weights:
                if gid not in fixed[iid] and unmatched_prot[iid] and len(covered[gid]) < targets[gid]:
                    union_covered[iid][gid] = unmatched_prot[iid].pop(0)
                    covered[gid].add(iid)

    def candidates(iid, gids):
        if iid in locked:
            return {
                gid: ([fixed[iid][gid]] if gid in fixed.get(iid, {})
                      else [union_covered[iid][gid]] if gid in union_covered.get(iid, {})
                      else [])
                for gid in gids
            }
        return {
            gid: ([fixed[iid][gid]] if gid in fixed.get(iid, {})
                  else [union_covered[iid][gid]] if gid in union_covered.get(iid, {})
                  else [n for n in pos_names[gid] if (iid, n) not in forbidden])
            for gid in gids
        }

    def match(iid, gids, pinned):
        eligible = candidates(iid, gids)
        if any(name not in eligible[gid] and name != fixed.get(iid, {}).get(gid) for gid, name in pinned.items()):
            return False
        try:
            _match_case(iid, gids, eligible, history.get(iid, {}), pinned)
        except CoverageConstraintError:
            return False
        return True

    explicit, materialized = _specified_slots(
        rules, groups, ranks, history, locked, fixed, targets, forbidden, covered, match,
    )
    if append:
        deficit = case_count - sum(targets.values())
        if deficit > 0:
            targets[groups[0]["group_id"]] += deficit

    # Cap targets if frozen adjudicated Cases have fewer seats than requested groups.
    for group in groups:
        gid = group["group_id"]
        max_possible = len(covered[gid]) + sum(1 for iid in ranks if iid not in covered[gid] and iid not in locked)
        if group["coverage_percent"] == 100 and targets[gid] > max_possible and locked:
            targets[gid] = max_possible

    previous_settings = {g["group_id"]: g for g in old_groups}
    previous_group_cases = defaultdict(set)
    for iid, members in history.items():
        for gid in members:
            previous_group_cases[gid].add(iid)

    # Step 2: Select coverage and solve orthogonal group assignments sequentially
    # so partial groups stratify evenly across earlier groups' actual owners.
    placed = defaultdict(dict)
    for iid, owners in fixed.items():
        placed[iid].update(owners)

    occupied = Counter()
    required_cov = {gid: set(cases) for gid, cases in covered.items()}
    all_first_full = groups[0]["coverage_percent"] == 100

    if not all_first_full:
        # Multi-partial-group union mode: select coverage across all groups first, ensuring full scope union.
        for group in groups:
            gid = group["group_id"]
            old_cases = previous_group_cases[gid]
            strategy = group["coverage_strategy"]
            unchanged = previous_settings.get(gid, {}).get("coverage_strategy") == strategy and len(old_cases) == targets[gid]
            free = targets[gid] - len(covered[gid])
            pool_cands = sorted(
                (iid for iid in ranks if iid not in locked and iid not in covered[gid]),
                key=lambda iid: (
                    unchanged and iid not in old_cases,
                    -occupied[iid] if strategy == "overlap" else occupied[iid],
                    iid not in old_cases,
                ),
            )
            chosen = []
            for iid in pool_cands:
                if len(chosen) == free:
                    break
                issue_groups = [g_id for g_id, cs in covered.items() if g_id == gid or iid in cs]
                if match(iid, issue_groups, {**fixed.get(iid, {}), **explicit.get(iid, {})}):
                    chosen.append(iid)
            if len(chosen) < free and not append:
                raise CoverageConstraintError(
                    f"此组最多可覆盖 {len(covered[gid]) + len(chosen)} 个 Case，请调整覆盖率或成员"
                    f" / This group can cover up to {len(covered[gid]) + len(chosen)} cases; adjust coverage or members"
                )
            covered[gid].update(chosen)
            occupied.update(covered[gid])
        for missing in (iid for iid in ranks if not occupied[iid]):
            if missing in locked:
                raise CoverageConstraintError("已保存 Case 的原分配组须保留 / Keep groups with saved assignments")
            for group in reversed(groups):
                gid = group["group_id"]
                donor = next((iid for iid in ranks if iid in covered[gid] and iid not in required_cov[gid] and occupied[iid] > 1), None)
                if donor is not None:
                    covered[gid].remove(donor)
                    covered[gid].add(missing)
                    occupied[donor] -= 1
                    occupied[missing] += 1
                    break
            else:
                raise CoverageConstraintError("各组覆盖范围须合计覆盖所有 Case / Allocation groups must cover the full task scope")

    ordinal = {iid: index for index, iid in enumerate(issue_ids, 1)}
    prev_gids = []

    for g_idx, group in enumerate(groups):
        gid = group["group_id"]
        pool = weights[gid]
        if all_first_full:
            old_cases = previous_group_cases[gid]
            strategy = group["coverage_strategy"]
            unchanged = previous_settings.get(gid, {}).get("coverage_strategy") == strategy and len(old_cases) == targets[gid]
            free = targets[gid] - len(covered[gid])
            if free > 0:
                raw_cands = [iid for iid in ranks if iid not in locked and iid not in covered[gid]]
                # Stratify evenly across earlier groups' assigned owners within each priority tier.
                tiers = defaultdict(list)
                for iid in raw_cands:
                    tier = (
                        unchanged and iid not in old_cases,
                        -occupied[iid] if strategy == "overlap" else occupied[iid],
                        bool(prot_by_issue.get(iid)),
                        iid not in old_cases,
                    )
                    tiers[tier].append(iid)
                full_prev = [p_gid for p_gid in prev_gids if len(covered[p_gid]) == case_count]
                ordered_cands = []
                for tier in sorted(tiers):
                    ordered_cands.extend(
                        _stratified_order(tiers[tier], lambda iid: tuple(
                            placed[iid].get(p_gid) or union_covered[iid].get(p_gid) for p_gid in full_prev
                        ))
                    )
                chosen = []
                for iid in ordered_cands:
                    if len(chosen) == free:
                        break
                    pinned_now = {
                        **{p_gid: placed[iid][p_gid] for p_gid in prev_gids if p_gid in placed[iid]},
                        **{p_gid: union_covered[iid][p_gid] for p_gid in prev_gids if p_gid in union_covered[iid]},
                        **fixed.get(iid, {}),
                        **explicit.get(iid, {}),
                    }
                    issue_groups = list(dict.fromkeys([
                        *[p_gid for p_gid in prev_gids if iid in covered[p_gid]],
                        gid,
                        *pinned_now.keys(),
                    ]))
                    if match(iid, issue_groups, pinned_now):
                        chosen.append(iid)
                if len(chosen) < free and not (append and g_idx > 0):
                    raise CoverageConstraintError(
                        f"此组最多可覆盖 {len(covered[gid]) + len(chosen)} 个 Case，请调整覆盖率或成员"
                        f" / This group can cover up to {len(covered[gid]) + len(chosen)} cases; adjust coverage or members"
                    )
                covered[gid].update(chosen)
            occupied.update(covered[gid])

        # Solve member assignments for active (non-union-covered) Cases in gid.
        active_cases = [iid for iid in sorted(covered[gid]) if gid not in union_covered.get(iid, {})]
        if active_cases:
            later_groups = [g["group_id"] for g in groups[g_idx + 1:]]
            blocked = set(forbidden)
            for iid in active_cases:
                # Cannot collide with earlier placed/union owners or later fixed/explicit owners.
                taken = (
                    {placed[iid][p_gid] for p_gid in prev_gids if p_gid in placed[iid]}
                    | {union_covered[iid][p_gid] for p_gid in prev_gids if p_gid in union_covered[iid]}
                    | {fixed[iid][l_gid] for l_gid in later_groups if l_gid in fixed.get(iid, {})}
                    | {explicit[iid][l_gid] for l_gid in later_groups if l_gid in explicit.get(iid, {})}
                )
                for name in taken:
                    blocked.add((iid, name))
                # Lookahead Hall guard: do not exhaust all eligible members of a later full/pinned group on iid.
                for l_gid in later_groups:
                    if groups[g_idx + 1 + later_groups.index(l_gid)]["coverage_percent"] < 100 and iid not in covered[l_gid]:
                        continue
                    if l_gid in fixed.get(iid, {}) or l_gid in explicit.get(iid, {}) or l_gid in union_covered.get(iid, {}):
                        continue
                    l_cands = [n for n in pos_names[l_gid] if (iid, n) not in forbidden and n not in taken]
                    if len(l_cands) == 1:
                        blocked.add((iid, l_cands[0]))

            anchors = {(iid, fixed[iid][gid]) for iid in active_cases if gid in fixed.get(iid, {})}
            wanted = {iid: explicit[iid][gid] for iid in active_cases if gid in explicit.get(iid, {})}
            old_owners = {iid: history[iid][gid] for iid in active_cases if gid in history.get(iid, {})}
            partner_sigs = {
                iid: (
                    *(placed[iid].get(p_gid) or union_covered[iid].get(p_gid) for p_gid in prev_gids),
                    *(fixed.get(iid, {}).get(l_gid) or explicit.get(iid, {}).get(l_gid) for l_gid in later_groups),
                )
                for iid in active_cases
            }
            preferred_partners = None
            if pairing_mode == "paired" and len(groups) > 1 and ordered_pos.get(gid):
                if g_idx == 0:
                    # Look ahead at locked/explicit owners in later groups so Group 1's movable cases
                    # still pair 1-to-1 even when later groups are mostly already completed.
                    g0_order = ordered_pos[gid]
                    preferred_partners = {}
                    for l_gid in later_groups:
                        lk_order = ordered_pos.get(l_gid, [])
                        if not lk_order:
                            continue
                        lk_idx_map = {name: idx for idx, name in enumerate(lk_order)}
                        for iid in active_cases:
                            if iid in preferred_partners:
                                continue
                            pk = fixed.get(iid, {}).get(l_gid) or explicit.get(iid, {}).get(l_gid)
                            if pk in lk_idx_map:
                                idx_k = lk_idx_map[pk]
                                cand = g0_order[idx_k % len(g0_order)]
                                if cand == pk and len(g0_order) > 1:
                                    cand = g0_order[(idx_k + 1) % len(g0_order)]
                                preferred_partners[iid] = cand
                    if not preferred_partners:
                        preferred_partners = None
                else:
                    g0_id = groups[0]["group_id"]
                    g0_order = ordered_pos.get(g0_id, [])
                    g0_idx_map = {name: idx for idx, name in enumerate(g0_order)}
                    gk_order = ordered_pos[gid]
                    preferred_partners = {}
                    for iid in active_cases:
                        p0 = placed[iid].get(g0_id) or union_covered[iid].get(g0_id)
                        if p0 in g0_idx_map:
                            idx0 = g0_idx_map[p0]
                            cand = gk_order[idx0 % len(gk_order)]
                            if cand == p0 and len(gk_order) > 1:
                                cand = gk_order[(idx0 + 1) % len(gk_order)]
                            preferred_partners[iid] = cand
            assigned_map = _allocate_group_orthogonal(
                active_cases, pool, basis=basis, anchors=anchors, blocked=blocked, wanted=wanted,
                old_owners=old_owners, partner_sigs=partner_sigs, seed=seed, gid=gid, ordinal=ordinal,
                pairing_mode=pairing_mode, preferred_partners=preferred_partners,
            )
            for iid, owner in assigned_map.items():
                placed[iid][gid] = owner

        prev_gids.append(gid)

    if any(not occupied[iid] for iid in ranks):
        raise CoverageConstraintError("各组覆盖范围须合计覆盖所有 Case / Allocation groups must cover the full task scope")

    by_issue = defaultdict(list)
    for group in groups:
        gid = group["group_id"]
        for iid in covered[gid]:
            by_issue[iid].append(gid)

    existing = {(row["issue_id"], row["assignee"]): row for row in old_rows}
    result = []
    for iid in issue_ids:
        active_map = {**union_covered.get(iid, {}), **placed.get(iid, {})}
        extra_authors = [
            name for name in unmatched_prot.get(iid, [])
            if name not in active_map.values()
        ]
        all_names = [*[active_map[gid] for gid in by_issue[iid] if gid in active_map], *extra_authors]
        base_needed = all(existing.get((iid, name), {}).get("assignment_kind") != "base" for name in all_names)
        for gid in by_issue[iid]:
            if gid not in active_map:
                continue
            name = active_map[gid]
            old = existing.get((iid, name))
            kind = old["assignment_kind"] if old else ("base" if base_needed else "cross")
            if kind == "base":
                base_needed = False
            result.append(dict(
                issue_id=iid, assignee=name, assignment_kind=kind,
                ordinal=old["ordinal"] if old else ordinal[iid],
                group_id=gid if gid in placed.get(iid, {}) else None,
                union_covered=gid in union_covered.get(iid, {}),
            ))
        for name in extra_authors:
            old = existing.get((iid, name))
            kind = old["assignment_kind"] if old else ("base" if base_needed else "cross")
            if kind == "base":
                base_needed = False
            result.append(dict(
                issue_id=iid, assignee=name, assignment_kind=kind,
                ordinal=old["ordinal"] if old else ordinal[iid],
                group_id=None, extra_retained=True,
            ))

    # Ensure every Case keeps full dict entry in placed (pure active group bindings only).
    clean_placed = {iid: dict(placed.get(iid, {})) for iid in issue_ids}
    return result, clean_placed, materialized


def grouped_config(groups, placed, rules, basis, pairing_mode="orthogonal"):
    weighted = Counter()
    for group in groups:
        weighted.update(percentage_weights(group["members"]))
    shares = bounded_shares(weighted, 10000)
    by_group = defaultdict(dict)
    for iid, owners in sorted(placed.items()):
        for gid, name in owners.items():
            by_group[gid][iid] = name
    max_depth = max(1, max((len(owners) for owners in placed.values()), default=1))
    if len(groups) == 1:
        max_depth = 1
    overlap = 0.0 if len(groups) == 1 or not placed else sum(len(owners) > 1 for owners in placed.values()) / len(placed)
    result = dict(
        groups=[{**g, "assignments": by_group[g["group_id"]]} for g in groups],
        cross_groups=rules, quota_basis=basis,
        assignees=[dict(name=name, count=None, review_percent=share / 100) for name, share in shares.items()],
        reviewers_per_issue=max_depth, overlap_ratio=overlap,
    )
    if len(groups) > 1 and normalize_pairing_mode(pairing_mode) == "paired":
        result["pairing_mode"] = "paired"
    return result


def convergence_summary(case_ids, evidence):
    """Summarize set-union Case completion, consensus and unresolved overlap conflicts."""
    case_set = set(case_ids)
    completed_pairs = {pair for pair in evidence.get("completed", set()) if pair[0] in case_set}
    completed_by_issue = defaultdict(set)
    for iid, author in completed_pairs:
        completed_by_issue[iid].add(author)

    outputs_by_issue = evidence.get("case_outputs", {})
    adjudicated_set = set(evidence.get("adjudicated_cases", set())) & case_set

    adjudicated = 0
    consensus = 0
    conflict_ids = []
    single_done = 0
    pending = 0

    for iid in sorted(case_set):
        authors = completed_by_issue.get(iid, set())
        if iid in adjudicated_set:
            adjudicated += 1
            continue
        if not authors:
            pending += 1
            continue
        labels = {outputs_by_issue.get((iid, a)) for a in authors if outputs_by_issue.get((iid, a))}
        if len(authors) >= 2:
            if len(labels) > 1:
                conflict_ids.append(iid)
            else:
                consensus += 1
        else:
            single_done += 1

    union_completed = len(case_set) - pending
    overlap_completed = consensus + len(conflict_ids) + sum(1 for iid in adjudicated_set if len(completed_by_issue.get(iid, ())) >= 2)
    return dict(
        case_count=len(case_set),
        union_completed_cases=union_completed,
        pending_cases=pending,
        single_completed_cases=single_done,
        consensus_cases=consensus,
        adjudicated_cases=adjudicated,
        conflict_cases=len(conflict_ids),
        conflict_issue_ids=conflict_ids[:50],
        overlap_completed_cases=overlap_completed,
    )


def group_projection(groups, placed, completed, *, case_ids=None):
    all_cases = list(case_ids) if case_ids is not None else list(placed)
    group_ids = [group["group_id"] for group in groups]
    totals = Counter((gid, name) for owners in placed.values() for gid, name in owners.items() if gid in group_ids)
    done = Counter((gid, name) for iid, owners in placed.items() for gid, name in owners.items()
                   if gid in group_ids and (iid, name) in completed)
    combinations = Counter(tuple(owners.get(gid) for gid in group_ids) for owners in placed.values())
    completed_cases = {iid for iid, _ in completed}
    by_group = {}
    union_covered_by_group = {}
    for group in groups:
        gid = group["group_id"]
        members = [dict(name=name, total=totals[gid, name], completed=done[gid, name])
                   for (g_key, name) in sorted(totals) if g_key == gid]
        by_group[gid] = members
        if len(groups) == 1:
            # Count Cases not actively placed in Group 1 because they were already completed in the set union.
            union_only = sum(1 for iid in all_cases if gid not in placed.get(iid, {}) and iid in completed_cases)
            union_covered_by_group[gid] = union_only
        else:
            union_covered_by_group[gid] = 0

    active_slots = sum(totals.values()) + sum(union_covered_by_group.values())
    active_completed = sum(done.values()) + sum(union_covered_by_group.values())
    return dict(
        case_count=len(all_cases),
        active_slots=active_slots,
        active_completed_slots=active_completed,
        groups=[dict(
            group_id=gid,
            members=by_group[gid],
            union_completed=union_covered_by_group[gid],
        ) for gid in group_ids],
        combinations=[dict(owners=list(owners), count=combinations[owners])
                      for owners in sorted(combinations, key=lambda names: tuple(name or "" for name in names))],
    )


def grouped_preview(groups, old_rows, new_rows, placed, evidence, *, old_placed=None):
    before, after = ({(r["issue_id"], r["assignee"]) for r in rows} for rows in (old_rows, new_rows))
    incoming = Counter(p for _, p in after - before)
    outgoing = Counter(p for _, p in before - after)
    old_counts = Counter(p for _, p in before)
    new_counts = Counter(p for _, p in after)
    active_after = Counter(name for owners in placed.values() for name in owners.values())
    active_before = Counter(name for owners in old_placed.values() for name in owners.values()) if old_placed else old_counts
    done = Counter(p for _, p in evidence["completed"])
    locked = Counter(p for _, p in evidence["protected"])
    active_done = Counter(
        name for iid, owners in placed.items() for name in owners.values()
        if (iid, name) in evidence["completed"]
    )
    all_people = sorted(
        old_counts.keys() | new_counts.keys()
        | {m["name"] for g in groups for m in g.get("members", []) if m.get("name")}
    )
    members = []
    for name in all_people:
        if not (old_counts[name] or new_counts[name] or active_after[name]):
            continue
        act_after = active_after[name]
        act_done = active_done[name]
        members.append(dict(
            name=name,
            before=old_counts[name],
            total_after=new_counts[name],
            active_before=active_before[name],
            active_after=act_after,
            completed=done[name],
            active_completed=act_done,
            extra_completed=max(0, done[name] - act_done),
            saved_pending=locked[name] - done[name],
            retained_pending=max(0, act_after - incoming[name] - act_done),
            pending_after=max(0, act_after - act_done),
            incoming=incoming[name],
            outgoing=outgoing[name],
        ))
    old_by_issue = defaultdict(list)
    for iid, name in before:
        old_by_issue[iid].append(name)
    new_by_issue = defaultdict(list)
    for iid, name in after:
        new_by_issue[iid].append(name)
    changes = [dict(issue_id=iid, before=sorted(old_by_issue[iid]), after=sorted(new_by_issue[iid]))
               for iid in sorted(placed) if set(new_by_issue[iid]) != set(old_by_issue[iid])]
    locks = evidence["coverage_locked"]
    projection = group_projection(groups, placed, evidence["completed"], case_ids=list(placed))
    return dict(
        group_coverage=projection,
        convergence=convergence_summary(list(placed), evidence),
        members=members,
        changes=changes,
        changed_cases=len(changes),
        total_slots=len(after),
        active_slots=projection["active_slots"],
        active_completed_slots=projection["active_completed_slots"],
        extra_retained_slots=max(0, len(after) - projection["active_slots"]),
        moved_slots=sum(incoming.values()),
        completed_slots=sum(done.values()),
        saved_pending_slots=sum(locked.values()) - sum(done.values()),
        movable_slots=max(0, projection["active_slots"] - projection["active_completed_slots"] - (sum(locked.values()) - sum(done.values()))),
        coverage_before=coverage_summary(Counter(iid for iid, _ in before), locks),
        coverage_after=coverage_summary(Counter(iid for iid, _ in after), locks),
    )
