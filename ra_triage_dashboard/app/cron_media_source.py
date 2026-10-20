"""Read bounded sidecar receipts for the selected daily cohort, without running it."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time

MAX_BYTES = 2_000_000
ISSUE_RE = re.compile(r"[A-Za-z0-9_-]{3,128}")
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _read(root: Path, path: Path, fallback=None):
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or path.is_symlink():
        raise ValueError("receipt escapes source root")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return fallback
    if len(data) > MAX_BYTES:
        raise ValueError("receipt too large")
    return json.loads(data)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _ids(rows):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("invalid cohort")
    values = [row.get("issue_id") for row in rows if isinstance(row, dict)]
    if len(values) != len(rows) or any(not isinstance(i, str) or not ISSUE_RE.fullmatch(i) for i in values):
        raise ValueError("invalid cohort members")
    if len(values) != len(set(values)):
        raise ValueError("duplicate cohort members")
    return set(values)


def _day(root, report, bags, day, replacement):
    work = report / "daily" / day
    status = _read(root, work / "status.json", {})
    groups = sorted((report / "daily").glob(day + "*"))[:8]
    groups = [p for p in groups if p.name == day or re.fullmatch(day + r"-supplement-\d{8}", p.name)]
    publications = [p / "media-publication" for p in groups] + [report / "media-publication"]
    if replacement:
        entry, replacement_dir = replacement
        name = entry.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
            raise ValueError("invalid replacement name")
        payload = _read(root, replacement_dir / (name + ".json"), {})
        members = _ids(payload.get("results"))
        receipt = _read(root, replacement_dir / (name + "-receipt.json"), {})
        assignment = entry.get("assignment") or {}
    else:
        # Superseded partial runs never become a daily full-run total.
        if (work / "superseded-by-full-run.json").exists():
            return None
        members = _ids(_read(root, work / "media-source.json", []))
        receipt = _read(root, work / "imports" / ("daily-review-" + day + "-receipt.json"), {})
        assignment = _read(root, work / "assignment.json", {})
    total = len(members)
    if replacement and (total != entry.get("count") or receipt.get("run_id") != entry.get("run_id")):
        raise ValueError("replacement cohort mismatch")
    verified = 0
    verified_at = 0
    for issue_id in members:
        for folder in publications:
            item = _read(root, folder / (issue_id + ".json"), {})
            if item.get("issue_id") == issue_id and item.get("state") == "verified" and item.get("bev_probe") and item.get("camera_probe"):
                verified += 1
                verified_at = max(verified_at, item.get("verified_at", 0))
                break
    imported = receipt.get("count") if receipt.get("run_id") else None
    assigned = None
    if assignment.get("run_id") == receipt.get("run_id") and receipt.get("run_id"):
        counts = (assignment.get("assigned") or {}).values()
        if all(_count(n) is not None for n in counts) and assignment.get("overlap") == 0:
            assigned = sum(counts)
    camera = _read(root, bags / "daily" / day / "camera" / "status.json", {}) if not replacement else {}
    # Replacement cohorts may combine old queues; joint receipts are the safe
    # lower bound. Never attach a 74-case queue counter to a 90-case full Run.
    camera_verified = verified if replacement else max(verified, _count(camera.get("completed")) or 0)
    camera_total = total if replacement else _count(camera.get("total"))
    orion = [(_read(root, group / "status.json", {}).get("bev") or {}) for group in groups]
    orion = [item for item in orion if item]
    original_failed = sum(_count(item.get("failed")) or 0 for item in orion)
    original_completed = sum(_count(item.get("completed")) or 0 for item in orion)
    original_total = sum(_count(item.get("total")) or 0 for item in orion)
    recovery = _read(root, work / "recovery-status.json", {})
    retry = recovery.get("retry") or {}
    local_results = []
    for item in sorted((bags / "daily" / day / "recovery" / "local").glob("*/*/result.json"))[:2000]:
        local_results.append(_read(root, item, {}))
    local_verified = sum(item.get("state") == "verified" for item in local_results)
    final = _read(root, work / "final-failures.json", {}).get("failures", status.get("final_failures", []))
    failure_ids = [item.get("issue_id") for item in final if isinstance(item, dict) and item.get("issue_id") in members]
    failure_ids = sorted(set(failure_ids))
    state = "empty" if total == 0 and status.get("state") == "empty" else "complete" if total and verified == total else status.get("state", "waiting")
    if replacement and verified != total:
        state = "collecting"  # The original partial-run terminal state has another scope.
    return dict(
        day=day, state=state, selected=total, imported=imported, assigned=assigned,
        verified=verified, failure_count=len(failure_ids), failure_ids=failure_ids,
        run_id=receipt.get("run_id", ""), updated_at=max(status.get("updated_at", 0), verified_at),
        camera_verified=camera_verified, camera_total=camera_total,
        bev_verified=verified, original_orion_completed=original_completed if orion else None,
        original_orion_failed=original_failed if orion else None,
        original_orion_total=original_total if orion else None,
        retry_completed=_count(retry.get("completed")), retry_failed=_count(retry.get("failed")),
        retry_state=str(retry.get("status") or "not_observed"),
        local_attempts=len(local_results), local_verified=local_verified,
    )


def media_snapshot(ra_root: Path) -> dict:
    report = ra_root / "reports" / "manual_sidecar_20261019"
    bags = ra_root / "bags" / "manual_sidecar_20261019"
    heartbeat = _read(ra_root, report / "heartbeat.json")
    if not isinstance(heartbeat, dict):
        raise ValueError("sidecar heartbeat unavailable")
    error = _read(ra_root, report / "controller-error.json", {})
    enabled = _read(ra_root, report / "daily-enabled.json", {})
    replacements = {}
    for folder in sorted(ra_root.glob("reports/manual_sidecar_20261019/full-replacement-*"))[-5:]:
        for item in _read(ra_root, folder / "complete.json", {}).get("new", [])[:30]:
            if DAY_RE.fullmatch(str(item.get("day", ""))):
                replacements[item["day"]] = (item, folder)
    days = set(replacements)
    for folder in (report / "daily").glob("*"):
        if folder.is_dir() and DAY_RE.fullmatch(folder.name):
            days.add(folder.name)
    rows = []
    for day in sorted(days, reverse=True)[:30]:
        row = _day(ra_root, report, bags, day, replacements.get(day))
        if row is not None:
            rows.append(row)
    checked = heartbeat.get("checked_at")
    fresh = type(checked) in (int, float) and 0 <= time.time() - checked < 300
    policy = heartbeat.get("recovery_policy") or {}
    return {
        "heartbeat_at": checked, "stale": not fresh,
        "controller_error": error.get("active") is True,
        "enabled": enabled.get("enabled") is True,
        "runs": rows,
        "policy": {k: _count(policy.get(k)) for k in (
            "orion_retry_count", "local_max_attempts", "local_workers", "max_missing_count",
            "camera_bag_retention_after_publish_seconds",
        )},
    }
