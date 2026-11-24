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
    collection_scope: dict[str, Any] | None = None
    reproduction: dict[str, Any] | None = None
    evaluation_scope: dict[str, Any] | None = None
    version_key: str
    label: str
    total_cases: int
    road_positive_cases: int
    road_behavior_cases: int = 0
    sim_positive_cases: int
    reproduced_cases: int
    sim_repro_rate: float | None
    model_repro_rate: float
    fn_fallback_rate: float
    fp_suppress_rate: float
    precision: float | None
    recall: float | None
    f1: float | None
    specificity: float | None = 0.0
    accuracy: float | None = 0.0
    positive_auto_repro_rate: float | None = 0.0
    negative_auto_repro_rate: float | None = 0.0
    positive_manual_repro_rate: float | None = 0.0
    evaluated_cases: int = 0
    dpe_coverage: float = 0.0
    publication: dict[str, Any] | None = None
    quality_gate_passed: bool = True
    root_causes: dict[str, int]
    source_gt: dict[str, Any] | None = None
    sim_estimate: dict[str, Any] | None = None


class SummaryResponse(BaseModel):
    business_collection: dict[str, Any] | None = None
    business_current_version: str | None = None
    business_metrics: KpiSummary | None = None
    business_status: str = "legacy"
    business_reason: str = ""
    current: KpiSummary | None = None
    legacy_current: KpiSummary | None = None
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


class SystemCheck(BaseModel):
    key: str
    status: str
    latency_ms: float | None = None
    detail: str = ""
    error: str = ""
    extra: dict[str, Any] = {}


class SystemStatusResponse(BaseModel):
    overall: str
    generated_at: datetime
    app_started_at: datetime
    uptime_seconds: int
    enable_rq: bool
    checks: list[SystemCheck]


class HealthResponse(BaseModel):
    status: str


class AuthMeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    authenticated: bool
    user: str | None = None
    source: str
    can_write: bool
    deployment_mode: str


class WorkflowStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    mode: str
    driver_ready: bool
    scheduler_enabled: bool
    current_version: str | None = None
    periods: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []


class WorkflowIssuesPageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    status: str


class ScenarioLabelGroupsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    rows: list[dict[str, Any]]
    total_scenarios: int
    frozen_count: int | None = None
    sampled_at: str


class CollectionInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    default_release: str | None = None
    versions: list[dict[str, Any]]


class SimulationBoardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    versions: list[dict[str, Any]]
    selected: dict[str, Any]
    mode: str
    driver_ready: bool
    scheduler_enabled: bool
    current_status: str
    refreshing: bool


class WorkflowSyncResponse(BaseModel):
    status: str


class WorkflowPlanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    fingerprint: str
    release: str
    binary_id: int | str | None = None
    scenarios: list[dict[str, Any]] = []


class WorkflowBatchReceiptResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    fingerprint: str
    status: str
    job_id: int | str | None = None


class WorkflowResumeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    release: str
    status: str


class EvaluationProfileResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    status: str
    config: dict[str, Any]
    config_hash: str


class EvaluationProfileCatalogueResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    active: str
    versions: list[dict[str, Any]]
    label_sources: list[dict[str, Any]]


class EvaluationPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile_id: str
    config_hash: str
    context: dict[str, Any]
    base_revision: str
    preview_hash: str
    metrics: dict[str, Any]
    previous_metrics: dict[str, Any]


class EvaluationActivateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    active: str
    audit_key: str
    contexts: list[dict[str, Any]]


class EvaluationBoardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    context: dict[str, Any]
    profile: dict[str, Any]
    versions: list[dict[str, Any]]
    sample_source: dict[str, Any]
    revision: dict[str, Any] | None = None
    stale: bool
    refresh: dict[str, Any] = {}
    plan: dict[str, Any] = {}
    cron: dict[str, Any]
    executions: list[dict[str, Any]] = []
    starts: list[dict[str, Any]] = []


class EvaluationComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile: dict[str, Any]
    versions: list[dict[str, Any]]


class EvaluationIssuesPageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int
    revision_key: str | None = None


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    status: str
    context: dict[str, Any]


class EvaluationStartResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    plan_id: str
    simulation_submitted: bool = False


class EvaluationCronResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool
    interval_seconds: int
    effective: bool
    processing_enabled: bool
    poll_seconds: int


class EvaluationScenarioLabelsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str


class EvaluationScenarioLabelSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
