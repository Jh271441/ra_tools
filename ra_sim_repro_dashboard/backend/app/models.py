from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PortableJSONB(TypeDecorator):
    """Uses PostgreSQL JSONB in production and standard JSON on SQLite tests."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def utcnow() -> datetime:
    return datetime.utcnow()


class Version(Base):
    __tablename__ = "versions"

    version_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    sim_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    baseline_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["ScenarioVersionResult"]] = relationship(back_populates="version")


class Scenario(Base):
    __tablename__ = "scenarios"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(512), default="")
    issue_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    signature: Mapped[str] = mapped_column(String(256), default="")
    raw_info: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    results: Mapped[list["ScenarioVersionResult"]] = relationship(back_populates="scenario")


class Issue(Base):
    __tablename__ = "issues"

    issue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    issue_topic: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(128), default="")
    priority: Mapped[str] = mapped_column(String(128), default="")
    poi: Mapped[str] = mapped_column(String(512), default="")
    issue_time: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    raw_issue: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScenarioVersionResult(Base):
    __tablename__ = "scenario_version_results"
    __table_args__ = (
        UniqueConstraint("version_key", "scenario_id", name="uq_result_version_scenario"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_key: Mapped[str] = mapped_column(ForeignKey("versions.version_key"), index=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.scenario_id"), index=True)
    issue_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    road_triggered: Mapped[bool] = mapped_column(Boolean, default=True)
    sim_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    reproduced: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    precision_label: Mapped[str] = mapped_column(String(32), default="FN", index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), default="UNKNOWN", index=True)
    root_cause: Mapped[str] = mapped_column(String(96), default="UNKNOWN", index=True)
    model_score_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    unstuck_status: Mapped[str] = mapped_column(String(128), default="")
    fp_reasons: Mapped[list[str]] = mapped_column(PortableJSONB, default=list)
    fn_reasons: Mapped[list[str]] = mapped_column(PortableJSONB, default=list)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    version: Mapped[Version] = relationship(back_populates="results")
    scenario: Mapped[Scenario] = relationship(back_populates="results")


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    current_version: Mapped[str] = mapped_column(String(128), index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RefreshJob(Base):
    __tablename__ = "refresh_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    config_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReleaseIssueSnapshot(Base):
    """Atomic full upstream population, independent of any simulation result."""

    __tablename__ = "release_issue_snapshots"
    __table_args__ = (
        Index("ix_release_snapshots_rel_pophash", "release", "population_hash"),
        Index("ix_release_snapshots_rel_id", "release", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_hash: Mapped[str] = mapped_column(String(64), index=True)
    release: Mapped[str] = mapped_column(String(128), index=True)
    population_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReleaseWorkflowState(Base):
    __tablename__ = "release_workflow_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReleaseSimulationBatch(Base):
    __tablename__ = "release_simulation_batches"
    __table_args__ = (
        Index("ix_release_batches_rel_status", "release", "status"),
        Index("ix_release_batches_rel_pophash", "release", "population_hash"),
    )

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    release: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    population_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# --- P1 Normalized Evaluation, Timing, CQRS Read Models, and Audit Tables ---


class EvaluationScenarioTag(Base):
    """Normalized replacement for `evscene_tags:*` KV entries (batch single-tx upsert)."""

    __tablename__ = "evaluation_scenario_tags"
    __table_args__ = (Index("ix_eval_scene_tags_plan", "context_hash", "plan_id"),)

    context_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    issue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_key: Mapped[str] = mapped_column(String(128), nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    checked_at: Mapped[str] = mapped_column(String(64), nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(PortableJSONB, default=list)


class EvaluationRequest(Base):
    """Normalized replacement for `evrequest:*` KV entries with status indexing."""

    __tablename__ = "evaluation_requests"
    __table_args__ = (
        Index("ix_eval_requests_status_req", "status", "requested_at"),
        Index("ix_eval_requests_ctx_req", "context_hash", "requested_at"),
    )

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    release: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(32), default="database", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    revision_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    requested_at: Mapped[str] = mapped_column(String(64), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EvaluationRevision(Base):
    """Lightweight summary header (~20 KB) for `evrevision:*` — board/comparison reads ONLY this."""

    __tablename__ = "evaluation_revisions"
    __table_args__ = (
        Index("ix_eval_revisions_ctx_gen", "context_hash", "generated_at"),
        Index("ix_eval_revisions_rel_prof", "release", "profile_id"),
    )

    revision_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date_start: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    date_end: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    sample_snapshot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inventory_identity: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    summary_payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    generated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class EvaluationRevisionBlob(Base):
    """Heavy per-issue rows/source/payload/lineage (~7 MB) separated from revision summary."""

    __tablename__ = "evaluation_revision_blobs"

    revision_key: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_revisions.revision_key", ondelete="CASCADE"),
        primary_key=True,
    )
    rows_payload: Mapped[list[dict[str, Any]]] = mapped_column(PortableJSONB, default=list)
    source_payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    payload_blob: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    lineage_payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)


class EvaluationExecution(Base):
    """Indexed replacement for `evexecution:*` splitting light meta from heavy plan/export."""

    __tablename__ = "evaluation_executions"
    __table_args__ = (
        Index("ix_eval_exec_rel_status", "release", "status"),
        Index("ix_eval_exec_status", "status"),
    )

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta_payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    heavy_payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ReproductionTimingEvidence(Base):
    """Indexed replacement for `rtime:*` immutable timing evidence ledgers."""

    __tablename__ = "reproduction_timing_evidence"
    __table_args__ = (Index("ix_rtime_release", "release"),)

    ledger_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    release: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_ver: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    records_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DashboardReadModel(Base):
    """CQRS materialized read projections keyed by (view_type, release, profile_id)."""

    __tablename__ = "dashboard_read_models"
    __table_args__ = (Index("ix_read_models_scope", "scope_release", "view_type"),)

    cache_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    scope_release: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    view_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReleaseDataVersion(Base):
    """Fine-grained per-release monotonic version counter replacing 4-table revision scans."""

    __tablename__ = "release_data_versions"

    release: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_seq: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AdminAuditLog(Base):
    """Persistent audit log for all mutating API operations."""

    __tablename__ = "admin_audit_logs"
    __table_args__ = (Index("ix_audit_logs_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    identity_source: Mapped[str] = mapped_column(String(64), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(256), nullable=False)
    target_release: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(PortableJSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
