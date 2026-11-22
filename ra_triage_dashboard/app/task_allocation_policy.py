"""Percentage-based workload allocation; percentages include cross-review slots."""
from collections import Counter, deque
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from .human_label_policy import digest
from .work_split import distribute_issue_ids


def review_percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("请填写每人的 review 比例 / Enter a review percentage for every member")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= 100 or number * 100 != (number * 100).to_integral_value():
            raise InvalidOperation
    except InvalidOperation as exc:
        raise ValueError("个人比例须为 0–100%，最多两位小数 / Percentages must be 0–100 with at most two decimal places") from exc
    return float(number)


def percentage_weights(people):
    return {p["name"]: int(Decimal(str(p["review_percent"])) * 100) for p in people}


def apportion(weights, total, *, minima=None, maxima=None):
    """Largest remainder: deterministic integer quotas with an exact total."""
    denominator = sum(weights.values())
    if not denominator:
        raise ValueError("至少一人的比例须大于零 / At least one percentage must be positive")
    lower = {name: (minima or {}).get(name, 0) for name in weights}
    upper = {name: (maxima or {}).get(name, total) if weights[name] else 0 for name in weights}
    if sum(lower.values()) > total or sum(upper.values()) < total or any(lower[p] > upper[p] for p in weights):
        raise ValueError("个人比例无法满足当前分配约束 / Personal shares cannot satisfy the current allocation constraints")
    quotas = {name: min(upper[name], max(lower[name], total * weight // denominator)) for name, weight in weights.items()}
    delta = total - sum(quotas.values())
    while delta:
        direction = 1 if delta > 0 else -1
        eligible = [p for p in weights if quotas[p] < upper[p]] if delta > 0 else [p for p in weights if quotas[p] > lower[p]]
        name = min(eligible, key=lambda p: (direction * (quotas[p] * denominator - total * weights[p]), p))
        quotas[name] += direction
        delta -= direction
    return quotas


def validate_percentages(people, *, reviewers, overlap, roles=None):
    weights = percentage_weights(people)
    if sum(weights.values()) != 10000:
        raise ValueError("个人 review 比例合计须为 100% / Review percentages must total 100%")
    effective = 1 + Decimal(str(overlap)) * (reviewers - 1)
    # Two-decimal percentages must represent thirds (33.34/33.33/33.33).
    # Exact integer allocation still enforces the actual per-Case capacity.
    maximum = int((Decimal(10000) / effective).to_integral_value(rounding=ROUND_CEILING))
    if any(weight > maximum for weight in weights.values()):
        limit = f"{maximum / 100:g}%"
        raise ValueError(f"当前交叉设置下个人比例最多为 {limit}，同一 Case 不能重复分配给一人 / Each share is limited to {limit} under these cross-review settings; a person cannot review the same Case twice")
    if overlap > 0 and sum(weight > 0 for weight in weights.values()) < reviewers:
        raise ValueError("正比例成员不足以满足交叉人数 / Too few members have a positive percentage for cross-review")
    if roles:
        for role in ("rd", "te"):
            role_weight = sum(weight for name, weight in weights.items() if roles[name] == role)
            if role_weight < 10000 // reviewers:
                raise ValueError("RD 和 TE 的比例必须分别足以覆盖每个 Case / RD and TE must each receive enough work to cover every Case")


def proportional_quotas(people, total, case_count, reviewers, roles=None):
    weights = percentage_weights(people)
    if not roles:
        return apportion(weights, total, maxima={name: case_count for name in weights})
    # Round roles first so a one-Case packet cannot round both slots into RD.
    grouped = {role: {name: w for name, w in weights.items() if roles[name] == role} for role in ("rd", "te")}
    totals = apportion({role: sum(pool.values()) for role, pool in grouped.items()}, total,
        minima={role: case_count for role in grouped},
        maxima={role: case_count * min(reviewers - 1, sum(w > 0 for w in pool.values())) for role, pool in grouped.items()})
    return {name: count for role, pool in grouped.items()
            for name, count in apportion(pool, totals[role], maxima={name: case_count for name in pool}).items()}


def _role_quota_rows(issue_ids, quotas, roles, reviewers, seed):
    """Bipartite flow realizes exact quotas, unique reviewers and RD+TE coverage."""
    graph = []
    def node():
        graph.append([])
        return len(graph) - 1
    def edge(source, target, capacity):
        forward = [target, capacity, len(graph[target])]
        reverse = [source, 0, len(graph[source])]
        graph[source].append(forward)
        graph[target].append(reverse)
        return forward
    source, sink = node(), node()
    names = sorted(quotas, key=lambda name: digest([seed, name]))
    person_nodes = {name: node() for name in names}
    for name in names:
        edge(source, person_nodes[name], quotas[name])
    links = []
    for iid in sorted(issue_ids, key=lambda value: digest([seed, value])):
        case, rd, te = node(), node(), node()
        edge(rd, case, reviewers - 1)
        edge(te, case, reviewers - 1)
        edge(case, sink, reviewers)
        for name in names:
            if quotas[name]:
                links.append((iid, name, edge(person_nodes[name], rd if roles[name] == "rd" else te, 1)))
    flow = 0
    while True:
        levels = [-1] * len(graph)
        levels[source] = 0
        queue = deque([source])
        while queue:
            u = queue.popleft()
            for v, capacity, _ in graph[u]:
                if capacity and levels[v] < 0:
                    levels[v] = levels[u] + 1
                    queue.append(v)
        if levels[sink] < 0:
            break
        cursors = [0] * len(graph)
        def augment(u, amount):
            if u == sink:
                return amount
            while cursors[u] < len(graph[u]):
                e = graph[u][cursors[u]]
                v, capacity, reverse = e
                if capacity and levels[v] == levels[u] + 1:
                    sent = augment(v, min(amount, capacity))
                    if sent:
                        e[1] -= sent
                        graph[v][reverse][1] += sent
                        return sent
                cursors[u] += 1
            return 0
        while sent := augment(source, len(issue_ids) * reviewers):
            flow += sent
    if flow != len(issue_ids) * reviewers:
        raise ValueError("当前比例无法满足每个 Case 的 RD、TE 和交叉人数要求 / These percentages cannot satisfy RD, TE and reviewer requirements on every Case")
    owners = {}
    for iid, name, e in links:
        if e[1] == 0:
            owners.setdefault(iid, []).append(name)
    return [
        dict(issue_id=iid, assignee=name, assignment_kind="base" if index == 0 else "cross", ordinal=ordinal)
        for ordinal, (iid, people) in enumerate(owners.items(), 1)
        for index, name in enumerate(sorted(people, key=lambda p: (roles[p] != "rd", digest([seed, iid, p]))))
    ]


def allocate_percentages(issue_ids, people, *, reviewers, overlap, seed, roles=None, previous=()):
    if not issue_ids:
        return []
    if previous:
        # Persisted percentages are cumulative targets, not per-packet quotas.
        weights = percentage_weights(people)
        names = [name for name, weight in weights.items() if weight > 0]
        counts = Counter(name for item in previous for name in item["assignees"])
        independent_roles = bool(roles) and reviewers == 2
        pool_weights = {role: sum(weights[p] for p in names if roles[p] == role)
                        for role in ("rd", "te")} if independent_roles else {}
        pool_counts = {role: Counter(p for item in previous for p in item["assignees"]
            if item.get("roles", {}).get(p, roles.get(p)) == role)
            for role in ("rd", "te")} if independent_roles else {}
        total_cases = len(previous)
        cross_count = sum(len(item["assignees"]) > 1 for item in previous)
        slots = sum(counts.values())
        rows = []
        for iid in sorted(issue_ids, key=lambda value: digest([seed, value])):
            total_cases += 1
            cross = reviewers > 1 and cross_count < round(total_cases * overlap)
            required = reviewers if cross else 1
            slots += required
            owners = []
            for index in range(required):
                mandatory_role = ("rd", "te")[index] if roles and index < 2 else None
                eligible = [p for p in names if p not in owners and (not mandatory_role or roles[p] == mandatory_role)]
                owner = min(eligible, key=lambda p: (
                    pool_counts[mandatory_role][p] * pool_weights[mandatory_role] - total_cases * weights[p]
                    if independent_roles else counts[p] * 10000 - slots * weights[p],
                    digest([seed, iid, p])))
                owners.append(owner)
                counts[owner] += 1
                if independent_roles:
                    pool_counts[mandatory_role][owner] += 1
            cross_count += cross
            rows.extend(dict(issue_id=iid, assignee=name, assignment_kind="base" if index == 0 else "cross",
                             ordinal=index + 1) for index, name in enumerate(owners))
        return rows
    total = len(issue_ids) + round(len(issue_ids) * overlap) * (reviewers - 1)
    quotas = proportional_quotas(people, total, len(issue_ids), reviewers, roles)
    if roles:
        return _role_quota_rows(issue_ids, quotas, roles, reviewers, seed)
    # Reuse the established fixed-quota allocator, including its feasibility checks.
    numeric_seed = seed if isinstance(seed, int) else int(digest(seed)[:16], 16)
    plan = distribute_issue_ids(issue_ids, [dict(name=p["name"], count=quotas[p["name"]]) for p in people],
                                seed=numeric_seed, reviewers_per_issue=reviewers, overlap_ratio=overlap)
    return [dict(assignee=p["name"], **item) for p in plan for item in p.get("items", [
        dict(issue_id=iid, assignment_kind="base", ordinal=index)
        for index, iid in enumerate(p["issue_ids"], 1)
    ])]
