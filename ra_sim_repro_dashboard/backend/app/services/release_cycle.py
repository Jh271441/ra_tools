"""Compatibility wrapper delegating pure cycle logic to `app.domain.cycle` & `app.domain.labels`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import CONFIG_DIR
from app.domain.cycle import (
    BASE_FILTERS,
    TZ,
    period_key,
    query_contract,
    reference_thursday,
    resolve_current,
    validate_period,
)
from app.domain.hashing import digest
from app.domain.labels import real_labels


def load_cycle_config() -> dict:
    path = Path(os.getenv("RELEASE_CYCLES_CONFIG", str(CONFIG_DIR / "release-cycles.default")))
    if not path.exists():
        return {"periods": []}
    value = json.loads(path.read_text())
    command = os.getenv("RELEASE_DRIVER_COMMAND_JSON")
    if command:
        value.setdefault("simulation", {})["driver_command"] = json.loads(command)
    return value


__all__ = [
    "BASE_FILTERS",
    "TZ",
    "digest",
    "load_cycle_config",
    "period_key",
    "query_contract",
    "real_labels",
    "reference_thursday",
    "resolve_current",
    "validate_period",
]
