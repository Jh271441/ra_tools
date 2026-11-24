"""Campaigns, Review Assignments, and Allocation Editor API schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class WorkSplitMember(DashboardBaseModel):
    username: str = ""
    assigned_count: int = 0
    completed_count: int = 0
    pending_count: int = 0
    extra_completed_count: int = 0
    completion_ratio: float = 0.0


class WorkSplitItem(DashboardBaseModel):
    split_id: str = ""
    campaign_name: str = ""
    model_run_id: str = ""
    workflow_mode: str = ""
    mode: str = "single"
    lifecycle: str = "active"
    is_current: bool = True
    legacy_read_only: bool = False
    created_at: str = ""
    updated_at: Optional[str] = None
    created_by: str = ""
    total_count: int = 0
    assignment_count: int = 0
    completed_count: int = 0
    pending_count: int = 0
    completion_ratio: float = 0.0
    reviewers_per_issue: int = 1
    overlap_ratio: float = 0.0
    members: List[WorkSplitMember] = Field(default_factory=list)
    baseline_ids: List[str] = Field(default_factory=list)
    kind: Optional[str] = None
    dataset_id: Optional[str] = None
    release_family: Optional[str] = None
    role_cohort: Optional[str] = None
    allocation_group_count: Optional[int] = None
    conflict_count: Optional[int] = None


class WorkSplitMetrics(DashboardBaseModel):
    task_count: int = 0
    total_assignments: int = 0
    completed_assignments: int = 0
    pending_assignments: int = 0


class WorkSplitListResponse(DashboardBaseModel):
    items: List[WorkSplitItem] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    lifecycle: str = "current"
    assigned_to_me: bool = False
    change_revision: int = 0


class AllocationMemberSpec(DashboardBaseModel):
    username: str = ""
    target_count: Optional[int] = None
    ratio: Optional[float] = None
    completed_count: Optional[int] = None
    pending_count: Optional[int] = None
    assigned_count: Optional[int] = None
    current_count: Optional[int] = None


class AllocationGroupSpec(DashboardBaseModel):
    group_id: str = ""
    name: str = ""
    coverage_ratio: Optional[float] = None
    target_case_count: Optional[int] = None
    members: List[AllocationMemberSpec] = Field(default_factory=list)


class CampaignAllocationResponse(DashboardBaseModel):
    campaign_id: str = ""
    config_revision: int = 0
    total_cases: int = 0
    mode: str = "single"
    workflow_mode: str = ""
    reviewers_per_issue: int = 1
    overlap_ratio: float = 0.0
    groups: List[AllocationGroupSpec] = Field(default_factory=list)
    members: List[AllocationMemberSpec] = Field(default_factory=list)
    editable: bool = True


class AllocationPreviewResponse(DashboardBaseModel):
    campaign_id: Optional[str] = None
    config_revision: Optional[int] = None
    plan: Optional[Dict[str, Any]] = None
    groups: Optional[List[Dict[str, Any]]] = None
    summary: Optional[Dict[str, Any]] = None


class AssignmentNameSuggestionResponse(DashboardBaseModel):
    suggestion: str = ""
    source: str = "rule"
    reason: Optional[str] = None


class CampaignListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    page_count: int = 1
    historical_imports: List[Dict[str, Any]] = Field(default_factory=list)
    change_revision: Optional[int] = None
