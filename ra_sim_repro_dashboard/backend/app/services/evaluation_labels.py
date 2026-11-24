"""Compatibility wrapper delegating pure label resolution to `app.domain.labels`."""

from __future__ import annotations

from app.domain.labels import (
    CURRENT_PRIORITY,
    FUTURE_PRIORITY,
    READY,
    SOURCE_FIELDS,
    resolve_label,
    source_value,
    validate_policy,
)

__all__ = [
    "CURRENT_PRIORITY",
    "FUTURE_PRIORITY",
    "READY",
    "SOURCE_FIELDS",
    "resolve_label",
    "source_value",
    "validate_policy",
]
