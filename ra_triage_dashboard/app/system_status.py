from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKUP_NAME_RE = re.compile(
    r"^ra_triage_dashboard-(?P<stamp>[0-9]{8}T[0-9]{6}Z)\.dump$"
)


def backup_status(data_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    backup_dir = data_dir / "postgres_backups"
    schedule_file = backup_dir / ".backup-schedule"
    schedule = ""
    installed_at = ""
    try:
        if schedule_file.is_file() and schedule_file.stat().st_size <= 1024:
            for line in schedule_file.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if not separator:
                    continue
                if key == "schedule":
                    schedule = value.strip()[:64]
                elif key == "installed_at":
                    installed_at = value.strip()[:64]
    except OSError:
        schedule = ""
        installed_at = ""

    backups: list[tuple[datetime, Path]] = []
    try:
        candidates = tuple(backup_dir.iterdir()) if backup_dir.is_dir() else ()
    except OSError:
        candidates = ()
    for candidate in candidates:
        match = BACKUP_NAME_RE.fullmatch(candidate.name)
        if not match or not candidate.is_file():
            continue
        try:
            created_at = datetime.strptime(
                match.group("stamp"), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        backups.append((created_at, candidate))
    backups.sort(key=lambda item: item[0], reverse=True)

    result: dict[str, Any] = {
        "available": bool(backups),
        "count": len(backups),
        "schedule_registered": bool(schedule),
        "schedule": schedule,
        "schedule_installed_at": installed_at,
        "latest_created_at": "",
        "latest_age_seconds": None,
        "latest_size_bytes": 0,
        "latest_checksum_present": False,
    }
    if not backups:
        return result
    created_at, latest = backups[0]
    try:
        size_bytes = latest.stat().st_size
        checksum_present = latest.with_name(f"{latest.name}.sha256").is_file()
    except OSError:
        return result
    result.update(
        {
            "latest_created_at": created_at.isoformat(),
            "latest_age_seconds": max(
                0, int((current_time - created_at).total_seconds())
            ),
            "latest_size_bytes": size_bytes,
            "latest_checksum_present": checksum_present,
        }
    )
    return result


def volume_status(data_dir: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(data_dir)
    except OSError:
        return {
            "available": False,
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "used_percent": 0,
        }
    used_percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0
    return {
        "available": True,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": used_percent,
    }


def overall_status(
    *,
    database: dict[str, Any],
    baseline: dict[str, Any],
    backups: dict[str, Any],
    volume: dict[str, Any],
) -> dict[str, Any]:
    problems: list[str] = []
    if not database.get("ok"):
        problems.append("database_unavailable")
    if database.get("backend") == "postgresql" and not database.get(
        "persistent_data"
    ):
        problems.append("database_not_persistent")
    if baseline.get("status") != "ready" or int(baseline.get("count") or 0) <= 0:
        problems.append("baseline_unavailable")
    if database.get("backend") == "postgresql":
        if not backups.get("available"):
            problems.append("backup_missing")
        elif not backups.get("latest_checksum_present"):
            problems.append("backup_checksum_missing")
        elif int(backups.get("latest_age_seconds") or 0) > 36 * 3600:
            problems.append("backup_stale")
        if not backups.get("schedule_registered"):
            problems.append("backup_schedule_unregistered")
    if not volume.get("available") or int(volume.get("free_bytes") or 0) < 1024**3:
        problems.append("disk_space_low")
    return {
        "status": "healthy" if not problems else "degraded",
        "problems": problems,
    }
