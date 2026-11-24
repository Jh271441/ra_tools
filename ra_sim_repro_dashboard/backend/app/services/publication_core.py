"""Core audited publication validation and batch lookup (Tier 4a, strictly acyclic)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.domain.coverage import (
    LEGACY_POLICY,
    POLICY,
    assess,
    coverage_policy,
    policy_for,
    validate_frozen,
)
from app.domain.hashing import audit_hash, population_identity
from app.domain.metrics import cohort_for_issue, summarize_population
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services.read_views import read_projection

STANDARD_VERSION = "primary_execution_v1"
MIN_COVERAGE = 0.995
LEGACY_AUTO_STANDARD_VERSION = "audited_coverage_v2"
LEGACY_BUDGET_STANDARD_VERSION = "issue_budget_v3"
AUTO_STANDARD_VERSION = "issue_coverage_v4"


def validate_standard(payload):
    """One standard for audited publications; reruns are diagnostic only."""
    audit = payload.get("result_import") or {}
    progress = payload.get("execution_progress") or {}
    period = payload.get("period") or {}
    total = audit.get("scenario_count", 0)
    valid = audit.get("valid_scenario_count", 0)
    failures = audit.get("failures") or []
    if period.get("verified") is not True or period.get("status") != "completed":
        raise ValueError("Release cycle is not verified and closed")
    if (
        not audit.get("primary")
        or audit.get("primary_job_id") != payload.get("job_id")
        or audit.get("population_hash") != payload.get("population_hash")
        or audit.get("binary_id") != payload.get("binary_id")
    ):
        raise ValueError("Primary execution identity mismatch")
    if (
        progress.get("state") != "COMPLETED"
        or progress.get("job_id") != payload.get("job_id")
        or progress.get("total") != total
        or any(progress.get(k, 0) != 0 for k in ("running", "queued", "unknown", "cancelled"))
    ):
        raise ValueError("Primary execution has unfinished or cancelled tasks")
    expected = {str(s["scenario_id"]) for s in payload.get("scenarios", [])}
    results = payload.get("results") or {}
    details = payload.get("scenario_results") or {}
    excluded = {str(f["scenario_id"]) for f in failures}
    if (
        not total
        or len(expected) != total
        or len(payload.get("scenarios", [])) != total
        or set(details) != expected
        or set(results) | excluded != expected
        or set(results) & excluded
        or len(excluded) != len(failures)
        or valid != len(results)
        or len(failures) != audit.get("missing_scenario_count")
        or progress.get("completed") != valid
        or progress.get("failed") != len(failures)
        or any(f.get("status") != "failed" for f in failures)
        or any(
            details[s].get("errors") or details[s].get("status") != "result_ready" for s in results
        )
        or not audit.get("subset_summary", {}).get("available")
    ):
        raise ValueError(
            "Only execution failures may be excluded; valid results must pass artifact checks"
        )
    if valid * 1000 < total * 995:
        raise ValueError("Valid result coverage must be at least 99.5%")
    return {
        "standard_version": STANDARD_VERSION,
        "minimum_coverage": MIN_COVERAGE,
        "coverage": valid / total,
    }


def approve_publication(db, batch, population_hash, excluded_ids, reason):
    p = batch.payload
    standard = validate_standard(p)
    audit = p.get("result_import") or {}
    excluded = sorted(str(s) for s in excluded_ids)
    failures = audit.get("failures") or []
    if not reason or not audit.get("primary") or audit.get("primary_job_id") != p.get("job_id"):
        raise ValueError("An explicit primary-execution approval is required")
    if (
        p.get("population_hash") != population_hash
        or audit.get("population_hash") != population_hash
    ):
        raise ValueError("Frozen evaluation population mismatch")
    if not any(
        (s.population_hash or population_identity(s.payload)) == population_hash
        for s in db.scalars(
            select(ReleaseIssueSnapshot).where(ReleaseIssueSnapshot.release == batch.release)
        )
    ):
        raise ValueError("Original audited source snapshot is missing")
    if (
        len(set(excluded)) != len(excluded)
        or sorted(str(f["scenario_id"]) for f in failures) != excluded
        or any(f.get("status") != "failed" for f in failures)
        or len(excluded) != audit.get("missing_scenario_count")
        or not audit.get("subset_summary", {}).get("available")
    ):
        raise ValueError("Only the explicitly listed execution failures may be excluded")
    approval = {
        **standard,
        "policy": "primary_valid_samples",
        "primary_job_id": p["job_id"],
        "population_hash": population_hash,
        "excluded_scenario_ids": excluded,
        "comparison_required": False,
        "reason": reason,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "audit_hash": audit_hash(p),
    }
    batch.payload = {**p, "publication_approval": approval}
    return approval


def validate_coverage_standard(payload, minimum_coverage=0.98, *, issue_budget=True):
    """Allow audited exceptions, never count them as successes or TP/FP/FN."""
    threshold = coverage_policy({"result_publication": {"minimum_coverage": minimum_coverage}})[
        "minimum_coverage"
    ]
    audit = payload.get("result_import") or {}
    progress = payload.get("execution_progress") or {}
    period = payload.get("period") or {}
    if period.get("verified") is not True or period.get("status") != "completed":
        raise ValueError("Release 周期尚未核实并关闭")
    if payload.get("acceptance_only"):
        raise ValueError("验收测试批次不能发布业务指标")
    if (
        not audit.get("primary")
        or audit.get("release") != payload.get("release")
        or audit.get("primary_job_id") != payload.get("job_id")
        or audit.get("population_hash") != payload.get("population_hash")
        or audit.get("binary_id") != payload.get("binary_id")
    ):
        raise ValueError("主结果版本、Job、Binary 或人口身份不匹配")
    if audit.get("comparison", {}).get("conflicts"):
        raise ValueError("多次执行存在结果差异，需明确主结果发布决策")
    scenes = payload.get("scenarios") or []
    expected = {str(s["scenario_id"]) for s in scenes}
    total = audit.get("scenario_count")
    details = payload.get("scenario_results") or {}
    results = payload.get("results") or {}
    failures = audit.get("failures") or []
    excluded = {str(f["scenario_id"]) for f in failures}
    valid = len(results)
    if (
        type(total) is not int
        or total <= 0
        or len(expected) != total
        or len(scenes) != total
        or set(details) != expected
        or set(results) | excluded != expected
        or set(results) & excluded
        or len(excluded) != len(failures)
        or audit.get("valid_scenario_count") != valid
        or audit.get("missing_scenario_count") != len(excluded)
    ):
        raise ValueError("核验结果未完整覆盖原始场景人口")
    if (
        progress.get("job_id") != payload.get("job_id")
        or progress.get("total") != total
        or progress.get("state") != "COMPLETED"
        or any(progress.get(k, 0) != 0 for k in ("running", "queued", "unknown", "cancelled"))
    ):
        raise ValueError("Job 尚未结束或存在取消任务，继续跟踪")
    execution_failed = sum(f.get("status") == "failed" for f in failures)
    if (
        progress.get("completed") != total - execution_failed
        or progress.get("failed") != execution_failed
        or any(
            f.get("status") not in ("failed", "quality_failed")
            or not f.get("errors")
            or details[str(f["scenario_id"])]
            != {k: v for k, v in f.items() if k not in ("scenario_id", "issue_id")}
            for f in failures
        )
        or any(
            details[s].get("errors")
            or details[s].get("status") != "result_ready"
            or not all(isinstance(results[s].get(k), bool) for k in ("sim_triggered", "reproduced"))
            or results[s].get("precision_label") not in ("TP", "FP", "FN", "TN")
            for s in results
        )
    ):
        raise ValueError("成功、失败与质量异常计数或核验明细不一致")
    invalid_issues = {str(s["issue_id"]) for s in scenes if str(s["scenario_id"]) in excluded}
    subset = summarize_population(
        [i for i in payload["issues"] if str(i["issue_id"]) not in invalid_issues],
        [s for s in scenes if str(s["issue_id"]) not in invalid_issues],
        results,
    )
    full = summarize_population(payload["issues"], scenes, results)
    issue_total, issue_valid = full["eligible"], subset["eligible"]
    if (
        full["unclassified"]
        or not subset["available"]
        or not issue_total
        or any(
            subset.get(k) != audit.get("subset_summary", {}).get(k)
            for k in ("eligible", "tp", "fp", "fn", "tn", "precision", "recall", "sim_repro_rate")
        )
    ):
        raise ValueError("有效样本指标或 GT 人口核验不一致")
    tolerance = {}
    if issue_budget:
        frozen_policy = policy_for(payload) if "issue_tolerance" in payload else LEGACY_POLICY
        original = []
        for row in payload["issues"]:
            source = dict(row)
            if (source.get("evaluation_exclusion") or {}).get("approved_by") == frozen_policy[
                "version"
            ]:
                source.pop("evaluation_exclusion")
            if cohort_for_issue(source):
                original.append(str(source["issue_id"]))
        if len(original) != len(set(original)):
            raise ValueError("原始有效 Issue 重复")
        prep_ids = set()
        if "issue_tolerance" in payload:
            validate_frozen(payload)
            frozen = payload["issue_tolerance"]
            if set(original) != set(frozen["eligible_issue_ids"]):
                raise ValueError("原始 GT 与冻结 Issue 分母不一致")
            prep_ids = {str(f["issue_id"]) for f in frozen["preparation_failures"]}
        elif any(
            (i.get("evaluation_exclusion") or {}).get("approved_by") == frozen_policy["version"]
            for i in payload["issues"]
        ):
            raise ValueError("缺少准备阶段异常审计")
        tolerance = assess(original, prep_ids | invalid_issues, frozen_policy)
        issue_total = tolerance["issue_count"]
        if issue_valid != tolerance["valid_issue_count"]:
            raise ValueError("有效 Issue 指标分母与异常审计不一致")
        value, required = Decimal(issue_valid), Decimal(issue_total) * Decimal(str(threshold))
        if value < required or (frozen_policy["comparison"] == ">" and value == required):
            raise ValueError(f"有效 Issue 覆盖率必须 {frozen_policy['comparison']} {threshold:.1%}")
        tolerance.update(
            maximum_abnormal_issues=frozen_policy["maximum_abnormal_issues"],
            excluded_issue_ids=sorted(prep_ids | invalid_issues),
            comparison=frozen_policy["comparison"],
        )
    elif Decimal(valid) < Decimal(total) * Decimal(str(threshold)) or Decimal(
        issue_valid
    ) < Decimal(issue_total) * Decimal(str(threshold)):
        raise ValueError(f"有效场景和 Issue 覆盖率均需达到 {threshold:.1%}")
    return {
        **tolerance,
        "standard_version": AUTO_STANDARD_VERSION if issue_budget else LEGACY_AUTO_STANDARD_VERSION,
        "minimum_coverage": threshold,
        "coverage": valid / total,
        "issue_coverage": issue_valid / issue_total,
        "valid_issue_count": issue_valid,
        "issue_count": issue_total,
        "execution_failed_count": execution_failed,
        "quality_failed_count": len(failures) - execution_failed,
    }


def publication(batch):
    p = batch.payload
    approval = p.get("publication_approval") or {}
    audit = p.get("result_import") or {}
    if (
        approval.get("policy") not in ("primary_valid_samples", "audited_valid_samples")
        or not audit.get("primary")
        or approval.get("audit_hash") != audit_hash(p)
    ):
        return None
    try:
        standard = (
            validate_coverage_standard(
                p,
                approval.get("minimum_coverage"),
                issue_budget=approval.get("standard_version")
                in (AUTO_STANDARD_VERSION, LEGACY_BUDGET_STANDARD_VERSION),
            )
            if approval.get("standard_version")
            in (AUTO_STANDARD_VERSION, LEGACY_BUDGET_STANDARD_VERSION, LEGACY_AUTO_STANDARD_VERSION)
            else validate_standard(p)
        )
    except ValueError:
        return None
    return {
        **audit["subset_summary"],
        "available": True,
        "quality_gate_passed": bool(audit.get("quality_gate_passed")),
        "job_id": p["job_id"],
        "release": batch.release,
        "generated_at": approval["approved_at"],
        "publication": {
            **standard,
            **approval,
            "scenario_count": audit["scenario_count"],
            "valid_scenario_count": audit["valid_scenario_count"],
            "coverage": audit["coverage"],
            "comparison_conflicts": len(audit["comparison"]["conflicts"]),
        },
    }


def published_batch(db, release):
    for batch in db.scalars(
        select(ReleaseSimulationBatch)
        .where(ReleaseSimulationBatch.release == release)
        .order_by(ReleaseSimulationBatch.updated_at.desc())
    ):
        if read_projection(
            db, ("publication", batch.fingerprint, batch.updated_at), lambda: publication(batch)
        ):
            return batch
    return None


__all__ = [
    "AUTO_STANDARD_VERSION",
    "LEGACY_AUTO_STANDARD_VERSION",
    "LEGACY_BUDGET_STANDARD_VERSION",
    "MIN_COVERAGE",
    "POLICY",
    "STANDARD_VERSION",
    "approve_publication",
    "audit_hash",
    "coverage_policy",
    "publication",
    "published_batch",
    "validate_coverage_standard",
    "validate_standard",
]
