"""Core infrastructure: DI container, FastAPI Depends providers, and domain config."""
from __future__ import annotations

from .container import AppContainer
from .deps import (
    get_baseline_registry,
    get_container,
    get_db,
    get_media_registry,
    get_settings,
    require_admin,
    require_intent_perm,
    require_session,
    require_writer,
    resolve_dep,
)
from .version_review_config import (
    DEFAULT_REVIEW_WEIGHTS,
    VERSION_REVIEW_WEIGHTS,
    get_version_review_weights,
)

__all__ = [
    "AppContainer",
    "DEFAULT_REVIEW_WEIGHTS",
    "VERSION_REVIEW_WEIGHTS",
    "get_baseline_registry",
    "get_container",
    "get_db",
    "get_media_registry",
    "get_settings",
    "get_version_review_weights",
    "require_admin",
    "require_intent_perm",
    "require_session",
    "require_writer",
    "resolve_dep",
]
