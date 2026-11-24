"""Externalizable configuration for version review task reviewer weights."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

DEFAULT_REVIEW_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("jasperchen", 1),
    ("liangxianghui", 1),
)
VERSION_REVIEW_WEIGHTS: dict[str, tuple[tuple[str, int], ...]] = {
    "20261030": (("liangxianghui", 4), ("jasperchen", 3), ("hejianmo", 3)),
}


def _normalize_weights(
    raw: Sequence[Sequence[object]],
) -> tuple[tuple[str, int], ...]:
    pairs: list[tuple[str, int]] = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError("Invalid reviewer weight entry")
        username = str(entry[0] or "").strip().lower()
        weight = int(entry[1])
        if not username or weight <= 0:
            raise ValueError("Reviewer username and positive weight are required")
        pairs.append((username, weight))
    if not pairs:
        raise ValueError("Reviewer weights must be non-empty")
    return tuple(pairs)


def load_version_review_weights_config(
    config_file: Path | str | None = None,
) -> tuple[tuple[tuple[str, int], ...], dict[str, tuple[tuple[str, int], ...]]]:
    """Load optional JSON override without breaking built-in family defaults."""
    raw_path = (
        str(config_file).strip()
        if config_file is not None
        else os.getenv("DASHBOARD_VERSION_REVIEW_WEIGHTS_FILE", "").strip()
    )
    if not raw_path:
        return DEFAULT_REVIEW_WEIGHTS, dict(VERSION_REVIEW_WEIGHTS)
    path = Path(raw_path).expanduser()
    if not path.is_file():
        return DEFAULT_REVIEW_WEIGHTS, dict(VERSION_REVIEW_WEIGHTS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Version review weights config must be a JSON object")
    default_weights = (
        _normalize_weights(payload["default"])
        if "default" in payload
        else DEFAULT_REVIEW_WEIGHTS
    )
    by_family = dict(VERSION_REVIEW_WEIGHTS)
    raw_families = payload.get("by_family")
    if isinstance(raw_families, dict):
        for family, entries in raw_families.items():
            key = str(family or "").strip()
            if key:
                by_family[key] = _normalize_weights(entries)
    return default_weights, by_family


def get_version_review_weights(
    release_family: str,
    *,
    config_file: Path | str | None = None,
) -> tuple[tuple[str, int], ...]:
    """Return weighted reviewer list for a release family."""
    default_weights, by_family = load_version_review_weights_config(config_file)
    return by_family.get(str(release_family or "").strip(), default_weights)
