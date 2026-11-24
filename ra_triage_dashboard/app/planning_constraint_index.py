"""Read saved planning text by Issue and publish time, without media or Bag I/O."""
from __future__ import annotations

from pathlib import Path

from .planning_contracts import (
    InvalidPlanningTime,
    MAX_OFFSET_MS,
    SOURCE,
    VERSION,
    query_offset,
)
from .planning_history_store import (
    APPLICATION_ID,
    INDEX_NAME,
    INDEX_VERSION,
    MAX_FRAME_BYTES,
    MAX_FRAMES,
    MAX_INDEX_BYTES,
    MAX_RESULT_BYTES,
    TOLERANCE_MS,
    _read_history_window,
)
from .planning_text_daily import read_daily_window

__all__ = [
    "APPLICATION_ID",
    "INDEX_NAME",
    "INDEX_VERSION",
    "InvalidPlanningTime",
    "MAX_FRAME_BYTES",
    "MAX_FRAMES",
    "MAX_INDEX_BYTES",
    "MAX_OFFSET_MS",
    "MAX_RESULT_BYTES",
    "SOURCE",
    "TOLERANCE_MS",
    "VERSION",
    "_read_history_window",
    "query_offset",
    "read_saved_window",
]


def read_saved_window(
    data_dir: Path,
    issue_id: str,
    offset_ms: int | None = None,
    timestamp_ms: int | None = None,
    *,
    trip_id: str | None = None,
    anchor_ms: int | None = None,
) -> dict | None:
    daily = read_daily_window(
        data_dir,
        issue_id,
        offset_ms,
        timestamp_ms,
        trip_id=trip_id,
        anchor_ms=anchor_ms,
    )
    if daily is not None and daily.get("status") != "pending":
        return daily
    history = _read_history_window(
        data_dir,
        issue_id,
        offset_ms,
        timestamp_ms,
        trip_id=trip_id,
        anchor_ms=anchor_ms,
    )
    return history if history is not None else daily
