"""Read verified, Workbench-owned simulation associations without Trail writes."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ISSUE_ID_RE


_TASK_ID_RE = re.compile(r"[0-9]{12,20}\Z")
_MAX_MANIFEST_BYTES = 1024 * 1024


def read_verified_disable_ra_simulation(
    data_dir: Path,
    issue_id: str,
    *,
    source_task_id: Any = None,
) -> dict[str, Any] | None:
    """Return a verified local association, ignoring invalid or stale records.

    The operator-owned manifest is published atomically after checking completed
    tasks, readable output bags and the original simulation configuration. Only
    numeric task references reach the existing fixed-host Animation link builder.
    Missing Trail metadata is allowed; a different current Trail task supersedes
    the local association instead of being silently hidden by it.
    """

    if not ISSUE_ID_RE.fullmatch(issue_id):
        return None
    path = Path(data_dir) / "disable_ra_simulations" / "links.json"
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            return None
        manifest = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int:
        return None
    if manifest["schema_version"] != 1 or not isinstance(manifest.get("links"), dict):
        return None
    row = manifest["links"].get(issue_id)
    if not isinstance(row, dict):
        return None
    task_id = str(row.get("task_id", ""))
    original_task_id = str(row.get("source_task_id", ""))
    version = row.get("task_version")
    bag_count = row.get("output_bag_count")
    if (
        not _TASK_ID_RE.fullmatch(task_id)
        or not _TASK_ID_RE.fullmatch(original_task_id)
        or type(version) is not int
        or not 0 <= version <= 100000
        or row.get("status") != "completed"
        or row.get("configuration_matches_source") is not True
        or type(bag_count) is not int
        or bag_count <= 0
    ):
        return None
    try:
        verified_at = datetime.fromisoformat(str(row.get("verified_at", "")))
        if verified_at.utcoffset() is None:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    current_source = str(source_task_id or "").strip()
    if current_source and current_source != original_task_id:
        return None
    return {
        "task_id": task_id,
        "task_version": version,
        "source_task_id": original_task_id,
        "verified_at": verified_at.isoformat(),
    }
