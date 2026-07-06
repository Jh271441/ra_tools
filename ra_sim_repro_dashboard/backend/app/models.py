from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["ScenarioVersionResult"]] = relationship(back_populates="version")


class Scenario(Base):
    __tablename__ = "scenarios"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(512), default="")
    issue_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    signature: Mapped[str] = mapped_column(String(256), default="")
    raw_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    raw_issue: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    fp_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    fn_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    version: Mapped[Version] = relationship(back_populates="results")
    scenario: Mapped[Scenario] = relationship(back_populates="results")


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    current_version: Mapped[str] = mapped_column(String(128), index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
