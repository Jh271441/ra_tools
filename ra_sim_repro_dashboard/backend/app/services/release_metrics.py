"""Compatibility wrapper delegating pure population metrics to `app.domain.metrics`."""

from __future__ import annotations

from app.domain.metrics import (
    EXCLUDED_RESULTS,
    GOOD_RESULTS,
    cohort_for_issue,
    excluded_issue,
    ratio,
    summarize_population,
)

__all__ = [
    "EXCLUDED_RESULTS",
    "GOOD_RESULTS",
    "cohort_for_issue",
    "excluded_issue",
    "ratio",
    "summarize_population",
]
