from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import trail_update


class TrailIssueHistoryTest(unittest.TestCase):
    def test_history_is_idempotent_and_keeps_per_issue_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            operation_id = "a" * 64
            database.upsert_trail_issue_exclusion_history(
                operation_id=operation_id,
                actor="jasperchen",
                actor_source="sso",
                actor_verified=True,
                status="pending",
                requested_count=2,
                entries=[
                    {"issue_id": "cn00000001", "comment": "红绿灯"},
                    {"issue_id": "cn00000002", "comment": "泊入"},
                ],
            )
            database.upsert_trail_issue_exclusion_history(
                operation_id=operation_id,
                actor="jasperchen",
                actor_source="sso",
                actor_verified=True,
                status="completed",
                requested_count=2,
                synced_count=2,
                entries=[
                    {"issue_id": "cn00000001", "comment": "红绿灯", "status": "synced"},
                    {"issue_id": "cn00000002", "comment": "泊入", "status": "synced"},
                ],
                message="Trail 回读 2/2 条成功。",
            )
            result = database.list_trail_issue_exclusion_history(limit=10)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["status"], "completed")
            self.assertEqual(result["items"][0]["entries"][1]["comment"], "泊入")

    def test_history_endpoint_uses_bounded_pagination(self) -> None:
        expected = {"items": [], "total": 0, "limit": 100, "offset": 4}
        with patch.object(
            trail_update.database,
            "list_trail_issue_exclusion_history",
            return_value=expected,
        ) as list_history:
            result = asyncio.run(trail_update.trail_issue_exclusion_history(limit=1000, offset=4))
        self.assertEqual(result, expected)
        list_history.assert_called_once_with(limit=100, offset=4)


if __name__ == "__main__":
    unittest.main()
