"""Analysis, Reason Clustering, Facets, and Shadow Comparison OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class AnalysisSummary(DashboardBaseModel):
    latest_reviews: int = 0
    with_reason: int = 0
    empty_reason: int = 0
    with_structured_evidence: int = 0


class AnalysisClusterItem(DashboardBaseModel):
    key: str = ""
    label: str = ""
    count: int = 0
    section: Optional[str] = None
    group: Optional[str] = None


class ConfusionMatrixRow(DashboardBaseModel):
    gt_label: str = ""
    total: int = 0
    accuracy: Optional[float] = None
    cells: Dict[str, int] = Field(default_factory=dict)


class ConfusionMatrixSchema(DashboardBaseModel):
    columns: List[str] = Field(default_factory=list)
    rows: List[ConfusionMatrixRow] = Field(default_factory=list)


class ReviewReasonAnalysisResponse(DashboardBaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 20
    page_count: int = 1
    summary: AnalysisSummary = Field(default_factory=AnalysisSummary)
    scope: Dict[str, Any] = Field(default_factory=dict)
    missing_evidence: List[AnalysisClusterItem] = Field(default_factory=list)
    tag_clusters: List[AnalysisClusterItem] = Field(default_factory=list)
    confusion: Optional[ConfusionMatrixSchema] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    baselines: List[str] = Field(default_factory=list)
    baseline_scopes: List[str] = Field(default_factory=list)


class ModelReviewFacetsResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    facets: Dict[str, Any] = Field(default_factory=dict)
    baseline_scopes: List[str] = Field(default_factory=list)


class ModelReviewShadowComparisonResponse(DashboardBaseModel):
    summary: Dict[str, Any] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_scopes: List[str] = Field(default_factory=list)
