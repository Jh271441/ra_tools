"""Shared read-only release/snapshot/execution repository helpers (strictly below services/)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.hashing import audit_hash, digest, execution_audit_hash, population_identity
from app.domain.labels import INPUT_FIELDS, SCENE_FIELDS, physical_fields
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.repositories import state_store


def latest_snapshot_for_release(db: Session, release: str) -> ReleaseIssueSnapshot | None:
    return db.scalars(
        select(ReleaseIssueSnapshot)
        .where(ReleaseIssueSnapshot.release == release)
        .order_by(ReleaseIssueSnapshot.id.desc())
        .limit(1)
    ).first()


def source_identity(payload: dict[str, Any]) -> str:
    return digest(
        {
            "period": {
                k: payload["period"].get(k)
                for k in ("release", "case_start", "case_end_exclusive", "binary_id")
            },
            "issues": sorted(
                (
                    {
                        "issue_id": str(i["issue_id"]),
                        **physical_fields(i),
                        "user_exclusion": i.get("evaluation_exclusion")
                        if (i.get("evaluation_exclusion") or {}).get("approved_by") == "user"
                        else None,
                    }
                    for i in payload["issues"]
                ),
                key=lambda i: i["issue_id"],
            ),
            "scenarios": sorted(
                (
                    {k: s.get(k) for k in ("scenario_id", *SCENE_FIELDS)}
                    for s in payload["scenarios"]
                ),
                key=lambda s: str(s["scenario_id"]),
            ),
        }
    )


def execution_inputs(
    db: Session, batch: ReleaseSimulationBatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind legacy plans to the last matching source snapshot at batch creation time."""
    p = batch.payload
    ids = {str(i["issue_id"]) for i in p.get("issues", [])}
    if all(all(k in i for k in INPUT_FIELDS) for i in p.get("issues", [])):
        rows = {str(i["issue_id"]): i for i in p["issues"]}
        kind, sid = "execution", None
    else:
        rows, sid = {}, None
        snapshots = db.scalars(
            select(ReleaseIssueSnapshot)
            .where(
                ReleaseIssueSnapshot.release == batch.release,
                ReleaseIssueSnapshot.created_at <= batch.created_at,
            )
            .order_by(ReleaseIssueSnapshot.created_at.desc(), ReleaseIssueSnapshot.id.desc())
            .execution_options(yield_per=1)
        )
        try:
            for snapshot in snapshots:
                snap_hash = snapshot.population_hash or population_identity(snapshot.payload)
                if snap_hash != p.get("population_hash"):
                    continue
                candidate = {
                    str(i["issue_id"]): i
                    for i in snapshot.payload["issues"]
                    if str(i["issue_id"]) in ids
                }
                if set(candidate) == ids and all(
                    all(k in i for k in INPUT_FIELDS) for i in candidate.values()
                ):
                    rows, sid = candidate, snapshot.id
                    break
        finally:
            snapshots.close()
        kind = "source_snapshot"
    if not rows:
        return {}, {"kind": "unverified", "snapshot_id": None, "input_hash": None}
    return rows, {
        "kind": kind,
        "snapshot_id": sid,
        "input_hash": digest(
            sorted(
                ({"issue_id": iid, **physical_fields(row)} for iid, row in rows.items()),
                key=lambda r: r["issue_id"],
            )
        ),
    }


def shared_results(
    db: Session, base: ReleaseSimulationBatch, full: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Allow standard backfill & label recovery to reuse audited physical executions."""
    source_inputs, _ = execution_inputs(db, base)
    if not source_inputs:
        return {}, {}
    expected_contract = base.payload.get("result_import", {}).get("execution_contract_hash")
    if not expected_contract:
        cached = state_store.get_routed_state(db, "label_runtime:" + base.fingerprint[:48])
        if cached.get("base_audit_hash") == audit_hash(base.payload):
            expected_contract = cached.get("execution_contract_hash")
    if not expected_contract:
        return {}, {}
    expected = {str(s["scenario_id"]): s for s in full["scenarios"]}
    results: dict[str, Any] = {}
    bindings: dict[str, Any] = {}
    executions = sorted(
        state_store.list_executions(
            db, release=base.release, statuses=("complete", "quality_failed"), include_heavy=True
        ),
        key=lambda e: e.get("created_at", ""),
    )
    for execution in executions:
        plan = execution["plan"]
        if (
            execution["status"] not in ("complete", "quality_failed")
            or plan["release"] != base.release
            or execution.get("audit_hash") != execution_audit_hash(execution)
            or execution["export"].get("execution_contract_hash") != expected_contract
            or any(
                plan.get(k) != base.payload.get(k)
                for k in ("binary_id", "simulation", "driver_revision")
            )
        ):
            continue
        inputs = {str(i["issue_id"]): i for i in plan["issues"]}
        for scene in plan["scenarios"]:
            sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
            signal = execution.get("results", {}).get(sid)
            if (
                sid in results
                or sid not in expected
                or not signal
                or type(signal.get("sim_triggered")) is not bool
                or iid not in inputs
                or iid not in source_inputs
                or physical_fields(inputs[iid]) != physical_fields(source_inputs[iid])
                or any(scene.get(k) != expected[sid].get(k) for k in SCENE_FIELDS)
            ):
                continue
            results[sid] = {"sim_triggered": signal["sim_triggered"]}
            bindings[sid] = {
                "execution_id": execution["id"],
                "job_id": execution["job_id"],
                "audit_hash": execution["audit_hash"],
            }
    return results, bindings


def binding_valid_uncached(db: Session, item: dict[str, Any]) -> bool:
    execution = state_store.get_execution(db, item["execution_id"], include_heavy=True)
    actual_hash = execution_audit_hash(execution)
    return bool(
        execution.get("audit_hash")
        and execution["audit_hash"] == item["audit_hash"]
        and execution["audit_hash"] == actual_hash
    )
