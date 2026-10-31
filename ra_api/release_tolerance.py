"""Versioned, Issue-level exception budget shared by submission and publication."""
from decimal import Decimal

POLICY = {"version": "issue_exceptions_v1", "maximum_abnormal_issues": 5,
          "minimum_coverage": 0.995, "comparison": ">"}


def assess(eligible_ids, abnormal_ids):
    eligible, abnormal = set(map(str, eligible_ids)), set(map(str, abnormal_ids))
    if not eligible or not abnormal <= eligible:
        raise ValueError("异常 Issue 必须属于非空的原始评测范围")
    valid = len(eligible - abnormal)
    if len(abnormal) > POLICY["maximum_abnormal_issues"] or Decimal(valid) <= Decimal(len(eligible)) * Decimal("0.995"):
        raise ValueError("异常 Issue 必须 ≤ 5 且有效 Issue 覆盖率 > 99.5%")
    return {"issue_count": len(eligible), "valid_issue_count": valid,
            "abnormal_issue_count": len(abnormal), "issue_coverage": valid / len(eligible)}


def validate_frozen(plan):
    audit = plan.get("issue_tolerance")
    if not audit or audit.get("policy") != POLICY:
        raise ValueError("Issue 异常容错策略缺失或不匹配")
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
                if (i.get("evaluation_exclusion") or {}).get("approved_by") == POLICY["version"]}
    mapped = {str(s["issue_id"]) for s in plan.get("scenarios", [])}
    if excluded != set(failed) or mapped != set(ids) - set(failed):
        raise ValueError("Issue 异常清单与场景映射不一致")
    return assess(ids, failed)
