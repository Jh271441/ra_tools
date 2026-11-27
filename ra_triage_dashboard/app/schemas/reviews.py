"""Case Reviews, Labeling, Comments, Discussions, and RD Results OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class CaseMediaResponse(DashboardBaseModel):
    issue_id: str = ""
    assets: Optional[Dict[str, Any]] = None
    camera: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    planning_constraints: Optional[Dict[str, Any]] = None


class ReviewSubmissionResponse(DashboardBaseModel):
    ok: bool = True
    issue_id: str = ""
    annotation: Optional[Dict[str, Any]] = None
    change_revision: Optional[int] = None


class CommentListResponse(DashboardBaseModel):
    issue_id: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    channel: Optional[str] = None


class CommentMutationResponse(DashboardBaseModel):
    ok: bool = True
    comment: Optional[Dict[str, Any]] = None
    change_revision: Optional[int] = None


class CaseLabelingQueueResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    summary: Dict[str, Any] = Field(default_factory=dict)


class LabelingSummaryResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    summary: Dict[str, Any] = Field(default_factory=dict)
    matrix_exclusions: Dict[str, int] = Field(default_factory=dict)


class RdResultsResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    summary: Dict[str, Any] = Field(default_factory=dict)


class HumanPublicationListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class OverviewResponse(DashboardBaseModel):
    total_cases: int = 0
    reviewed_cases: int = 0
    failure_cases: int = 0
    model_run: Optional[Dict[str, Any]] = None
    change_revision: Optional[int] = None
