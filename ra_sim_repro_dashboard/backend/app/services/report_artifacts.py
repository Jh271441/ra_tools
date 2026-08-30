from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


COHORT_TRUTH = {
    "positive_auto": True,
    "positive_manual": True,
    "negative_auto": False,
}
VALID_UPLOAD_STATUSES = {"uploaded", "existing"}


def build_manifest_scenario_index(
    metadata: dict[str, Any],
    version_key: str,
) -> dict[str, dict[str, Any]]:
    """Build a source/truth index from the full-release upload manifest."""
    artifact = metadata.get("source_manifest")
    if not artifact:
        return {}
    path = resolve_report_path(str(artifact))
    rows = _read_csv(path)
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("release") or "").strip() != version_key:
            continue
        scenario_id = canonical_scenario_id(row.get("scenario_id"))
        cohort = str(row.get("cohort") or "").strip()
        upload_status = str(row.get("upload_status") or "").strip()
        if not scenario_id or cohort not in COHORT_TRUTH:
            continue
        if upload_status not in VALID_UPLOAD_STATUSES:
            continue
        source_labels = [version_key, cohort]
        index[scenario_id] = {
            "scenario_id": scenario_id,
            "scenario_name": "",
            "issue_id": _clean(row.get("issue_id")),
            "signature": "",
            # This legacy field is the business truth label used by TP/FP/FN/TN.
            "road_triggered": COHORT_TRUTH[cohort],
            "truth_positive": COHORT_TRUTH[cohort],
            "source_groups": [cohort],
            "source_labels": source_labels,
            "raw_source": row,
        }
    return index


def load_release_metrics(metadata: dict[str, Any], version_key: str) -> dict[str, Any]:
    artifact = metadata.get("result_metrics")
    if not artifact:
        return {}
    payload = _read_json(resolve_report_path(str(artifact)))
    per_release = payload.get("per_release") or {}
    value = per_release.get(version_key) if isinstance(per_release, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def load_binary_backtest_sources(
    config: dict[str, Any],
    target_version: str,
) -> dict[str, dict[str, Any]]:
    """Load per-source-release truth counts for one target binary."""
    backtest = config.get("binary_backtest") or {}
    artifact = backtest.get("result_metrics")
    if not artifact:
        return {}
    path = resolve_report_path(str(artifact))
    if not path.exists():
        return {}
    payload = _read_json(path)
    targets = payload.get("targets") or {}
    target = targets.get(target_version) if isinstance(targets, dict) else None
    if not isinstance(target, dict) or target.get("quality_gate_passed") is not True:
        return {}
    sources = target.get("sources") if isinstance(target, dict) else None
    if not isinstance(sources, dict):
        return {}
    normalized = {
        str(version): dict(metrics)
        for version, metrics in sources.items()
        if isinstance(metrics, dict)
    }
    declared_sources = target.get("source_releases")
    if isinstance(declared_sources, list) and {
        str(version) for version in declared_sources
    } != set(normalized):
        return {}
    try:
        window_size = int(target.get("window_size"))
    except (TypeError, ValueError):
        return {}
    if window_size <= 0 or len(normalized) != window_size:
        return {}
    for metrics in normalized.values():
        try:
            expected = int(metrics.get("expected"))
            evaluated = int(metrics.get("evaluated"))
            dpe_coverage = float(metrics.get("dpe_coverage"))
        except (TypeError, ValueError):
            return {}
        if expected <= 0 or evaluated != expected or dpe_coverage < 1.0:
            return {}
        cohorts = metrics.get("cohorts")
        if not isinstance(cohorts, dict) or set(cohorts) != set(COHORT_TRUTH):
            return {}
        for cohort_name in COHORT_TRUTH:
            cohort = cohorts.get(cohort_name)
            if not isinstance(cohort, dict):
                return {}
            try:
                cohort_expected = int(cohort.get("expected"))
                cohort_evaluated = int(cohort.get("evaluated"))
                trigger_rate = float(cohort.get("trigger_rate"))
            except (TypeError, ValueError):
                return {}
            if (
                cohort_expected <= 0
                or cohort_evaluated != cohort_expected
                or not 0.0 <= trigger_rate <= 1.0
            ):
                return {}
    return normalized


def resolve_report_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else settings.report_dir / path


def canonical_scenario_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    stat = path.stat()
    return _read_csv_versioned(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=16)
def _read_csv_versioned(
    path_text: str,
    _mtime_ns: int,
    _size: int,
) -> tuple[dict[str, str], ...]:
    with Path(path_text).open("r", encoding="utf-8", newline="") as fh:
        return tuple(dict(row) for row in csv.DictReader(fh))


def _read_json(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return _read_json_versioned(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=16)
def _read_json_versioned(
    path_text: str,
    _mtime_ns: int,
    _size: int,
) -> dict[str, Any]:
    with Path(path_text).open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else {}


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
