from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ra_triage_dashboard.app.system_status import (
    backup_status,
    overall_status,
    volume_status,
)


class SystemStatusTest(unittest.TestCase):
    def test_backup_status_uses_only_valid_named_dumps_and_schedule_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            backup_dir = data_dir / "postgres_backups"
            backup_dir.mkdir()
            (backup_dir / "ra_triage_dashboard-20260802T080000Z.dump").write_bytes(
                b"older"
            )
            latest = backup_dir / "ra_triage_dashboard-20260802T100000Z.dump"
            latest.write_bytes(b"latest")
            latest.with_name(f"{latest.name}.sha256").write_text(
                "checksum\n", encoding="utf-8"
            )
            (backup_dir / "untrusted.dump").write_bytes(b"ignored")
            (backup_dir / ".backup-schedule").write_text(
                "schedule=15 2 * * *\ninstalled_at=2026-08-02T10:01:00Z\n",
                encoding="utf-8",
            )

            result = backup_status(
                data_dir,
                now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
            )

            self.assertTrue(result["available"])
            self.assertEqual(result["count"], 2)
            self.assertEqual(result["latest_age_seconds"], 7200)
            self.assertEqual(result["latest_size_bytes"], len(b"latest"))
            self.assertTrue(result["latest_checksum_present"])
            self.assertTrue(result["schedule_registered"])
            self.assertEqual(result["schedule"], "15 2 * * *")

    def test_overall_status_marks_missing_protection_as_degraded(self) -> None:
        healthy = overall_status(
            database={"ok": True, "backend": "postgresql", "persistent_data": True},
            baseline={"status": "ready", "count": 1071},
            backups={
                "available": True,
                "latest_checksum_present": True,
                "latest_age_seconds": 60,
                "schedule_registered": True,
            },
            volume={"available": True, "free_bytes": 10 * 1024**3},
        )
        self.assertEqual(healthy, {"status": "healthy", "problems": []})

        degraded = overall_status(
            database={"ok": True, "backend": "postgresql", "persistent_data": False},
            baseline={"status": "ready", "count": 1071},
            backups={"available": False, "schedule_registered": False},
            volume={"available": True, "free_bytes": 10 * 1024**3},
        )
        self.assertEqual(degraded["status"], "degraded")
        self.assertIn("database_not_persistent", degraded["problems"])
        self.assertIn("backup_missing", degraded["problems"])
        self.assertIn("backup_schedule_unregistered", degraded["problems"])

    def test_overall_status_checks_every_registered_baseline(self) -> None:
        result = overall_status(
            database={"ok": True, "backend": "sqlite", "persistent_data": False},
            baseline={"status": "ready", "count": 1071},
            baselines=[
                {"id": "0508", "status": "ready", "count": 1071},
                {"id": "0206", "status": "ready", "count": 1326},
                {"id": "0626", "status": "failed", "count": 0},
            ],
            backups={},
            volume={"available": True, "free_bytes": 10 * 1024**3},
        )

        self.assertEqual(result["status"], "degraded")
        self.assertIn("baseline_unavailable", result["problems"])

    def test_volume_status_reports_existing_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = volume_status(Path(directory))
        self.assertTrue(result["available"])
        self.assertGreater(result["total_bytes"], 0)
        self.assertGreaterEqual(result["free_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
