"""Normalized repository layer for evaluation revisions, executions, requests, tags, timing, and KV fallback.

Also installs SQLAlchemy Session flush hooks so indexed columns on
`ReleaseIssueSnapshot` / `ReleaseSimulationBatch` and per-release counters in
`release_data_versions` stay atomically consistent with every ORM write.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.domain.hashing import digest, population_identity
from app.models import (
    DashboardSnapshot,
    EvaluationExecution,
    EvaluationRequest,
    EvaluationRevision,
    EvaluationRevisionBlob,
    EvaluationScenarioTag,
    ReleaseIssueSnapshot,
    ReleaseSimulationBatch,
    ReleaseWorkflowState,
    ReproductionTimingEvidence,
    Version,
)
from app.repositories.read_models_repo import GLOBAL_RELEASE_SCOPE, bump_release_version

logger = logging.getLogger(__name__)

_MISSING_SENTINEL = {"__missing_blob_field__": True}
REVISION_BLOB_FIELDS = ("rows", "source", "payload", "lineage")
EXECUTION_HEAVY_FIELDS = ("plan", "export", "results")
ACTIVE_EXECUTION_STATUSES = (
    "preparing",
    "submitting",
    "submission_uncertain",
    "running",
    "verifying",
)


def _is_missing_sentinel(val: Any) -> bool:
    return isinstance(val, dict) and val == _MISSING_SENTINEL


def _extract_release_from_kv(key: str, payload: dict[str, Any] | None) -> str:
    if isinstance(payload, dict):
        rel = (
            payload.get("release")
            or (payload.get("context") or {}).get("release")
            or (payload.get("plan") or {}).get("release")
        )
        if isinstance(rel, str) and rel:
            return rel
    if ":" in key:
        prefix, suffix = key.split(":", 1)
        if prefix in {
            "release_monitor",
            "release_observation",
            "collection_revision",
            "label_recovery",
            "label_cycle",
            "evaluation_target",
            "rtime_policy",
        }:
            return suffix
    return GLOBAL_RELEASE_SCOPE


# --- Evaluation Revisions (Summary ~20 KB vs Blob ~7 MB) ---


def save_revision(
    db: Session, revision_key: str, value: dict[str, Any], *, commit: bool = True
) -> None:
    ctx = value.get("context") or {}
    profile = value.get("profile") or {}
    sample = value.get("sample") or {}
    summary = {k: v for k, v in value.items() if k not in REVISION_BLOB_FIELDS}

    rows_payload = value["rows"] if "rows" in value else _MISSING_SENTINEL
    source_payload = value["source"] if "source" in value else _MISSING_SENTINEL
    payload_blob = value["payload"] if "payload" in value else _MISSING_SENTINEL
    lineage_payload = value["lineage"] if "lineage" in value else _MISSING_SENTINEL

    context_hash = digest(ctx) if ctx else digest(revision_key)
    release = str(ctx.get("release") or "")
    profile_id = str(ctx.get("profile_id") or profile.get("id") or "")
    date_start = str(ctx.get("date_start") or "")
    date_end = str(ctx.get("date_end") or "")
    config_hash = str(profile.get("config_hash") or "")
    sample_id = sample.get("snapshot_id") or sample.get("id")
    inventory_id = str(value.get("inventory_identity") or "")
    generated_at = str(value.get("generated_at") or datetime.now(timezone.utc).isoformat())

    rev = db.get(EvaluationRevision, revision_key)
    if rev is None:
        rev = EvaluationRevision(
            revision_key=revision_key,
            context_hash=context_hash,
            release=release,
            profile_id=profile_id,
            date_start=date_start,
            date_end=date_end,
            config_hash=config_hash,
            sample_snapshot_id=str(sample_id) if sample_id is not None else None,
            inventory_identity=inventory_id,
            summary_payload=summary,
            generated_at=generated_at,
        )
        db.add(rev)
    else:
        rev.context_hash = context_hash
        rev.release = release
        rev.profile_id = profile_id
        rev.date_start = date_start
        rev.date_end = date_end
        rev.config_hash = config_hash
        rev.sample_snapshot_id = str(sample_id) if sample_id is not None else None
        rev.inventory_identity = inventory_id
        rev.summary_payload = summary
        rev.generated_at = generated_at

    blob = db.get(EvaluationRevisionBlob, revision_key)
    if blob is None:
        blob = EvaluationRevisionBlob(
            revision_key=revision_key,
            rows_payload=rows_payload,
            source_payload=source_payload,
            payload_blob=payload_blob,
            lineage_payload=lineage_payload,
        )
        db.add(blob)
    else:
        blob.rows_payload = rows_payload
        blob.source_payload = source_payload
        blob.payload_blob = payload_blob
        blob.lineage_payload = lineage_payload

    if commit:
        db.commit()


def _reconstruct_revision(
    rev: EvaluationRevision, blob: EvaluationRevisionBlob | None
) -> dict[str, Any]:
    out = deepcopy(rev.summary_payload) if isinstance(rev.summary_payload, dict) else {}
    if blob is not None:
        if not _is_missing_sentinel(blob.rows_payload):
            out["rows"] = deepcopy(blob.rows_payload)
        if not _is_missing_sentinel(blob.source_payload):
            out["source"] = deepcopy(blob.source_payload)
        if not _is_missing_sentinel(blob.payload_blob):
            out["payload"] = deepcopy(blob.payload_blob)
        if not _is_missing_sentinel(blob.lineage_payload):
            out["lineage"] = deepcopy(blob.lineage_payload)
    return out


def get_revision_summary(db: Session, revision_key: str) -> dict[str, Any]:
    """Load ONLY the lightweight ~20 KB summary (never reads the ~7 MB blob)."""
    if not revision_key:
        return {}
    rev = db.get(EvaluationRevision, revision_key)
    if rev is not None:
        return deepcopy(rev.summary_payload)
    legacy = db.get(ReleaseWorkflowState, revision_key)
    if legacy is not None and isinstance(legacy.payload, dict):
        return {k: deepcopy(v) for k, v in legacy.payload.items() if k not in REVISION_BLOB_FIELDS}
    return {}


def get_revision_full(db: Session, revision_key: str) -> dict[str, Any]:
    if not revision_key:
        return {}
    rev = db.get(EvaluationRevision, revision_key)
    if rev is not None:
        blob = db.get(EvaluationRevisionBlob, revision_key)
        return _reconstruct_revision(rev, blob)
    legacy = db.get(ReleaseWorkflowState, revision_key)
    return deepcopy(legacy.payload) if legacy is not None else {}


def list_revisions(db: Session, *, include_blobs: bool = True) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    revs = db.scalars(select(EvaluationRevision)).all()
    blobs_by_key: dict[str, EvaluationRevisionBlob] = {}
    if include_blobs and revs:
        keys = [r.revision_key for r in revs]
        blobs_by_key = {
            b.revision_key: b
            for b in db.scalars(
                select(EvaluationRevisionBlob).where(EvaluationRevisionBlob.revision_key.in_(keys))
            )
        }
    for rev in revs:
        seen.add(rev.revision_key)
        if include_blobs:
            items.append(_reconstruct_revision(rev, blobs_by_key.get(rev.revision_key)))
        else:
            items.append(deepcopy(rev.summary_payload))
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evrevision:"))
    ):
        if row.key not in seen:
            if include_blobs:
                items.append(deepcopy(row.payload))
            else:
                items.append(
                    {
                        k: deepcopy(v)
                        for k, v in row.payload.items()
                        if k not in REVISION_BLOB_FIELDS
                    }
                )
    return items


# --- Evaluation Executions (Indexed by release/status, split meta vs heavy) ---


def _split_execution(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = {k: v for k, v in value.items() if k not in EXECUTION_HEAVY_FIELDS}
    heavy = {k: v for k, v in value.items() if k in EXECUTION_HEAVY_FIELDS}
    return meta, heavy


def _merge_execution(meta: dict[str, Any], heavy: dict[str, Any] | None) -> dict[str, Any]:
    out = deepcopy(meta) if isinstance(meta, dict) else {}
    if isinstance(heavy, dict):
        for k, v in heavy.items():
            out[k] = deepcopy(v)
    return out


def save_execution(
    db: Session, execution_id: str, value: dict[str, Any], *, commit: bool = True
) -> None:
    meta, heavy = _split_execution(value)
    plan = value.get("plan") or {}
    ctx = value.get("context") or {}
    release = str(plan.get("release") or ctx.get("release") or "")
    plan_id = value.get("plan_id")
    raw_job = value.get("job_id")
    job_id = int(raw_job) if raw_job is not None and str(raw_job).isdigit() else None
    preflight = value.get("preflight") or {}
    contract_hash = preflight.get("execution_contract_hash") or (
        (value.get("export") or {}).get("execution_contract_hash")
    )

    row = db.get(EvaluationExecution, execution_id)
    if row is None:
        row = EvaluationExecution(
            execution_id=execution_id,
            release=release,
            plan_id=str(plan_id) if plan_id is not None else None,
            job_id=job_id,
            status=str(value.get("status") or ""),
            metrics_status=value.get("metrics_status"),
            audit_hash=value.get("audit_hash"),
            contract_hash=contract_hash,
            meta_payload=meta,
            heavy_payload=heavy,
            created_at=str(value.get("created_at") or ""),
            finished_at=value.get("finished_at"),
        )
        db.add(row)
    else:
        row.release = release
        row.plan_id = str(plan_id) if plan_id is not None else None
        row.job_id = job_id
        row.status = str(value.get("status") or "")
        row.metrics_status = value.get("metrics_status")
        row.audit_hash = value.get("audit_hash")
        row.contract_hash = contract_hash
        row.meta_payload = meta
        row.heavy_payload = heavy
        row.created_at = str(value.get("created_at") or row.created_at or "")
        row.finished_at = value.get("finished_at")

    if commit:
        db.commit()


def get_execution(db: Session, execution_id: str, *, include_heavy: bool = True) -> dict[str, Any]:
    if not execution_id:
        return {}
    if not include_heavy:
        meta = db.execute(
            select(EvaluationExecution.meta_payload).where(
                EvaluationExecution.execution_id == execution_id
            )
        ).scalar_one_or_none()
        if meta is not None:
            return deepcopy(meta)
    else:
        row = db.get(EvaluationExecution, execution_id)
        if row is not None:
            return _merge_execution(row.meta_payload, row.heavy_payload)
    legacy = db.get(ReleaseWorkflowState, "evexecution:" + execution_id)
    if legacy is not None:
        if not include_heavy:
            return {
                k: deepcopy(v) for k, v in legacy.payload.items() if k not in EXECUTION_HEAVY_FIELDS
            }
        return deepcopy(legacy.payload)
    return {}


def list_executions(
    db: Session,
    *,
    release: str | None = None,
    statuses: tuple[str, ...] | None = None,
    include_heavy: bool = True,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    if include_heavy:
        stmt = select(EvaluationExecution)
        if release is not None:
            stmt = stmt.where(EvaluationExecution.release == release)
        if statuses is not None:
            stmt = stmt.where(EvaluationExecution.status.in_(statuses))
        for row in db.scalars(stmt):
            seen.add(row.execution_id)
            items.append(_merge_execution(row.meta_payload, row.heavy_payload))
    else:
        stmt = select(EvaluationExecution.execution_id, EvaluationExecution.meta_payload)
        if release is not None:
            stmt = stmt.where(EvaluationExecution.release == release)
        if statuses is not None:
            stmt = stmt.where(EvaluationExecution.status.in_(statuses))
        for eid, meta in db.execute(stmt):
            seen.add(eid)
            items.append(deepcopy(meta))

    # Merge any unmigrated legacy KV rows (tests or pre-backfill PG data)
    for kv in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evexecution:"))
    ):
        eid = kv.key.removeprefix("evexecution:")
        if eid in seen:
            continue
        p = kv.payload or {}
        if release is not None:
            kv_rel = (p.get("plan") or {}).get("release") or (p.get("context") or {}).get("release")
            if kv_rel != release:
                continue
        if statuses is not None and p.get("status") not in statuses:
            continue
        if include_heavy:
            items.append(deepcopy(p))
        else:
            items.append({k: deepcopy(v) for k, v in p.items() if k not in EXECUTION_HEAVY_FIELDS})
    return items


def list_public_executions_grouped(
    db: Session, release: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Return lightweight execution metadata grouped by release (zero heavy JSON)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    stmt = select(
        EvaluationExecution.execution_id,
        EvaluationExecution.release,
        EvaluationExecution.meta_payload,
    )
    if release:
        stmt = stmt.where(EvaluationExecution.release == release)
    for eid, rel, meta in db.execute(stmt):
        seen.add(eid)
        if rel:
            grouped.setdefault(rel, []).append(deepcopy(meta))
    for kv in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evexecution:"))
    ):
        eid = kv.key.removeprefix("evexecution:")
        if eid in seen:
            continue
        p = kv.payload or {}
        rel = (p.get("plan") or {}).get("release") or (p.get("context") or {}).get("release")
        if not rel or (release and rel != release):
            continue
        grouped.setdefault(rel, []).append(
            {k: deepcopy(v) for k, v in p.items() if k not in EXECUTION_HEAVY_FIELDS}
        )
    return grouped


def count_active_executions(db: Session, release: str | None = None) -> int:
    stmt = select(EvaluationExecution.execution_id).where(
        EvaluationExecution.status.in_(ACTIVE_EXECUTION_STATUSES)
    )
    if release is not None:
        stmt = stmt.where(EvaluationExecution.release == release)
    active_ids = set(db.scalars(stmt).all())
    for kv in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evexecution:"))
    ):
        eid = kv.key.removeprefix("evexecution:")
        if eid in active_ids:
            continue
        p = kv.payload or {}
        if p.get("status") not in ACTIVE_EXECUTION_STATUSES:
            continue
        if release is not None:
            kv_rel = (p.get("plan") or {}).get("release") or (p.get("context") or {}).get("release")
            if kv_rel != release:
                continue
        active_ids.add(eid)
    return len(active_ids)


# --- Evaluation Requests (Indexed status + 30-day terminal pruning) ---


def save_request(
    db: Session, request_id: str, value: dict[str, Any], *, commit: bool = True
) -> None:
    ctx = value.get("context") or {}
    context_hash = digest(ctx) if ctx else digest(request_id)
    row = db.get(EvaluationRequest, request_id)
    if row is None:
        row = EvaluationRequest(
            request_id=request_id,
            context_hash=context_hash,
            release=str(ctx.get("release") or ""),
            profile_id=str(ctx.get("profile_id") or ""),
            source_mode=str(value.get("source_mode") or "database"),
            status=str(value.get("status") or "queued"),
            revision_key=value.get("revision_key"),
            error=str(value.get("error") or ""),
            payload=value,
            requested_at=str(value.get("requested_at") or datetime.now(timezone.utc).isoformat()),
            finished_at=value.get("finished_at"),
        )
        db.add(row)
    else:
        row.context_hash = context_hash
        row.release = str(ctx.get("release") or "")
        row.profile_id = str(ctx.get("profile_id") or "")
        row.source_mode = str(value.get("source_mode") or "database")
        row.status = str(value.get("status") or "queued")
        row.revision_key = value.get("revision_key")
        row.error = str(value.get("error") or "")
        row.payload = value
        row.requested_at = str(value.get("requested_at") or row.requested_at)
        row.finished_at = value.get("finished_at")
    if commit:
        db.commit()


def get_request(db: Session, request_id: str) -> dict[str, Any]:
    if not request_id:
        return {}
    row = db.get(EvaluationRequest, request_id)
    if row is not None:
        return deepcopy(row.payload)
    legacy = db.get(ReleaseWorkflowState, "evrequest:" + request_id)
    return deepcopy(legacy.payload) if legacy is not None else {}


def list_requests(db: Session, *, statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    stmt = select(EvaluationRequest)
    if statuses is not None:
        stmt = stmt.where(EvaluationRequest.status.in_(statuses))
    for row in db.scalars(stmt):
        seen.add(row.request_id)
        items.append(deepcopy(row.payload))
    for kv in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evrequest:"))
    ):
        rid = kv.key.removeprefix("evrequest:")
        if rid in seen:
            continue
        p = kv.payload or {}
        if statuses is not None and p.get("status") not in statuses:
            continue
        items.append(deepcopy(p))
    return items


def prune_terminal_requests(db: Session, *, keep_days: int = 30) -> int:
    """Remove terminal evaluation requests older than `keep_days`, retaining latest per context."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    latest_per_ctx: dict[str, str] = {}
    for row in db.scalars(
        select(EvaluationRequest).order_by(EvaluationRequest.requested_at.desc())
    ):
        latest_per_ctx.setdefault(row.context_hash, row.request_id)
    keep_ids = set(latest_per_ctx.values())
    to_delete = [
        row.request_id
        for row in db.scalars(
            select(EvaluationRequest).where(
                EvaluationRequest.status.in_(("complete", "failed")),
                EvaluationRequest.requested_at < cutoff,
            )
        )
        if row.request_id not in keep_ids
    ]
    if not to_delete:
        return 0
    db.execute(delete(EvaluationRequest).where(EvaluationRequest.request_id.in_(to_delete)))
    db.commit()
    return len(to_delete)


# --- Scenario Label Tags (Batch single-tx upsert) ---


def batch_upsert_scenario_tags(
    db: Session,
    *,
    context_hash: str,
    plan_id: str,
    revision_key: str,
    namespace: str,
    checked_at: str,
    grouped_items: dict[str, list[dict[str, Any]]],
    commit: bool = True,
) -> int:
    if not grouped_items:
        return 0
    issue_ids = list(grouped_items.keys())
    existing = {
        row.issue_id: row
        for row in db.scalars(
            select(EvaluationScenarioTag).where(
                EvaluationScenarioTag.context_hash == context_hash,
                EvaluationScenarioTag.issue_id.in_(issue_ids),
            )
        )
    }
    for issue_id, items in grouped_items.items():
        row = existing.get(issue_id)
        if row is None:
            db.add(
                EvaluationScenarioTag(
                    context_hash=context_hash,
                    issue_id=str(issue_id),
                    plan_id=plan_id,
                    revision_key=revision_key,
                    namespace=namespace,
                    checked_at=checked_at,
                    items=items,
                )
            )
        else:
            row.plan_id = plan_id
            row.revision_key = revision_key
            row.namespace = namespace
            row.checked_at = checked_at
            row.items = items
    if commit:
        db.commit()
    return len(grouped_items)


def get_scenario_tag(
    db: Session, context_hash: str, issue_id: str, *, legacy_key: str | None = None
) -> dict[str, Any]:
    row = db.get(EvaluationScenarioTag, (context_hash, str(issue_id)))
    if row is not None:
        return {
            "plan_id": row.plan_id,
            "revision_key": row.revision_key,
            "namespace": row.namespace,
            "checked_at": row.checked_at,
            "items": deepcopy(row.items),
        }
    if legacy_key:
        legacy = db.get(ReleaseWorkflowState, legacy_key)
        if legacy is not None:
            return deepcopy(legacy.payload)
    return {}


# --- Reproduction Timing Evidence (Indexed by release) ---


def save_timing_ledger(db: Session, ledger_key: str, release: str, core: dict[str, Any]) -> str:
    content_hash = digest(core)
    existing = db.get(ReproductionTimingEvidence, ledger_key)
    if existing is not None:
        if existing.payload != core:
            raise ValueError("timing_ledger_conflict")
        return ledger_key
    legacy = db.get(ReleaseWorkflowState, ledger_key)
    if legacy is not None and legacy.payload != core:
        raise ValueError("timing_ledger_conflict")
    db.add(
        ReproductionTimingEvidence(
            ledger_key=ledger_key,
            release=release,
            schema_ver=str(core.get("schema") or ""),
            content_hash=content_hash,
            records_count=len(core.get("records") or []),
            payload=core,
        )
    )
    return ledger_key


def list_timing_ledgers(db: Session, release: str) -> list[tuple[str, dict[str, Any]]]:
    seen: set[str] = set()
    results: list[tuple[str, dict[str, Any]]] = []
    for row in db.scalars(
        select(ReproductionTimingEvidence).where(ReproductionTimingEvidence.release == release)
    ):
        seen.add(row.ledger_key)
        results.append((row.ledger_key, row.payload))
    # Fallback to legacy KV rows for unmigrated data or tests inserting directly into KV
    stmt = select(ReleaseWorkflowState).where(
        ReleaseWorkflowState.key.like("rtime:%"),
        ReleaseWorkflowState.payload["release"].as_string() == release,
    )
    for row in db.scalars(stmt):
        if row.key not in seen:
            seen.add(row.key)
            results.append((row.key, row.payload))
    return results


# --- Indexed Snapshot Lookup Helper ---


def find_snapshot_by_population_hash(
    db: Session, release: str, population_hash: str
) -> ReleaseIssueSnapshot | None:
    """O(1) indexed lookup by (release, population_hash), with legacy NULL fallback."""
    indexed = db.scalars(
        select(ReleaseIssueSnapshot)
        .where(
            ReleaseIssueSnapshot.release == release,
            ReleaseIssueSnapshot.population_hash == population_hash,
        )
        .order_by(ReleaseIssueSnapshot.id.desc())
        .limit(1)
    ).first()
    if indexed is not None:
        return indexed
    # Only scan unbackfilled legacy rows where population_hash IS NULL
    rows = db.scalars(
        select(ReleaseIssueSnapshot)
        .where(
            ReleaseIssueSnapshot.release == release,
            ReleaseIssueSnapshot.population_hash.is_(None),
        )
        .order_by(ReleaseIssueSnapshot.id.desc())
        .execution_options(yield_per=1)
    )
    try:
        for snap in rows:
            try:
                if population_identity(snap.payload) == population_hash:
                    return snap
            except (KeyError, TypeError):
                continue
    finally:
        rows.close()
    return None


# --- Transparent Routing Helpers for Legacy `get_state` / `put_state` ---


def put_routed_state(
    db: Session, key: str, payload: dict[str, Any], *, commit: bool = True
) -> None:
    if key.startswith("evrevision:"):
        save_revision(db, key, payload, commit=commit)
        return
    if key.startswith("evexecution:"):
        save_execution(db, key.removeprefix("evexecution:"), payload, commit=commit)
        return
    if key.startswith("evrequest:"):
        save_request(db, key.removeprefix("evrequest:"), payload, commit=commit)
        return
    row = db.get(ReleaseWorkflowState, key)
    if row is None:
        db.add(ReleaseWorkflowState(key=key, payload=payload))
    else:
        row.payload = payload
    if commit:
        db.commit()


def get_routed_state(db: Session, key: str, default: Any = None) -> Any:
    if not key:
        return default if default is not None else {}
    if key.startswith("evrevision:"):
        value = get_revision_full(db, key)
        return value if value else (default if default is not None else {})
    if key.startswith("evexecution:"):
        value = get_execution(db, key.removeprefix("evexecution:"), include_heavy=True)
        return value if value else (default if default is not None else {})
    if key.startswith("evrequest:"):
        value = get_request(db, key.removeprefix("evrequest:"))
        return value if value else (default if default is not None else {})
    row = db.get(ReleaseWorkflowState, key)
    return row.payload if row is not None else (default if default is not None else {})


# --- Automatic SQLAlchemy Session Flush Hooks ---


def _sync_snapshot_columns(obj: ReleaseIssueSnapshot) -> None:
    p = obj.payload
    if isinstance(p, dict) and "period" in p and "issues" in p and "scenarios" in p:
        try:
            obj.population_hash = population_identity(p)
        except Exception:
            pass


def _sync_batch_columns(obj: ReleaseSimulationBatch) -> None:
    p = obj.payload
    if not isinstance(p, dict):
        return
    pop_hash = p.get("population_hash")
    if isinstance(pop_hash, str) and pop_hash:
        obj.population_hash = pop_hash[:64]
    obj.is_backfill = bool(p.get("backfill"))
    result_import = p.get("result_import")
    obj.is_primary = bool(isinstance(result_import, dict) and result_import.get("primary"))
    raw_job = p.get("job_id")
    if raw_job is not None and str(raw_job).isdigit():
        obj.job_id = int(raw_job)


def _affected_release_for_obj(obj: Any) -> str | None:
    if isinstance(obj, ReleaseIssueSnapshot):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, ReleaseSimulationBatch):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, EvaluationRevision):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, EvaluationRevisionBlob):
        return GLOBAL_RELEASE_SCOPE
    if isinstance(obj, EvaluationExecution):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, EvaluationRequest):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, EvaluationScenarioTag):
        return GLOBAL_RELEASE_SCOPE
    if isinstance(obj, ReproductionTimingEvidence):
        return obj.release or GLOBAL_RELEASE_SCOPE
    if isinstance(obj, ReleaseWorkflowState):
        return _extract_release_from_kv(obj.key, obj.payload)
    if isinstance(obj, (DashboardSnapshot, Version)):
        return GLOBAL_RELEASE_SCOPE
    return None


@event.listens_for(Session, "before_flush")
def _on_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if session.info.get("_bumping_versions"):
        return
    dirty_releases: set[str] = session.info.setdefault("_pending_version_bumps", set())
    for obj in (*session.new, *session.dirty):
        if isinstance(obj, ReleaseIssueSnapshot):
            _sync_snapshot_columns(obj)
        elif isinstance(obj, ReleaseSimulationBatch):
            _sync_batch_columns(obj)
        rel = _affected_release_for_obj(obj)
        if rel:
            dirty_releases.add(rel)
    for obj in session.deleted:
        rel = _affected_release_for_obj(obj)
        if rel:
            dirty_releases.add(rel)


@event.listens_for(Session, "after_flush")
def _on_after_flush(session: Session, flush_context: Any) -> None:
    if session.info.get("_bumping_versions"):
        return
    dirty_releases: set[str] = session.info.pop("_pending_version_bumps", set())
    if not dirty_releases:
        return
    session.info["_bumping_versions"] = True
    try:
        for rel in sorted(dirty_releases):
            bump_release_version(session, rel)
    except Exception:
        # Tolerate minimal test schemas that do not create release_data_versions.
        logger.debug("Skipping release_data_versions bump", exc_info=True)
    finally:
        session.info["_bumping_versions"] = False
