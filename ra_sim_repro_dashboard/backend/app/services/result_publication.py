"""Audited publication orchestration & effective publication read projection (Tier 4b)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.domain.coverage import coverage_policy
from app.domain.hashing import audit_hash
from app.models import ReleaseSimulationBatch
from app.services import label_cycle, release_backfill, reproduction_evidence
from app.services.publication_core import (
    AUTO_STANDARD_VERSION,
    LEGACY_AUTO_STANDARD_VERSION,
    LEGACY_BUDGET_STANDARD_VERSION,
    MIN_COVERAGE,
    STANDARD_VERSION,
    approve_publication,
    publication,
    published_batch,
    validate_coverage_standard,
    validate_standard,
)
from app.services.read_views import read_projection


def reconcile_publications(db, config):
    """Idempotent scheduler step: publish audited terminal results, even on restart."""
    policy = coverage_policy(config)
    seen = set()
    for batch in db.scalars(
        select(ReleaseSimulationBatch)
        .where(ReleaseSimulationBatch.status.in_(["complete", "quality_failed"]))
        .order_by(ReleaseSimulationBatch.created_at.desc())
    ):
        p = batch.payload
        if (
            p.get("backfill")
            or not p.get("result_import", {}).get("primary")
            or batch.release in seen
        ):
            continue
        seen.add(batch.release)
        approval = p.get("publication_approval") or {}
        if approval and approval.get("standard_version") != AUTO_STANDARD_VERSION:
            continue
        decision = {"minimum_coverage": policy["minimum_coverage"]}
        try:
            if not policy["enabled"]:
                raise ValueError("自动发布已关闭")
            standard = validate_coverage_standard(p, policy["minimum_coverage"])
            fingerprint = audit_hash(p)
            if (
                approval.get("audit_hash") == fingerprint
                and approval.get("minimum_coverage") == policy["minimum_coverage"]
            ):
                continue
            if not release_backfill.frozen_snapshot_valid(db, batch):
                raise ValueError("当前人口与核验快照不一致，停止自动发布")
            approval = {
                **standard,
                "policy": "audited_valid_samples",
                "automatic": True,
                "primary_job_id": p["job_id"],
                "population_hash": p["population_hash"],
                "excluded_scenario_ids": sorted(
                    str(f["scenario_id"]) for f in p["result_import"]["failures"]
                ),
                "comparison_required": True,
                "reason": "达到有效样本覆盖率阈值，异常保留且不计入指标",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "audit_hash": fingerprint,
            }
            decision.update(
                status="published",
                coverage=standard["coverage"],
                issue_coverage=standard["issue_coverage"],
            )
            updated = {**p, "publication_approval": approval, "publication_decision": decision}
        except ValueError as exc:
            decision.update(status="blocked", reason=str(exc))
            updated = {**p, "publication_decision": decision}
            if approval.get("standard_version") == AUTO_STANDARD_VERSION:
                updated.pop("publication_approval", None)
        if updated != p:
            batch.payload = updated
    db.commit()


def effective_publication(db, batch):
    return read_projection(
        db,
        ("effective-publication", batch.fingerprint, batch.updated_at),
        lambda: _effective_publication(db, batch),
    )


def _effective_publication(db, batch):
    base = read_projection(
        db, ("publication", batch.fingerprint, batch.updated_at), lambda: publication(batch)
    )
    enriched = release_backfill.revision_metrics(db, batch, base)
    return reproduction_evidence.standard_view(
        db, batch, label_cycle.revision_metrics(db, batch, enriched)
    )


def annotate_standard_rows(db, release, rows):
    if not reproduction_evidence.active(db, release):
        return rows
    batch = published_batch(db, release)
    metrics = effective_publication(db, batch) if batch else None
    return reproduction_evidence.annotate_rows_for_publication(db, release, batch, metrics, rows)


__all__ = [
    "AUTO_STANDARD_VERSION",
    "LEGACY_AUTO_STANDARD_VERSION",
    "LEGACY_BUDGET_STANDARD_VERSION",
    "MIN_COVERAGE",
    "STANDARD_VERSION",
    "annotate_standard_rows",
    "approve_publication",
    "audit_hash",
    "coverage_policy",
    "effective_publication",
    "publication",
    "published_batch",
    "reconcile_publications",
    "validate_coverage_standard",
    "validate_standard",
]
