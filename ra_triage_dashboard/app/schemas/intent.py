"""Intent Labeling Datasets, Queue, Experiments (062 Reallocation), and Summary OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class IntentDatasetListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    default_dataset_id: Optional[str] = None


class IntentQueueResponse(DashboardBaseModel):
    dataset_id: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    progress: Dict[str, Any] = Field(default_factory=dict)


class IntentCaseDetailResponse(DashboardBaseModel):
    dataset_id: str = ""
    case_id: str = ""
    frames: List[Dict[str, Any]] = Field(default_factory=list)
    labels: Optional[Dict[str, Any]] = None
    reveal: Optional[Dict[str, Any]] = None


class IntentExperimentResponse(DashboardBaseModel):
    experiment: Dict[str, Any] = Field(default_factory=dict)
    change_revision: Optional[int] = None


class IntentExperimentListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    members: List[Dict[str, Any]] = Field(default_factory=list)


class IntentSummaryResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    distributions: Dict[str, Any] = Field(default_factory=dict)
    agreement: Dict[str, Any] = Field(default_factory=dict)
