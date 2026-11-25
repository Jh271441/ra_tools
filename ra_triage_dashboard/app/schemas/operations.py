"""Users, Access Control, Mentions, and Legacy Cutover OpenAPI schemas."""
from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import DashboardBaseModel


class AccessUsersResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class MentionUsersResponse(DashboardBaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ReviewersListResponse(DashboardBaseModel):
    items: List[Any] = Field(default_factory=list)


class WorkAssigneesListResponse(DashboardBaseModel):
    items: List[Any] = Field(default_factory=list)


class GenericMutationResponse(DashboardBaseModel):
    ok: bool = True
    change_revision: Optional[int] = None
    message: Optional[str] = None
