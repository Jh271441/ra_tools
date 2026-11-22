"""Reallocate untouched slots, preserving saved work and per-Case coverage.

All counts are derived from assignments/evidence. There is no new workflow state.
"""
from collections import Counter, defaultdict, deque
from fractions import Fraction
from heapq import heappop, heappush


def bounded_shares(weights, total, lower=None, upper=None):
    """Water filling, then largest remainders; zero weight retains its lower bound."""
    lower = {p: (lower or {}).get(p, 0) for p in weights}
    upper = {p: (upper or {}).get(p, total) if weights[p] else lower[p] for p in weights}
    if (any(lower[p] > upper[p] for p in weights)
            or sum(lower.values()) > total or sum(upper.values()) < total):
        raise ValueError("可接收人员不足，无法覆盖全部待办 / Not enough eligible recipients to cover all pending work")
    if total == sum(lower.values()):
        return lower
    # The monotone, piecewise linear sum has breakpoints L/w and U/w.
    points = sorted({Fraction(bound[p], weights[p])
                     for p in weights if weights[p] for bound in (lower, upper)})
    fixed = sum(lower[p] for p in weights if not weights[p])
    for left, right in zip([Fraction(0), *points], [*points, None]):
        mid = left + 1 if right is None else (left + right) / 2
        active = [p for p in weights if weights[p] and lower[p] <= mid * weights[p] <= upper[p]]
        constant = fixed + sum(lower[p] if mid * weights[p] < lower[p] else upper[p]
                               for p in weights if weights[p] and p not in active)
        if active:
            scale = Fraction(total - constant, sum(weights[p] for p in active))
            if scale < left or right is not None and scale > right:
                continue
            raw = {p: min(Fraction(upper[p]), max(Fraction(lower[p]), scale * weights[p])) for p in weights}
            break
        if constant == total:
            raw = {p: Fraction(min(upper[p], max(lower[p], mid * weights[p]))) for p in weights}
            break
    else:
        raise ValueError("无法计算分配配额 / Unable to calculate allocation quotas")
    quotas = {p: int(value) for p, value in raw.items()}
    remainder = total - sum(quotas.values())
    for p in sorted(weights, key=lambda p: (-(raw[p] - quotas[p]), p)):
        if remainder and quotas[p] < upper[p] and weights[p]:
            quotas[p] += 1
            remainder -= 1
    assert remainder == 0
    return quotas


class _Flow:
    """Integral min-cost flow; blocking flow batches equal-cost shortest paths."""
    def __init__(self):
        self.graph = []

    def node(self):
        self.graph.append([])
        return len(self.graph) - 1

    def edge(self, u, v, capacity, cost=0):
        edge = [v, capacity, cost, len(self.graph[v])]
        self.graph[u].append(edge)
        self.graph[v].append([u, 0, -cost, len(self.graph[u]) - 1])
        return edge

    def send(self, source, sink, required):
        graph = self.graph
        potential = [0] * len(graph)
        delivered = 0
        while delivered < required:
            dist = [float("inf")] * len(graph)
            dist[source] = 0
            queue = [(0, source)]
            while queue:
                d, u = heappop(queue)
                if d != dist[u]:
                    continue
                for v, capacity, cost, _ in graph[u]:
                    nd = d + cost + potential[u] - potential[v]
                    if capacity and nd < dist[v]:
                        dist[v] = nd
                        heappush(queue, (nd, v))
            if dist[sink] == float("inf"):
                raise ValueError("部分 Case 无法满足不重复负责人及 RD/TE 要求，请增加接收人员 / Some Cases cannot satisfy unique-reviewer or RD/TE coverage; add eligible recipients")
            for u, d in enumerate(dist):
                if d != float("inf"):
                    potential[u] += d
            # Dinic on the zero reduced-cost residual graph avoids one Dijkstra
            # per Case, including on several-thousand-Case version tasks.
            while True:
                levels = [-1] * len(graph)
                levels[source] = 0
                queue = deque([source])
                while queue:
                    u = queue.popleft()
                    for v, capacity, cost, _ in graph[u]:
                        if capacity and levels[v] < 0 and cost + potential[u] - potential[v] == 0:
                            levels[v] = levels[u] + 1
                            queue.append(v)
                if levels[sink] < 0:
                    break
                cursor = [0] * len(graph)

                def push(u, amount):
                    if u == sink:
                        return amount
                    while cursor[u] < len(graph[u]):
                        e = graph[u][cursor[u]]
                        v, capacity, cost, reverse = e
                        if capacity and levels[v] == levels[u] + 1 and cost + potential[u] - potential[v] == 0:
                            sent = push(v, min(amount, capacity))
                            if sent:
                                e[1] -= sent
                                graph[v][reverse][1] += sent
                                return sent
                        cursor[u] += 1
                    return 0
                while sent := push(source, required - delivered):
                    delivered += sent
                if delivered == required:
                    return


def reallocate_slots(rows, weights, *, basis, protected, completed=(), roles=None,
                     captured_roles=None, forbidden=(), required_counts=None, pinned_members=None,
                     fixed_quotas=None):
    """Exact coverage, nearest feasible integer quotas, then minimum owner moves."""
    if basis not in {"remaining", "total"}:
        raise ValueError("分配基数无效 / Invalid allocation basis")
    protected, completed, forbidden = set(protected), set(completed), set(forbidden)
    before = {(r["issue_id"], r["assignee"]): r for r in rows}
    if len(before) != len(rows) or not protected <= before.keys():
        raise ValueError("原分配或保护记录不完整 / Inconsistent assignment or protection records")
    names = sorted(set(weights) | {p for _, p in before})
    weights = {p: weights.get(p, 0) for p in names}
    locked = Counter(p for _, p in protected)
    done = Counter(p for _, p in completed)
    groups = defaultdict(list)
    for row in rows:
        groups[row["issue_id"]].append(row)
    counts = required_counts if required_counts is not None else {iid: len(group) for iid, group in groups.items()}
    pinned_members = pinned_members or {}
    fixed_quotas = fixed_quotas or {}
    protected_by_issue = defaultdict(set)
    for iid, p in protected:
        protected_by_issue[iid].add(p)
    eligible = {}
    capacity = Counter()
    for iid, required in counts.items():
        owners = protected_by_issue[iid]
        remaining = required - len(owners)
        eligible[iid] = [p for p in names if weights[p] > 0 and p not in owners
                         and (iid, p) not in forbidden
                         and (iid not in pinned_members or p in pinned_members[iid])
                         and (not roles or roles.get(p) in {"rd", "te"})] if remaining else []
        capacity.update(eligible[iid])
    count = sum(counts.values())
    remaining_count = count - len(protected)
    independent_roles = bool(roles) and all(required == 2 for required in counts.values())
    if independent_roles:
        # With one RD and one TE position per Case these are two real pools.
        # A completed RD position must not reduce the TE pool's pending budget.
        quota, ideal = dict.fromkeys(names, 0), dict.fromkeys(names, 0)
        for role in ("rd", "te"):
            pool_weights = {p: weights[p] if roles.get(p) == role else 0 for p in names}
            pool_locked = Counter(p for iid, p in protected if (captured_roles or {}).get((iid, p)) == role)
            pool_capacity = {p: capacity[p] if pool_weights[p] else 0 for p in names}
            pool_remaining = len(groups) - sum(pool_locked.values())
            pool_size = pool_remaining if basis == "remaining" else len(groups)
            shares = bounded_shares(pool_weights, pool_size,
                lower=pool_locked if basis == "total" else None,
                upper={p: pool_capacity[p] + (pool_locked[p] if basis == "total" else 0) for p in names})
            for p in names:
                quota[p] += shares[p] - (pool_locked[p] if basis == "total" else 0)
                if sum(pool_weights.values()):
                    ideal[p] += pool_size * pool_weights[p] / sum(pool_weights.values())
    elif basis == "remaining":
        quota = bounded_shares(weights, remaining_count, upper={p: capacity[p] for p in names})
        ideal = {p: remaining_count * weights[p] / sum(weights.values()) for p in names}
    else:
        final = bounded_shares(weights, count, locked, {p: locked[p] + capacity[p] for p in names})
        quota = {p: final[p] - locked[p] for p in names}
        ideal = {p: count * weights[p] / sum(weights.values()) for p in names}
    flow = _Flow()
    source, sink = flow.node(), flow.node()
    people = {p: flow.node() for p in names}
    for p in names:
        if p in fixed_quotas:
            flow.edge(people[p], sink, fixed_quotas[p])
            continue
        # Prefer filling exact quotas before balancing the remaining shares.
        quota_cost = (remaining_count + 1) ** 2 if fixed_quotas else 0
        flow.edge(people[p], sink, quota[p], quota_cost)
        # A quota deviation costs more than every possible owner transfer.
        flow.edge(people[p], sink, max(0, capacity[p] - quota[p]), quota_cost + remaining_count + 1)
    links = []
    for iid, group in sorted(groups.items()):
        frozen = [r for r in group if (iid, r["assignee"]) in protected]
        left = counts[iid] - len(frozen)
        if roles:
            frozen_roles = [(captured_roles or {}).get((iid, r["assignee"])) for r in frozen]
            if any(role not in {"rd", "te"} for role in frozen_roles):
                raise ValueError("已有记录缺少可靠的历史角色，暂不能调整 / Saved work is missing a reliable captured role")
            missing = {role: int(role not in frozen_roles) for role in ("rd", "te")}
            if sum(missing.values()) > left:
                raise ValueError("已有分配不满足 RD/TE 覆盖 / Existing assignments do not satisfy RD/TE coverage")
        if not left:
            continue
        case = flow.node()
        flow.edge(source, case, left)
        role_nodes = {}
        if roles:
            for role, other in (("rd", "te"), ("te", "rd")):
                role_nodes[role] = flow.node()
                flow.edge(case, role_nodes[role], left - missing[other])
        for p in eligible[iid]:
            start = role_nodes[roles[p]] if roles else case
            # Retaining a slot keeps all row metadata, including captured roles.
            if roles and (iid, p) in before and (captured_roles or {}).get((iid, p)) != roles[p]:
                continue
            links.append((iid, p, flow.edge(start, people[p], 1, 0 if (iid, p) in before else 1)))
    flow.send(source, sink, remaining_count)
    selected = set(protected) | {(iid, p) for iid, p, edge in links if edge[1] == 0}
    new_by_issue = defaultdict(list)
    for iid, p in selected - before.keys():
        new_by_issue[iid].append(p)
    result = []
    for iid, group in sorted(groups.items()):
        retained = [r for r in group if (iid, r["assignee"]) in selected]
        vacancies = sorted((r for r in group if (iid, r["assignee"]) not in selected),
                           key=lambda r: (r["assignment_kind"] != "base", r["ordinal"], r["assignee"]))
        new_people = sorted(new_by_issue[iid])
        if counts[iid] == len(group):
            assert len(vacancies) == len(new_people)
            result.extend(retained)
            result.extend(dict(issue_id=iid, assignee=p, assignment_kind=old["assignment_kind"], ordinal=old["ordinal"])
                          for p, old in zip(new_people, vacancies))
            continue
        # Only untouched Cases may change size. Preserve retained ordering and
        # ensure that the resized Case still has one base assignment.
        positions = [*sorted(retained, key=lambda r: r["assignment_kind"] != "base"),
                     *(dict(issue_id=iid, assignee=p, ordinal=group[0]["ordinal"]) for p in new_people)]
        result.extend({**row, "assignment_kind": "base" if index == 0 else "cross"}
                      for index, row in enumerate(positions))
    after_counts = Counter(p for _, p in selected)
    if any(after_counts[p] != amount for p, amount in fixed_quotas.items()):
        raise ValueError("固定数量与指定组合无法同时满足 / Fixed quotas and specified groups cannot both be satisfied")
    before_counts = Counter(p for _, p in before)
    incoming = Counter(p for _, p in selected - before.keys())
    outgoing = Counter(p for _, p in before.keys() - selected)
    summary = [dict(
        name=p, weight=weights[p], before=before_counts[p], completed=done[p],
        saved_pending=locked[p] - done[p], movable_after=after_counts[p] - locked[p],
        pending_after=after_counts[p] - done[p], total_after=after_counts[p],
        incoming=incoming[p], outgoing=outgoing[p], ideal=ideal[p],
        quota=quota[p], actual_percent=100 * after_counts[p] / count if count else 0,
        pool_role=roles.get(p, "") if independent_roles else "",
        pool_percent=(100 * weights[p] / sum(weights[n] for n in names if roles.get(n) == roles.get(p))
                      if independent_roles and weights[p] else None),
        constrained=(after_counts[p] - locked[p] != quota[p]
                     or abs((after_counts[p] - locked[p] if basis == "remaining" else after_counts[p]) - ideal[p]) >= 1
                     or independent_roles and abs(ideal[p] - (remaining_count if basis == "remaining" else count)
                                                   * weights[p] / sum(weights.values())) >= 1),
    ) for p in names]
    return result, summary
