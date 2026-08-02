from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ra_triage_dashboard.app.db import (
    Database,
    _CompatRow,
    _json_load,
    _postgres_sql,
)


class PostgresAdapterUnitTest(unittest.TestCase):
    def test_query_translation_preserves_quoted_question_marks(self) -> None:
        translated = _postgres_sql(
            "SELECT '?' AS literal FROM issues "
            "WHERE issue_id = ? AND title LIKE ?"
        )
        self.assertEqual(
            translated,
            "SELECT '?' AS literal FROM issues "
            "WHERE issue_id = %s AND title ILIKE %s",
        )

    def test_json_filter_casts_jsonb_to_text(self) -> None:
        translated = _postgres_sql(
            "SELECT * FROM annotations ann WHERE ann.tags_json LIKE ? "
            "OR ann.missing_evidence_json LIKE ?"
        )
        self.assertIn("ann.tags_json::text ILIKE %s", translated)
        self.assertIn("ann.missing_evidence_json::text ILIKE %s", translated)

    def test_compat_row_matches_used_sqlite_row_surface(self) -> None:
        row = _CompatRow(
            {
                "created_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
                "payload": {"ok": True},
            }
        )
        self.assertEqual(row[0], "2026-08-02T00:00:00+00:00")
        self.assertEqual(row["payload"], {"ok": True})
        self.assertEqual(row.keys(), ("created_at", "payload"))

    def test_json_loader_accepts_native_jsonb_values(self) -> None:
        payload = {"labels": ["误触发"]}
        self.assertIs(_json_load(payload, {}), payload)
        self.assertEqual(_json_load(json.dumps(payload), {}), payload)

    def test_database_keeps_path_constructor_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triage.sqlite3"
            database = Database(path)
            self.assertEqual(database.backend, "sqlite")
            self.assertEqual(database.storage_label, "sqlite-mvp")
            database.init()
            self.assertEqual(database.change_revision(), 0)
            runtime = database.runtime_status()
            self.assertTrue(runtime["ok"])
            self.assertEqual(runtime["backend"], "sqlite")
            self.assertEqual(runtime["revision"], 0)
            self.assertGreaterEqual(runtime["latency_ms"], 0)

    def test_postgres_requires_migration_directory_before_connecting(self) -> None:
        database = Database("postgresql:///ra_triage_test")
        self.assertEqual(database.backend, "postgresql")
        self.assertEqual(database.storage_label, "postgresql")
        with self.assertRaisesRegex(RuntimeError, "migrations directory"):
            database._apply_postgres_migrations()


if __name__ == "__main__":
    unittest.main()
