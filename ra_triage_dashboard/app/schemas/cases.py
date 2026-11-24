"""Case Gallery and Case Detail API schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class CaseListItem(DashboardBaseModel):
    issue_id: str = ""
    trip_id: str = ""
    title: str = ""
    scenario: str = ""
    gt_label: str = ""
    baseline_scope: str = ""
    baseline_id: Optional[str] = None
    model_label: Optional[str] = None
    model_confidence: Optional[float] = None
    review_status: Optional[str] = None
    expected_output: Optional[str] = None
    label_state: Optional[Dict[str, Any]] = None


class CaseListResponse(DashboardBaseModel):
    items: List[CaseListItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    filters: Dict[str, Any] = Field(default_factory=dict)
    gt_snapshots: Dict[str, Any] = Field(default_factory=dict)


class CaseDetailResponse(DashboardBaseModel):
    issue_id: str = ""
    trip_id: str = ""
    title: str = ""
    scenario: str = ""
    gt_label: str = ""
    baseline_scope: str = ""
    model_run_id: Optional[str] = None
    prediction: Optional[Dict[str, Any]] = None
    annotations: List[Dict[str, Any]] = Field(default_factory=list)
    media: Optional[Dict[str, Any]] = None
    external_links: Optional[Dict[str, Any]] = None
    label_state: Optional[Dict[str, Any]] = None
