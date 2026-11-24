"""Shared planning-constraint constants, query validation, and error contracts."""
from __future__ import annotations

SOURCE = "/studio_node/planning/speed_table_raw.dominantConstraint"
VERSION = "ares-default-8c071689-v2"
MAX_OFFSET_MS = 60000


class InvalidPlanningTime(ValueError):
    """Raised when a planning constraint offset or timestamp is invalid."""


def query_offset(anchor_ms: int, offset_ms: int | None, timestamp_ms: int | None) -> int:
    if timestamp_ms is not None and offset_ms is not None:
        raise InvalidPlanningTime("Choose offset_ms or timestamp_ms")
    if timestamp_ms is not None:
        if type(timestamp_ms) is not int or not 0 < timestamp_ms <= 9007199254740991:
            raise InvalidPlanningTime("Invalid publish timestamp")
        offset_ms = timestamp_ms - anchor_ms
    offset_ms = 0 if offset_ms is None else offset_ms
    if type(offset_ms) is not int or abs(offset_ms) > MAX_OFFSET_MS:
        raise InvalidPlanningTime("Invalid offset")
    return offset_ms
