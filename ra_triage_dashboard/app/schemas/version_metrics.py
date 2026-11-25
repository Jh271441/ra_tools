"""Cross-version Metrics and Daily Review OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class VersionMetricsOverviewResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    catalog: List[Dict[str, Any]] = Field(default_factory=list)
    selected: List[str] = Field(default_factory=list)
    table: Dict[str, Any] = Field(default_factory=dict)
    refresh: Optional[Dict[str, Any]] = None


class VersionMetricsDetailResponse(DashboardBaseModel):
    summary: Dict[str, Any] = Field(default_factory=dict)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    cases: Dict[str, Any] = Field(default_factory=dict)


class DailyReviewResponse(DashboardBaseModel):
    date: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
