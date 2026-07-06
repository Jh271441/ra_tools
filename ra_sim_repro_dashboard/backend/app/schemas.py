from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_key: str
    label: str
    sim_job_id: int | None
    baseline_job_id: int | None
    sort_order: int
    is_current: bool
    metadata_json: dict[str, Any]
    last_refreshed_at: datetime | None


class VersionsResponse(BaseModel):
    current_version: str
    compare_versions: list[str]
    config_hash: str
    versions: list[VersionOut]


class KpiSummary(BaseModel):
    version_key: str
    label: str
    total_cases: int
    road_positive_cases: int
    sim_positive_cases: int
    reproduced_cases: int
    sim_repro_rate: float
    model_repro_rate: float
    fn_fallback_rate: float
    fp_suppress_rate: float
    precision: float
    recall: float
    f1: float
    root_causes: dict[str, int]
    source_gt: dict[str, Any] | None = None
    sim_estimate: dict[str, Any] | None = None


class SummaryResponse(BaseModel):
    current: KpiSummary
    previous: KpiSummary | None = None
    deltas: dict[str, float]
    generated_at: datetime


class VersionComparisonItem(KpiSummary):
    sort_order: int


class ScenarioResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_key: str
    scenario_id: str
    issue_id: str | None
    road_triggered: bool
    sim_triggered: bool
    reproduced: bool
    precision_label: str
    trigger_type: str
    root_cause: str
    model_score_max: float | None
    threshold: float | None
    unstuck_status: str
    fp_reasons: list[str]
    fn_reasons: list[str]
    raw_metrics: dict[str, Any]
    updated_at: datetime


class IssueListItem(BaseModel):
    issue_id: str | None
    scenario_id: str
    scenario_name: str
    version_key: str
    issue_topic: str = ""
    status: str = ""
    priority: str = ""
    poi: str = ""
    road_triggered: bool
    sim_triggered: bool
    reproduced: bool
    precision_label: str
    trigger_type: str
    root_cause: str
    model_score_max: float | None
    threshold: float | None
    unstuck_status: str
    fp_reasons: list[str]
    fn_reasons: list[str]


class PaginatedIssuesResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[IssueListItem]


class IssueDetailResponse(BaseModel):
    issue_id: str
    issue: dict[str, Any]
    scenarios: list[dict[str, Any]]


class ScenarioDetailResponse(BaseModel):
    scenario_id: str
    scenario: dict[str, Any]
    results: list[ScenarioResultOut]


class RefreshJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    progress: int
    message: str
    error: str
    config_hash: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RefreshRequest(BaseModel):
    force: bool = False
