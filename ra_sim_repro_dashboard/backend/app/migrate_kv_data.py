"""Idempotent, non-destructive backfill from legacy KV/JSON columns to P1 normalized tables.

Safe to re-run repeatedly; never deletes legacy `release_workflow_state` rows so
an emergency rollback to pre-P1 code remains lossless.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain.hashing import digest, population_identity
from app.models import (
    EvaluationExecution,
    EvaluationRequest,
    EvaluationRevision,
    EvaluationRevisionBlob,
    EvaluationScenarioTag,
    ReleaseIssueSnapshot,
    ReleaseSimulationBatch,
    ReleaseWorkflowState,
    ReproductionTimingEvidence,
)
from app.repositories import state_store

logger = logging.getLogger(__name__)


def backfill_database(db: Session, *, prune_request_days: int | None = None) -> dict[str, int]:
    counts: dict[str, int] = {
        "snapshots_hashed": 0,
        "batches_indexed": 0,
        "revisions_migrated": 0,
        "executions_migrated": 0,
        "requests_migrated": 0,
        "scenario_tags_migrated": 0,
        "timing_ledgers_migrated": 0,
        "requests_pruned": 0,
    }

    # 1. Backfill ReleaseIssueSnapshot.population_hash
    for snap in db.scalars(
        select(ReleaseIssueSnapshot).where(ReleaseIssueSnapshot.population_hash.is_(None))
    ):
        p = snap.payload or {}
        if "period" in p and "issues" in p and "scenarios" in p:
            try:
                snap.population_hash = population_identity(p)
                counts["snapshots_hashed"] += 1
            except Exception:
                logger.warning("Failed to hash snapshot id=%s", snap.id, exc_info=True)
    db.commit()

    # 2. Backfill ReleaseSimulationBatch indexed columns
    for batch in db.scalars(select(ReleaseSimulationBatch)):
        p = batch.payload or {}
        changed = False
        pop_hash = p.get("population_hash")
        if isinstance(pop_hash, str) and pop_hash and batch.population_hash != pop_hash[:64]:
            batch.population_hash = pop_hash[:64]
            changed = True
        is_bf = bool(p.get("backfill"))
        if batch.is_backfill != is_bf:
            batch.is_backfill = is_bf
            changed = True
        ri = p.get("result_import")
        is_prim = bool(isinstance(ri, dict) and ri.get("primary"))
        if batch.is_primary != is_prim:
            batch.is_primary = is_prim
            changed = True
        raw_job = p.get("job_id")
        job_id = int(raw_job) if raw_job is not None and str(raw_job).isdigit() else None
        if batch.job_id != job_id:
            batch.job_id = job_id
            changed = True
        if changed:
            counts["batches_indexed"] += 1
    db.commit()

    # 3. Backfill evrevision:* -> evaluation_revisions + evaluation_revision_blobs
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evrevision:"))
    ):
        if db.get(EvaluationRevision, row.key) is None and isinstance(row.payload, dict):
            state_store.save_revision(db, row.key, row.payload, commit=False)
            counts["revisions_migrated"] += 1
    db.commit()

    # 4. Backfill evexecution:* -> evaluation_executions
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evexecution:"))
    ):
        eid = row.key.removeprefix("evexecution:")
        if db.get(EvaluationExecution, eid) is None and isinstance(row.payload, dict):
            state_store.save_execution(db, eid, row.payload, commit=False)
            counts["executions_migrated"] += 1
    db.commit()

    # 5. Backfill evrequest:* -> evaluation_requests
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evrequest:"))
    ):
        rid = row.key.removeprefix("evrequest:")
        if db.get(EvaluationRequest, rid) is None and isinstance(row.payload, dict):
            state_store.save_request(db, rid, row.payload, commit=False)
            counts["requests_migrated"] += 1
    db.commit()

    # 6. Backfill evscene_tags:* -> evaluation_scenario_tags
    plan_to_ctx_hash: dict[str, str] = {}
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evscene_labels:"))
    ):
        p = row.payload or {}
        if p.get("id") and p.get("context"):
            plan_to_ctx_hash[str(p["id"])] = digest(p["context"])

    grouped_by_plan: dict[tuple[str, str, str, str, str], dict[str, list[dict[str, Any]]]] = {}
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evscene_tags:"))
    ):
        p = row.payload or {}
        items = p.get("items") or []
        plan_id = str(p.get("plan_id") or "")
        ctx_hash = plan_to_ctx_hash.get(plan_id)
        if not ctx_hash or not items:
            continue
        issue_id = str(items[0].get("issue_id") or "")
        if not issue_id:
            continue
        if db.get(EvaluationScenarioTag, (ctx_hash, issue_id)) is not None:
            continue
        bucket_key = (
            ctx_hash,
            plan_id,
            str(p.get("revision_key") or ""),
            str(p.get("namespace") or ""),
            str(p.get("checked_at") or ""),
        )
        grouped_by_plan.setdefault(bucket_key, {})[issue_id] = items

    for (ctx_hash, plan_id, rev_key, ns, checked_at), grouped in grouped_by_plan.items():
        counts["scenario_tags_migrated"] += state_store.batch_upsert_scenario_tags(
            db,
            context_hash=ctx_hash,
            plan_id=plan_id,
            revision_key=rev_key,
            namespace=ns,
            checked_at=checked_at,
            grouped_items=grouped,
            commit=False,
        )
    db.commit()

    # 7. Backfill rtime:* -> reproduction_timing_evidence
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("rtime:"))
    ):
        p = row.payload or {}
        release = str(p.get("release") or "")
        if (
            release
            and p.get("schema")
            and isinstance(p.get("records"), list)
            and row.key == "rtime:" + digest(p)[:48]
            and db.get(ReproductionTimingEvidence, row.key) is None
        ):
            state_store.save_timing_ledger(db, row.key, release, p)
            counts["timing_ledgers_migrated"] += 1
    db.commit()

    if prune_request_days is not None and prune_request_days > 0:
        counts["requests_pruned"] = state_store.prune_terminal_requests(
            db, keep_days=prune_request_days
        )

    return counts


def verify_backfill(db: Session) -> dict[str, Any]:
    return {
        "snapshots_missing_hash": int(
            db.scalar(
                select(func.count())
                .select_from(ReleaseIssueSnapshot)
                .where(ReleaseIssueSnapshot.population_hash.is_(None))
            )
            or 0
        ),
        "evaluation_revisions": int(
            db.scalar(select(func.count()).select_from(EvaluationRevision)) or 0
        ),
        "evaluation_revision_blobs": int(
            db.scalar(select(func.count()).select_from(EvaluationRevisionBlob)) or 0
        ),
        "evaluation_executions": int(
            db.scalar(select(func.count()).select_from(EvaluationExecution)) or 0
        ),
        "evaluation_requests": int(
            db.scalar(select(func.count()).select_from(EvaluationRequest)) or 0
        ),
        "evaluation_scenario_tags": int(
            db.scalar(select(func.count()).select_from(EvaluationScenarioTag)) or 0
        ),
        "reproduction_timing_evidence": int(
            db.scalar(select(func.count()).select_from(ReproductionTimingEvidence)) or 0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Print normalized table counts")
    parser.add_argument(
        "--prune-days",
        type=int,
        default=None,
        help="Optionally prune terminal evaluation_requests older than N days",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        result = backfill_database(db, prune_request_days=args.prune_days)
        if args.verify:
            result["counts"] = verify_backfill(db)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
