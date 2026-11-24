"""Daily Cron Observatory response schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class CronCaseFailure(DashboardBaseModel):
    issue_id: str = ""
    code: str = ""


class CronRun(DashboardBaseModel):
    id: str = ""
    target_date_cst: str = ""
    state: str = ""
    health: str = ""
    stage: str = ""
    total: Optional[int] = None
    finished: Optional[int] = None
    succeeded: Optional[int] = None
    percent: Optional[float] = None
    failure_count: Optional[int] = None
    selected: Optional[int] = None
    inferred: Optional[int] = None
    skipped: Optional[int] = None
    published: Optional[int] = None
    verified: Optional[int] = None
    started_at: Optional[float] = None
    updated_at: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    target_is_weekend: bool = False
    evidence_error: bool = False
    skipped_cases: List[CronCaseFailure] = Field(default_factory=list)
    failure_details: List[CronCaseFailure] = Field(default_factory=list)
    timing: Optional[Dict[str, Any]] = None
    stage_timings: Dict[str, Any] = Field(default_factory=dict)


class CronDaily(DashboardBaseModel):
    health: str = ""
    target_date: str = ""
    timezone: str = ""
    heartbeat_at: Optional[float] = None
    first_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    stall_seconds: Optional[float] = None
    runs: List[CronRun] = Field(default_factory=list)
    alerts: List[Dict[str, Any]] = Field(default_factory=list)
    launches: List[Dict[str, Any]] = Field(default_factory=list)
    recoveries: List[Dict[str, Any]] = Field(default_factory=list)


class CronJob(DashboardBaseModel):
    id: str = ""
    name: str = ""
    schedule: str = ""
    evidence: str = ""
    log_updated_at: Optional[float] = None
    log_age_seconds: Optional[float] = None


class CronOverview(DashboardBaseModel):
    collected_at: Optional[float] = None
    stale: bool = False
    collector_error: bool = False
    daily: CronDaily = Field(default_factory=CronDaily)
    jobs: List[CronJob] = Field(default_factory=list)


class CronMediaCounts(DashboardBaseModel):
    selected: int = 0
    verified: int = 0
    reused: int = 0
    failure_count: int = 0
    queued: int = 0
    camera_verified: Optional[int] = None
    bev_verified: Optional[int] = None
    triple_verified: Optional[int] = None
    track_counts_basis: Optional[str] = None
    closeup: Optional[Dict[str, Any]] = None


class CronVersionEntry(DashboardBaseModel):
    family: str = ""
    states: Optional[Dict[str, int]] = None
    states_status: str = "unavailable"
    media: Optional[CronMediaCounts] = None
    planning_text: Optional[Dict[str, Any]] = None


class CronIncremental(DashboardBaseModel):
    enabled: bool = False
    stale: bool = False
    updated_at: Optional[float] = None
    sampling_policy: Optional[str] = None
    states: Dict[str, int] = Field(default_factory=dict)
    families: List[str] = Field(default_factory=list)
    versions: List[CronVersionEntry] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)
    media: Optional[CronMediaCounts] = None
    planning_text: Optional[Dict[str, Any]] = None
    increments: Optional[Dict[str, Any]] = None


class DailyCronResponse(DashboardBaseModel):
    observed_at: float = 0.0
    refresh_seconds: int = 30
    sources: Dict[str, str] = Field(default_factory=dict)
    overview: Optional[CronOverview] = None
    history: Optional[List[Dict[str, Any]]] = None
    sidecar: Optional[Dict[str, Any]] = None
    media_daily: Optional[Dict[str, Any]] = None
    closeup: Optional[Dict[str, Any]] = None
    incremental: Optional[CronIncremental] = None
