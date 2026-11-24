"""Version Datasets and Version Workbench API schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class VersionDatasetSummary(DashboardBaseModel):
    id: str = ""
    name: str = ""
    release_family: str = ""
    run_id: Optional[str] = None
    revision: Optional[Any] = None
    total: int = 0
    targets: Optional[int] = None
    samples: Optional[int] = None
    sampled_targets: Optional[int] = None
    low: Optional[int] = None
    low_only: Optional[int] = None
    states: Dict[str, int] = Field(default_factory=dict)
    assigned: Dict[str, int] = Field(default_factory=dict)
    historical: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VersionDatasetListResponse(DashboardBaseModel):
    items: List[VersionDatasetSummary] = Field(default_factory=list)


class VersionWorkbenchItem(DashboardBaseModel):
    issue_id: str = ""
    software_version: str = ""
    date: str = ""
    state: str = ""
    is_target: bool = False
    is_sample: bool = False
    is_low: bool = False
    te_status: str = ""
    te_value: Optional[Any] = None
    review_submitted: Optional[bool] = None
    review_submitted_at: Optional[str] = None
    first_seen: Optional[str] = None
    updated_at: Optional[str] = None
    binding: Dict[str, Any] = Field(default_factory=dict)
    prediction: Optional[Dict[str, Any]] = None


class VersionWorkbenchResponse(DashboardBaseModel):
    dataset_id: str = ""
    dataset: Dict[str, Any] = Field(default_factory=dict)
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: List[VersionWorkbenchItem] = Field(default_factory=list)
    date_options: List[str] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list)
    snapshot_revision: str = ""
    rd: Dict[str, Any] = Field(default_factory=dict)
    te: Dict[str, Any] = Field(default_factory=dict)
    count_scope: Dict[str, Any] = Field(default_factory=dict)
    composition: Dict[str, Any] = Field(default_factory=dict)
