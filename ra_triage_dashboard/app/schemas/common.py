"""Shared Pydantic base model compatible with both Pydantic v1.10 and v2.x."""
import pydantic
from pydantic import BaseModel

_PYDANTIC_V2 = int(str(getattr(pydantic, "__version__", "1")).split(".")[0]) >= 2

if _PYDANTIC_V2:
    from pydantic import ConfigDict  # type: ignore[attr-defined]

    class DashboardBaseModel(BaseModel):
        """Permissive extra='allow' contract model for OpenAPI 3.x + TS generation."""

        model_config = ConfigDict(extra="allow", protected_namespaces=())

else:

    class DashboardBaseModel(BaseModel):  # type: ignore[no-redef]
        """Permissive extra='allow' contract model for OpenAPI 3.x + TS generation."""

        class Config:
            extra = "allow"
