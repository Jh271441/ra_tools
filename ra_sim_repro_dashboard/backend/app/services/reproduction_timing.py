"""Compatibility wrapper delegating pure reproduction timing logic to `app.domain.timing`."""

from __future__ import annotations

from app.domain.timing import DEFAULT_BAND_MS, POLICY, classify, milliseconds, summarize

__all__ = ["DEFAULT_BAND_MS", "POLICY", "classify", "milliseconds", "summarize"]
