"""Batch Prediction, Inference, Trail Update/History, and Import OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class BatchConfigResponse(DashboardBaseModel):
    enabled: bool = False
    max_cases: int = 100
    models: List[Dict[str, Any]] = Field(default_factory=list)
    prompts: List[Dict[str, Any]] = Field(default_factory=list)
    input_profiles: List[Dict[str, Any]] = Field(default_factory=list)


class BatchListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class BatchDetailResponse(DashboardBaseModel):
    id: str = ""
    status: str = ""
    total_cases: int = 0
    completed_cases: int = 0
    failed_cases: int = 0
    items: List[Dict[str, Any]] = Field(default_factory=list)


class TrailUpdatePreviewResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    write_enabled: bool = False


class TrailHistoryListResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class ImportContractResponse(DashboardBaseModel):
    supported_formats: List[str] = Field(default_factory=list)
    max_upload_bytes: int = 0
    fields: Dict[str, Any] = Field(default_factory=dict)


class GtSyncStatusResponse(DashboardBaseModel):
    running: bool = False
    status: str = ""
    message: str = ""
    last_success_at: Optional[str] = None
    baselines: List[Dict[str, Any]] = Field(default_factory=list)
