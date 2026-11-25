"""Single explicit boundary for importing sibling ``ra_auto_triage`` modules.

All ``sys.path`` adjustments and dynamic imports from ``ra_auto_triage`` are
consolidated here so no other module under ``ra_triage_dashboard/app/`` mutates
``sys.path`` directly.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_RA_AUTO_TRIAGE_ROOT = Path(
    os.getenv("RA_AUTO_TRIAGE_ROOT", "").strip()
    or "/volume/home/workspace/ra_auto_triage"
)


def resolve_ra_auto_triage_root(ra_root: str | Path | None = None) -> Path:
    if ra_root is not None and str(ra_root).strip():
        return Path(ra_root).expanduser().resolve()
    env_root = os.getenv("RA_AUTO_TRIAGE_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return DEFAULT_RA_AUTO_TRIAGE_ROOT.expanduser().resolve()


def ensure_ra_auto_triage_on_path(
    ra_root: str | Path | None = None,
    *,
    require_vlm: bool = False,
) -> Path:
    """Resolve and register ``ra_auto_triage`` on ``sys.path`` idempotently."""
    resolved = resolve_ra_auto_triage_root(ra_root)
    if require_vlm and not (resolved / "vlm").is_dir():
        raise FileNotFoundError(f"RA_AUTO_TRIAGE_ROOT missing vlm/: {resolved}")
    root_str = str(resolved)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    importlib.invalidate_caches()
    return resolved


def load_ra_auto_triage_module(
    module_name: str,
    ra_root: str | Path | None = None,
) -> Any:
    """Import a named module from ``ra_auto_triage`` via the adapter boundary."""
    ensure_ra_auto_triage_on_path(ra_root)
    return importlib.import_module(module_name)


def load_trail_reader(ra_root: str | Path | None = None) -> Any:
    """Return ``utils.get_ra_issue_utils.get_self_issue`` from ``ra_auto_triage``."""
    module = load_ra_auto_triage_module("utils.get_ra_issue_utils", ra_root)
    return module.get_self_issue


def load_trail_interface(ra_root: str | Path | None = None) -> Any:
    """Instantiate ``utils.trail_api.TrailInterface`` from ``ra_auto_triage``."""
    module = load_ra_auto_triage_module("utils.trail_api", ra_root)
    return module.TrailInterface()


def load_rd_trail_http(ra_root: str | Path | None = None) -> Any:
    """Instantiate ``tools.daily_auto_triage.rd_review_sync.TrailHTTP``."""
    module = load_ra_auto_triage_module("tools.daily_auto_triage.rd_review_sync", ra_root)
    return module.TrailHTTP()
