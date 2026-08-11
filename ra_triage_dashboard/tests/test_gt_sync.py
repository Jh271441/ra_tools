from __future__ import annotations

import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app import http_support as gt_http
from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.gt_sync import (
    TrailGtSyncResult,
    _source_timestamp,
    read_trail_gt_labels,
)
from ra_triage_dashboard.app.settings import Settings


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

    def test_settings_default_to_all_baselines_every_thirty_minutes(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.gt_sync_baseline_ids, ("*",))
        self.assertEqual(settings.gt_sync_interval_seconds, 1800)

        with patch.dict(
            "os.environ",
            {"DASHBOARD_GT_SYNC_BASELINE_ID": "0508"},
            clear=True,
        ):
            legacy = Settings.from_env()
        self.assertEqual(legacy.gt_sync_baseline_ids, ("0508",))

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

    def test_multi_baseline_sync_isolated_and_aggregated(self) -> None:
        second_scope = "release0626_test"
        self.db.replace_baseline_scope(
            scope=second_scope,
            rows=[
                {"issue_id": "cn4", "gt_label": "误触发"},
                {"issue_id": "cn5", "gt_label": "无需协助"},
            ],
            source="test_baseline_0626",
        )
        registry = BaselineRegistry(
            entries=(
                BaselineEntry(
                    id="0508",
                    label="0508",
                    scope=self.scope,
                    loader="trail_label_baseline",
                    xlsx=Path(self.temp.name) / "0508.xlsx",
                ),
                BaselineEntry(
                    id="0626",
                    label="0626 抽检",
                    scope=second_scope,
                    loader="spotcheck_zh",
                    xlsx=Path(self.temp.name) / "0626.xlsx",
                ),
            )
        )
        fake_settings = SimpleNamespace(
            gt_sync_baseline_ids=("*",),
            gt_sync_enabled=True,
            gt_sync_interval_seconds=1800,
            gt_sync_view_id=1000,
            gt_sync_chunk_size=160,
            ra_auto_triage_root=Path(self.temp.name),
        )

        def fake_read(*, issue_ids, view_id, **_):
            labels = {
                "cn1": "正确触发",
                "cn2": "正确触发",
                "cn3": "无需协助",
                "cn4": "无需协助",
                "cn5": "无需协助",
            }
            rows = [
                {
                    "issue_id": issue_id,
                    "gt_label": labels[issue_id],
                    "source_updated_at": "2026-08-11T01:00:00+00:00",
                    "source_updated_by": "tester",
                }
                for issue_id in issue_ids
            ]
            return TrailGtSyncResult(
                rows=rows,
                queried_issues=len(rows),
                returned_issues=len(rows),
                fields_visible=("ra_merge_result",),
                view_id=view_id,
                complete=True,
                message="complete",
            )

        with patch.multiple(
            gt_http,
            settings=fake_settings,
            baseline_registry=registry,
            database=self.db,
            runtime_state={"gt_sync": {}},
            gt_sync_lock=threading.Lock(),
            read_trail_gt_labels=fake_read,
        ):
            result = gt_http.sync_authoritative_gt(
                baseline_ids=["0508", "0626"],
                trigger="test",
            )
            only_0626 = gt_http.gt_sync_status(["0626"])

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["baseline_ids"], ["0508", "0626"])
        self.assertEqual(len(result["baselines"]), 2)
        self.assertEqual(result["source_row_count"], 5)
        self.assertEqual(result["last_check_change_count"], 2)
        self.assertEqual(only_0626["baseline_id"], "0626")
        self.assertEqual(only_0626["source_row_count"], 2)
        with self.db.connect() as conn:
            labels = {
                str(row["issue_id"]): str(row["gt_label"])
                for row in conn.execute(
                    "SELECT issue_id, gt_label FROM issues WHERE baseline_scope IN (?, ?)",
                    (self.scope, second_scope),
                ).fetchall()
            }
        self.assertEqual(labels["cn1"], "正确触发")
        self.assertEqual(labels["cn4"], "无需协助")

    def test_multi_baseline_failure_does_not_block_next_scope(self) -> None:
        second_scope = "release0626_test"
        self.db.replace_baseline_scope(
            scope=second_scope,
            rows=[{"issue_id": "cn4", "gt_label": "误触发"}],
            source="test_baseline_0626",
        )
        registry = BaselineRegistry(
            entries=(
                BaselineEntry(
                    "0508",
                    "0508",
                    self.scope,
                    "trail_label_baseline",
                    Path("0508.xlsx"),
                ),
                BaselineEntry(
                    "0626",
                    "0626",
                    second_scope,
                    "spotcheck_zh",
                    Path("0626.xlsx"),
                ),
            )
        )
        fake_settings = SimpleNamespace(
            gt_sync_baseline_ids=("*",),
            gt_sync_enabled=True,
            gt_sync_interval_seconds=1800,
            gt_sync_view_id=1000,
            gt_sync_chunk_size=160,
            ra_auto_triage_root=Path(self.temp.name),
        )

        def fake_read(*, issue_ids, view_id, **_):
            ids = list(issue_ids)
            if "cn1" in ids:
                return TrailGtSyncResult(
                    [], len(ids), 0, (), view_id, False, "partial"
                )
            return TrailGtSyncResult(
                [
                    {
                        "issue_id": "cn4",
                        "gt_label": "无需协助",
                        "source_updated_at": "",
                        "source_updated_by": "",
                    }
                ],
                1,
                1,
                ("ra_merge_result",),
                view_id,
                True,
                "complete",
            )

        with patch.multiple(
            gt_http,
            settings=fake_settings,
            baseline_registry=registry,
            database=self.db,
            runtime_state={"gt_sync": {}},
            gt_sync_lock=threading.Lock(),
            read_trail_gt_labels=fake_read,
        ):
            result = gt_http.sync_authoritative_gt(trigger="test")

        self.assertEqual(result["status"], "failed")
        by_id = {item["baseline_id"]: item for item in result["baselines"]}
        self.assertEqual(by_id["0508"]["status"], "failed")
        self.assertEqual(by_id["0626"]["status"], "ready")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT gt_label FROM issues WHERE baseline_scope = ? AND issue_id = ?",
                (second_scope, "cn4"),
            ).fetchone()
        self.assertEqual(row["gt_label"], "无需协助")


if __name__ == "__main__":
    unittest.main()
