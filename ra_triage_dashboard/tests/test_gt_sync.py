from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.gt_sync import _source_timestamp, read_trail_gt_labels


class _FakeFrame:
    def __init__(self, rows: list[dict[str, object]]):
        self._rows = rows
        self.columns = list(rows[0]) if rows else []

    def __len__(self) -> int:
        return len(self._rows)

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return list(self._rows)


class AuthoritativeGtSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "triage.sqlite3")
        self.db.init()
        self.scope = "release0508_test"
        self.baseline = [
            {"issue_id": "cn1", "gt_label": "误触发"},
            {"issue_id": "cn2", "gt_label": "正确触发"},
            {"issue_id": "cn3", "gt_label": "无需协助"},
        ]
        self.db.replace_baseline_scope(
            scope=self.scope,
            rows=self.baseline,
            source="test_baseline",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    @staticmethod
    def _snapshot() -> list[dict[str, str]]:
        return [
            {
                "issue_id": "cn1",
                "gt_label": "正确触发",
                "source_updated_at": "2026-08-10T12:31:07+00:00",
                "source_updated_by": "testing_engineer",
            },
            {
                "issue_id": "cn2",
                "gt_label": "正确触发",
                "source_updated_at": "2026-08-10T12:31:07+00:00",
                "source_updated_by": "testing_engineer",
            },
            {
                "issue_id": "cn3",
                "gt_label": "误触发",
                "source_updated_at": "2026-08-10T12:31:07+00:00",
                "source_updated_by": "testing_engineer",
            },
        ]

    def _apply(self, rows: list[dict[str, str]] | None = None) -> dict:
        return self.db.apply_gt_sync_snapshot(
            scope=self.scope,
            rows=rows or self._snapshot(),
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
            trigger="test",
            requested_by="jasperchen",
            requested_by_source="test",
            requested_by_verified=True,
        )

    def _labels(self) -> dict[str, str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT issue_id, gt_label FROM issues WHERE baseline_scope = ?",
                (self.scope,),
            ).fetchall()
        return {str(row["issue_id"]): str(row["gt_label"] or "") for row in rows}

    def test_full_snapshot_updates_only_diffs_and_preserves_last_apply(self) -> None:
        revision_before = self.db.change_revision()
        state = self._apply()
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["source_row_count"], 3)
        self.assertEqual(state["last_check_change_count"], 2)
        self.assertEqual(state["last_applied_change_count"], 2)
        self.assertEqual(state["source_updated_at"], "2026-08-10T12:31:07+00:00")
        self.assertEqual(
            self._labels(),
            {"cn1": "正确触发", "cn2": "正确触发", "cn3": "误触发"},
        )
        self.assertGreater(self.db.change_revision(), revision_before)

        revision_after_apply = self.db.change_revision()
        applied_at = state["last_applied_at"]
        second = self._apply()
        self.assertEqual(second["last_check_change_count"], 0)
        self.assertEqual(second["last_applied_change_count"], 2)
        self.assertEqual(second["last_applied_at"], applied_at)
        self.assertEqual(self.db.change_revision(), revision_after_apply)

    def test_partial_or_invalid_snapshot_fails_closed(self) -> None:
        before = self._labels()
        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            self._apply(self._snapshot()[:-1])
        self.assertEqual(self._labels(), before)

        invalid = self._snapshot()
        invalid[0] = {**invalid[0], "gt_label": "待确认"}
        with self.assertRaisesRegex(ValueError, "非法三分类"):
            self._apply(invalid)
        self.assertEqual(self._labels(), before)

    def test_persisted_overlay_survives_baseline_bootstrap(self) -> None:
        self._apply()
        self.db.replace_baseline_scope(
            scope=self.scope,
            rows=self.baseline,
            source="old_xlsx_bootstrap",
        )
        self.assertEqual(
            self._labels(),
            {"cn1": "正确触发", "cn2": "正确触发", "cn3": "误触发"},
        )

    def test_failure_keeps_last_successful_snapshot(self) -> None:
        applied = self._apply()
        failed = self.db.record_gt_sync_failure(
            scope=self.scope,
            error_text="upstream timeout",
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
            trigger="periodic",
            requested_by="system",
            requested_by_source="service_periodic",
            requested_by_verified=False,
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["last_applied_at"], applied["last_applied_at"])
        self.assertEqual(failed["last_applied_change_count"], 2)
        self.assertEqual(
            self._labels(),
            {"cn1": "正确触发", "cn2": "正确触发", "cn3": "误触发"},
        )

    def test_trail_millisecond_timestamp_is_normalized(self) -> None:
        self.assertEqual(
            _source_timestamp(1786360267036),
            "2026-08-10T11:11:07+00:00",
        )

    def test_trail_reader_normalizes_labels_and_requires_full_coverage(self) -> None:
        responses = {
            "cn1": {
                "issue_id": "cn1",
                "ra_merge_result": "成功",
                "last_modify_time": 1786360267036,
                "last_modificator": "testing_engineer",
            },
            "cn2": {
                "issue_id": "cn2",
                "ra_merge_result": "误触发",
                "last_modify_time": 1786360267036,
                "last_modificator": "testing_engineer",
            },
        }

        def get_self_issue(conditions, *, view_id, size):
            requested = conditions[0]["val"]
            return _FakeFrame([responses[item] for item in requested if item in responses])

        package = types.ModuleType("utils")
        package.__path__ = []  # type: ignore[attr-defined]
        module = types.ModuleType("utils.get_ra_issue_utils")
        module.get_self_issue = get_self_issue  # type: ignore[attr-defined]
        with patch.dict(
            "sys.modules",
            {"utils": package, "utils.get_ra_issue_utils": module},
        ):
            result = read_trail_gt_labels(
                ra_root=Path(self.temp.name),
                issue_ids=["cn1", "cn2"],
                view_id=1000,
                chunk_size=1,
            )
            partial = read_trail_gt_labels(
                ra_root=Path(self.temp.name),
                issue_ids=["cn1", "cn2", "cn3"],
                view_id=1000,
                chunk_size=2,
            )
        self.assertTrue(result.complete, result.message)
        self.assertEqual(
            {row["issue_id"]: row["gt_label"] for row in result.rows},
            {"cn1": "正确触发", "cn2": "误触发"},
        )
        self.assertFalse(partial.complete)
        self.assertEqual(partial.returned_issues, 2)


if __name__ == "__main__":
    unittest.main()
