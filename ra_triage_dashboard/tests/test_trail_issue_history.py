from __future__ import annotations

import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import trail_update


class TrailIssueHistoryTest(unittest.TestCase):
    def test_history_binds_native_boolean_for_postgresql(self) -> None:
        """A PostgreSQL boolean must not receive SQLite's 0/1 integer."""

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            captured: dict[str, object] = {}

            class _Result:
                def __init__(self, row: dict[str, object] | None) -> None:
                    self._row = row

                def fetchone(self) -> dict[str, object] | None:
                    return self._row

            class _Connection:
                def execute(self, query: str, params: tuple[object, ...] = ()) -> _Result:
                    if "SELECT created_at" in query:
                        return _Result(None)
                    if "INSERT INTO trail_issue_exclusion_history" in query:
                        captured["values"] = params
                        return _Result(None)
                    if "SELECT operation_id, created_at" in query:
                        values = captured["values"]
                        assert isinstance(values, tuple)
                        return _Result(
                            {
                                "operation_id": values[0],
                                "created_at": values[1],
                                "updated_at": values[2],
                                "actor": values[3],
                                "actor_source": values[4],
                                "actor_verified": values[5],
                                "status": values[6],
                                "requested_count": values[7],
                                "synced_count": values[8],
                                "failed_count": values[9],
                                "entries_json": values[10],
                                "message": values[11],
                            }
                        )
                    raise AssertionError(f"Unexpected query: {query}")

            @contextmanager
            def fake_connect():
                yield _Connection()

            with patch.object(database, "connect", fake_connect):
                database.upsert_trail_issue_exclusion_history(
                    operation_id="b" * 64,
                    actor_verified=True,
                    entries=[{"issue_id": "cn00000001"}],
                )
            values = captured["values"]
            assert isinstance(values, tuple)
            self.assertIs(values[5], True)

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

    def test_history_keeps_bounded_historical_excel_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_trail_issue_exclusion_history(
                operation_id="c" * 64,
                entries=[
                    {
                        "issue_id": "cn00000001",
                        "comment": "历史抽检排除来源：0206 抽检。",
                        "source": {
                            "kind": "historical_spotcheck_xlsx",
                            "source_id": "spotcheck-0206",
                            "label": "0206 抽检",
                            "baseline_id": "0206",
                            "filename": "release0206版本 RA问题review.xlsx",
                            "sha256": "a" * 64,
                            "row_number": 269,
                            "issue_id": "cn00000001",
                            "column": "是否排除",
                            "value": "是",
                            "untrusted_extra": "must not persist",
                        },
                    }
                ],
            )
            result = database.list_trail_issue_exclusion_history(limit=10)
        source = result["items"][0]["entries"][0]["source"]
        self.assertEqual(source["source_id"], "spotcheck-0206")
        self.assertEqual(source["row_number"], 269)
        self.assertNotIn("untrusted_extra", source)

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
