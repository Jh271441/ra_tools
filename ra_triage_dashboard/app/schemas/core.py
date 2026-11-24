"""Core platform API schemas: session, config, health, baselines, system-status."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class HealthResponse(DashboardBaseModel):
    ok: bool = True
    build_commit: str = ""
    base_path: str = ""
    deployment_mode: str = "production"
    storage: str = ""
    change_revision: int = 0


class SessionResponse(DashboardBaseModel):
    authenticated: bool = False
    verified: bool = False
    username: str = ""
    display_name: str = ""
    source: str = ""
    access_role: str = "viewer"
    is_admin: bool = False
    intent_permission: str = ""
    can_view_intent: bool = False
    can_annotate_intent: bool = False
    can_manage_intent: bool = False
    can_manage_team_default: bool = False
    deployment_mode: str = "production"
    can_write: bool = False
    read_only: bool = True
    login_managed_by: str = ""
    logout_url: str = ""


class ChangeRevisionResponse(DashboardBaseModel):
    revision: int = 0
    topics: Dict[str, Any] = Field(default_factory=dict)
    poll_after_ms: int = 5000
    gt_sync: Optional[Dict[str, Any]] = None


class BaselineMembership(DashboardBaseModel):
    status: str = ""
    registered_count: Optional[int] = None
    expected_count: Optional[int] = None
    count_matches: Optional[bool] = None
    sha_matches: Optional[bool] = None
    frozen: Optional[bool] = None


class BaselineMediaReady(DashboardBaseModel):
    coverage_status: Optional[str] = None
    bev_indexed_issues: Optional[int] = None
    video_indexed_issues: Optional[int] = None
    camera_indexed_issues: Optional[int] = None
    failure_count: Optional[int] = None


class BaselineSummary(DashboardBaseModel):
    id: str = ""
    label: str = ""
    scope: str = ""
    status: str = ""
    registration_status: Optional[str] = None
    media_status: Optional[str] = None
    count: Optional[int] = None
    default_selected: bool = False
    membership: Optional[BaselineMembership] = None
    media_ready: Optional[BaselineMediaReady] = None
    missing_media: Optional[Dict[str, int]] = None


class BaselinesResponse(DashboardBaseModel):
    items: List[BaselineSummary] = Field(default_factory=list)
    default_ids: List[str] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)


class DashboardConfigResponse(DashboardBaseModel):
    default_model_run_id: str = ""
    base_path: str = ""
    deployment_mode: str = "production"
    baselines: Optional[List[Dict[str, Any]]] = None
    default_baseline_ids: Optional[List[str]] = None
    review_tags: Optional[List[Dict[str, Any]]] = None
    missing_evidence: Optional[List[Dict[str, Any]]] = None


class OverallStatus(DashboardBaseModel):
    status: str = "healthy"
    problems: List[str] = Field(default_factory=list)


class ApplicationStatus(DashboardBaseModel):
    build_commit: str = ""
    started_at: str = ""
    uptime_seconds: float = 0.0
    deployment_mode: str = "production"
    base_path: str = ""


class DatabaseStatus(DashboardBaseModel):
    ok: bool = True
    backend: str = ""
    server_version: str = ""
    persistent_data: bool = False
    revision: int = 0
    migration_count: int = 0
    pool_max_size: int = 0
    latency_ms: Optional[float] = None


class BackupStatus(DashboardBaseModel):
    available: bool = False
    count: int = 0
    latest_path: str = ""
    latest_name: str = ""
    latest_size_bytes: Optional[int] = None
    latest_created_at: Optional[str] = None
    latest_age_seconds: Optional[float] = None
    latest_checksum_present: bool = False
    schedule_registered: bool = False
    schedule_line: str = ""


class VolumeStatus(DashboardBaseModel):
    path: str = ""
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    used_percent: Optional[float] = None


class SystemStatusResponse(DashboardBaseModel):
    overall: OverallStatus = Field(default_factory=OverallStatus)
    application: ApplicationStatus = Field(default_factory=ApplicationStatus)
    database: DatabaseStatus = Field(default_factory=DatabaseStatus)
    backups: BackupStatus = Field(default_factory=BackupStatus)
    volume: VolumeStatus = Field(default_factory=VolumeStatus)
    baselines: List[BaselineSummary] = Field(default_factory=list)
    baseline_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    ra_auto_triage_root_available: bool = False
    ares_manifest_available: bool = False
    camera_cache_root_available: bool = False
    ares_video_root_available: bool = False
    trail_sync: Dict[str, Any] = Field(default_factory=dict)
    gt_sync: Dict[str, Any] = Field(default_factory=dict)
    model_gateway: Dict[str, Any] = Field(default_factory=dict)
    review_notifications: Dict[str, Any] = Field(default_factory=dict)
    legacy_cutover: Dict[str, Any] = Field(default_factory=dict)
    change_revision: int = 0
    build_commit: str = ""
