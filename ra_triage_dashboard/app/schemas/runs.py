"""Model Runs, Run Comparison, Run Collections, and Frozen Evaluations OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class ModelRunSummary(DashboardBaseModel):
    id: str = ""
    name: str = ""
    source_name: str = ""
    kind: str = ""
    is_default: bool = False
    created_at: str = ""
    created_by: str = ""
    prediction_count: int = 0
    baseline_prediction_count: int = 0
    failure_count: int = 0
    inferred_baseline_ids: List[str] = Field(default_factory=list)
    source_file: Optional[Dict[str, Any]] = None


class ModelRunListResponse(DashboardBaseModel):
    items: List[ModelRunSummary] = Field(default_factory=list)
    default_run_id: Optional[str] = None
    change_revision: Optional[int] = None


class ModelRunComparisonResponse(DashboardBaseModel):
    view_mode: str = "pair"
    page: int = 1
    page_size: int = 10
    page_count: int = 1
    total: int = 0
    baseline_run: Optional[Dict[str, Any]] = None
    candidate_run: Optional[Dict[str, Any]] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    matrices: Dict[str, Any] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_ids: List[str] = Field(default_factory=list)


class ComparisonCaseInputsResponse(DashboardBaseModel):
    issue_id: str = ""
    baseline: Optional[Dict[str, Any]] = None
    candidate: Optional[Dict[str, Any]] = None


class ReviewClustersResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


class RunCollectionListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class RunCollectionDetailResponse(DashboardBaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    current_revision: int = 1
    metadata_revision: int = 0
    current: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    audit: List[Dict[str, Any]] = Field(default_factory=list)


class RunEvaluationListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


class RunEvaluationDetailResponse(DashboardBaseModel):
    id: str = ""
    collection_id: str = ""
    collection_revision: int = 1
    page: int = 1
    page_count: int = 1
    total: int = 0
    members: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)
