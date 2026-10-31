"""Versioned, Issue-level exception budget shared by submission and publication."""
from decimal import Decimal

LEGACY_POLICY = {"version": "issue_exceptions_v1", "maximum_abnormal_issues": 5,
          "minimum_coverage": 0.995, "comparison": ">"}
POLICY = {"version": "issue_coverage_v2", "maximum_abnormal_issues": None,
          "minimum_coverage": 0.98, "comparison": ">"}


def grade(eligible_ids, abnormal_ids):
    eligible, abnormal = set(map(str, eligible_ids)), set(map(str, abnormal_ids))
    if not eligible or not abnormal <= eligible:
        raise ValueError("异常 Issue 必须属于非空的原始评测范围")
    return grade_counts(len(eligible), len(abnormal))


def grade_counts(total, abnormal):
    if type(total) is not int or type(abnormal) is not int or total <= 0 or not 0 <= abnormal <= total:
        raise ValueError("Invalid Issue coverage counts")
    valid = total - abnormal
    normal = abnormal <= 5 and Decimal(valid) > Decimal(total) * Decimal("0.995")
    level = "normal" if normal else "degraded" if Decimal(valid) > Decimal(total) * Decimal("0.98") else "blocked"
    return {"issue_count":total, "valid_issue_count":valid,
            "abnormal_issue_count":abnormal, "issue_coverage":valid/total, "quality_level":level}


def policy_for(plan):
    policy = (plan.get("issue_tolerance") or {}).get("policy")
    if policy not in (POLICY, LEGACY_POLICY):
        raise ValueError("Issue 异常容错策略缺失或不匹配")
    return policy


def assess(eligible_ids, abnormal_ids, policy=None):
    policy = POLICY if policy is None else policy
    if policy not in (POLICY, LEGACY_POLICY):
        raise ValueError("未知 Issue 覆盖率策略")
    eligible, abnormal = set(map(str, eligible_ids)), set(map(str, abnormal_ids))
    if not eligible or not abnormal <= eligible:
        raise ValueError("异常 Issue 必须属于非空的原始评测范围")
    valid = len(eligible - abnormal)
    threshold = Decimal(len(eligible)) * Decimal(str(policy["minimum_coverage"]))
    limit = policy["maximum_abnormal_issues"]
    if ((limit is not None and len(abnormal) > limit)
            or (Decimal(valid) <= threshold if policy["comparison"] == ">" else Decimal(valid) < threshold)):
        raise ValueError("异常 Issue 必须 ≤ 5 且有效 Issue 覆盖率 > 99.5%" if policy == LEGACY_POLICY
                         else "有效 Issue 覆盖率必须 > 98%")
    return grade(eligible, abnormal)


def validate_frozen(plan):
    audit = plan.get("issue_tolerance")
    policy = policy_for(plan)
    ids = audit.get("eligible_issue_ids", [])
    failures = audit.get("preparation_failures", [])
    failed = [str(f["issue_id"]) for f in failures]
    rows = plan.get("issues", [])
    row_ids = [str(i["issue_id"]) for i in rows]
    if (len(ids) != len(set(ids)) or len(failed) != len(set(failed))
            or len(row_ids) != len(set(row_ids)) or not set(ids) <= set(row_ids)
            or audit.get("population_hash") != plan.get("population_hash")
            or any(f.get("reason") not in ("missing_bag", "upstream_error") for f in failures)):
        raise ValueError("Issue 异常审计身份不一致")
    excluded = {str(i["issue_id"]) for i in rows
                if (i.get("evaluation_exclusion") or {}).get("approved_by") == policy["version"]}
    mapped = {str(s["issue_id"]) for s in plan.get("scenarios", [])}
    if excluded != set(failed) or mapped != set(ids) - set(failed):
        raise ValueError("Issue 异常清单与场景映射不一致")
    return assess(ids, failed, policy)
