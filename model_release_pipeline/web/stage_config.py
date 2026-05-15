"""Web-owned stage configuration overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


STAGE_CONFIG_KEY = "web_stage_config"
SUPPORTED_STAGE_KEYS = {"handoff", "dcl", "sim_plan"}
ACTION_STAGE_KEYS = {
    "apply-handoff": "handoff",
    "dcl": "dcl",
    "sim-plan": "sim_plan",
}
ALLOWED_FIELDS = {
    "branch",
    "checkout_branch",
    "update_diff_ids",
    "sim_plan",
    "plans",
    "revision_id",
    "priority",
    "time_sensitive_hour",
    "lint",
    "allow_dirty",
}


def defaults_path(runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir).expanduser()
    return runs_dir.parent / f"{runs_dir.name}_web_stage_defaults.json"


def action_stage_key(action: str) -> Optional[str]:
    return ACTION_STAGE_KEYS.get(action)


def read_defaults(runs_dir: Path) -> Dict[str, Any]:
    path = defaults_path(runs_dir)
    if not path.exists():
        return {}
    return clean_stage_config(json.loads(path.read_text(encoding="utf-8")))


def write_defaults(runs_dir: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    path = defaults_path(runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = clean_stage_config(config)
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return cleaned


def record_stage_config(record: Dict[str, Any]) -> Dict[str, Any]:
    return clean_stage_config(record.get(STAGE_CONFIG_KEY) or {})


def update_stage_config(
    existing: Dict[str, Any],
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    merged = clean_stage_config(existing)
    if not isinstance(patch, dict):
        return merged
    for stage, raw_values in patch.items():
        if stage not in SUPPORTED_STAGE_KEYS or not isinstance(raw_values, dict):
            continue
        values = clean_stage_values(raw_values)
        if values:
            merged[stage] = values
        else:
            merged.pop(stage, None)
    return merged


def effective_stage_config(
    stage: str,
    defaults: Dict[str, Any],
    run_config: Dict[str, Any],
    immediate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for source in (
        clean_stage_config(defaults).get(stage) or {},
        clean_stage_config(run_config).get(stage) or {},
    ):
        merged.update(source)
    if immediate is not None:
        merged.update(clean_stage_values(immediate, keep_empty_branch=True))
    return merged


def clean_stage_config(config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for stage, values in config.items():
        if stage not in SUPPORTED_STAGE_KEYS or not isinstance(values, dict):
            continue
        stage_values = clean_stage_values(values)
        if stage_values:
            cleaned[stage] = stage_values
    return cleaned


def clean_stage_values(
    values: Dict[str, Any],
    *,
    keep_empty_branch: bool = False,
) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for raw_key, raw_value in values.items():
        key = "update_diff_ids" if raw_key in {"update_diff_id", "cr", "crs"} else raw_key
        key = "branch" if key == "name" else key
        if key not in ALLOWED_FIELDS:
            continue
        if key in {"lint", "allow_dirty"}:
            if isinstance(raw_value, str):
                cleaned[key] = raw_value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                cleaned[key] = bool(raw_value)
            continue
        if key in {"plans"}:
            plans = parse_sim_plans(raw_value)
            if plans:
                cleaned[key] = plans
            continue
        if key in {"revision_id", "priority"}:
            text = str(raw_value or "").strip()
            if text:
                if not text.isdigit():
                    raise ValueError(f"{key} must be an integer.")
                cleaned[key] = int(text)
            continue
        if key == "time_sensitive_hour":
            text = str(raw_value or "").strip()
            if text:
                cleaned[key] = float(text)
            continue
        if key == "update_diff_ids":
            diff_ids = parse_update_diff_ids(raw_value)
            if diff_ids:
                cleaned[key] = diff_ids
            continue
        value = str(raw_value or "").strip()
        if value or (key == "branch" and keep_empty_branch):
            cleaned[key] = value
    return cleaned


def parse_sim_plans(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: Iterable[Any]
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        text = str(value).replace("\n", ",")
        raw_items = [part.strip() for part in text.split(",")]
    plans = []
    for item in raw_items:
        text = str(item or "").strip()
        if text:
            plans.append(text)
    return plans


def parse_update_diff_ids(value: Any) -> list[int]:
    if value is None:
        return []
    raw_items: Iterable[Any]
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        text = str(value).replace("\n", ",")
        raw_items = [part.strip() for part in text.split(",")]
    diff_ids = []
    for item in raw_items:
        if item in (None, ""):
            continue
        text = str(item).strip()
        if text.upper().startswith("CR"):
            text = text[2:].strip()
        if not text.isdigit():
            raise ValueError("update_diff_ids must be integers or comma-separated CR ids.")
        diff_ids.append(int(text))
    return diff_ids
