"""Plan the number of independent assignments on each Case."""
from collections import Counter
import random


class CoverageConstraintError(ValueError):
    """Saved Case sizes or the specified groups constrain coverage."""


def coverage_summary(counts, locked=()):
    locked = set(counts).intersection(locked)
    cross_cases = sum(count > 1 for count in counts.values())
    locked_cross = sum(counts[iid] > 1 for iid in locked)
    adjustable = len(counts) - len(locked)
    return dict(case_count=len(counts), cross_cases=cross_cases, locked_cases=len(locked),
                locked_slots=sum(counts[iid] for iid in locked),
                min_cross_cases=locked_cross, max_cross_cases=locked_cross + adjustable,
                reviewer_counts=dict(Counter(counts.values())))


def plan_cross_coverage(counts, *, target, reviewers, seed, groups, recipients,
                        protected=(), locked=()):
    """Fix saved Case sizes and explicit groups, then keep as much coverage as possible."""
    if not isinstance(groups, list) or len(groups) > 100:
        raise ValueError("指定组合须为数组，最多 100 组 / Specify up to 100 cross-review groups")
    protected = set(protected)
    locked = set(locked)
    selected = {}
    by_count = []
    ranks = sorted(counts)
    random.Random(seed).shuffle(ranks)
    ranks.sort(key=lambda iid: counts[iid] == 1)
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("members"), list):
            raise ValueError("请选择交叉组合的成员 / Select members for each cross-review group")
        raw_members = group["members"]
        if not all(isinstance(name, str) and name.strip() for name in raw_members):
            raise ValueError("请选择有效成员 / Select valid members")
        members = tuple(sorted({name.strip().lower() for name in raw_members}))
        if len(members) < 2 or len(members) != len(raw_members):
            raise ValueError("每组至少两名不同成员 / Each group needs at least two distinct members")
        issue_ids = group.get("issue_ids") or []
        size = group.get("count")
        if not isinstance(issue_ids, list) or not all(isinstance(iid, str) and iid.strip() for iid in issue_ids):
            raise ValueError("请填写有效的 Case ID / Enter valid Case IDs")
        if issue_ids:
            if size is not None or len(set(issue_ids)) != len(issue_ids):
                raise ValueError("每组填写唯一的 Case ID 或指定数量 / Provide unique Case IDs or a count for each group")
            for iid in issue_ids:
                if iid not in counts or iid in selected:
                    raise ValueError("Case 必须在任务范围内且只属于一个指定组合 / A Case must be in scope and in only one specified group")
                selected[iid] = members
        elif type(size) is int and 0 < size <= len(counts):
            by_count.append((size, members))
        else:
            raise ValueError("请为每组填写 Case ID 或有效数量 / Enter Case IDs or a valid count for each group")

    for size, members in by_count:
        candidates = [iid for iid in ranks if iid not in locked and iid not in selected][:size]
        if len(candidates) != size:
            raise ValueError("可调整的 Case 不足以抽取指定数量 / Too few adjustable Cases for the requested group size")
        selected.update((iid, members) for iid in candidates)

    protected_by_issue = {}
    for iid, name in protected:
        protected_by_issue.setdefault(iid, set()).add(name)
    for iid, members in selected.items():
        saved = protected_by_issue.get(iid, set())
        expected = counts[iid] if iid in locked else reviewers
        if len(members) != expected or not saved.issubset(members):
            raise CoverageConstraintError(f"指定组合必须符合人数并保留已保存成员（{iid}） / The group must match the required headcount and retain saved owners ({iid})")
        if set(members) - saved - recipients:
            raise ValueError(f"指定组合需要能接收待办的成员（{iid}） / Group members must be eligible to receive pending work ({iid})")

    fixed = locked | selected.keys()
    planned = {iid: counts[iid] if iid in locked else reviewers for iid in fixed}
    minimum = sum(count > 1 for count in planned.values())
    spare = target - minimum
    maximum = minimum + len(counts) - len(fixed) if reviewers > 1 else minimum
    if target < minimum or target > maximum:
        raise CoverageConstraintError(f"当前交叉覆盖可调整至 {minimum}–{maximum} 个 Case，目标为 {target} / Cross-review coverage can be {minimum}–{maximum} Cases with the current protection and groups; requested {target}")
    for iid in ranks:
        if iid not in planned:
            planned[iid] = reviewers if spare else 1
            spare -= bool(spare)

    grouped = {}
    for iid, members in sorted(selected.items()):
        grouped.setdefault(members, []).append(iid)
    materialized = [dict(members=list(members), issue_ids=ids) for members, ids in grouped.items()]
    return planned, selected, materialized
