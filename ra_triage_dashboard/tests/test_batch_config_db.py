from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


class BatchConfigDatabaseTest(unittest.TestCase):
    @staticmethod
    def _create_job(database: Database, issue_id: str = "cn12345") -> dict:
        return database.create_batch_prediction_job(
            name="queued experiment",
            issue_ids=[issue_id],
            requested_by="jasper",
            requested_model_id="auto",
            resolved_model_id="Qwen3.5/base",
            model_source="ra_model_gateway",
            catalog_sha256="a" * 64,
            model_validation_status="validated",
            prompt_version="stuck_triage_auto_opt_api",
            prompt_template="三分类：误触发、正确触发、无需协助。",
            prompt_template_sha256="b" * 64,
            prompt_mode="custom",
            input_profile="camera_ra_event",
            input_config={"profile_id": "camera_ra_event"},
        )

    def test_change_revision_tracks_committed_shared_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            initial = database.change_revision()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            after_issue = database.change_revision()
            self.assertGreater(after_issue, initial)
            database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="shared update",
                author="jasper",
            )
            self.assertGreater(database.change_revision(), after_issue)

    def test_missing_evidence_catalog_is_shared_and_descriptive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            initial = database.change_revision()
            item = database.create_missing_evidence(
                label="绕行空间缺失",
                hint="未确认相邻车道是否存在可行绕行空间",
                created_by="jasperchen",
            )
            self.assertTrue(item["key"].startswith("custom:"))
            self.assertEqual(item["label"], "绕行空间缺失")
            self.assertEqual(
                database.list_missing_evidence_catalog(),
                [item],
            )
            self.assertGreater(database.change_revision(), initial)
            updated = database.update_missing_evidence(
                key=item["key"],
                label="绕行空间与时序缺失",
                hint="未确认可行绕行空间或关键时序证据",
                updated_by="other",
            )
            self.assertEqual(updated["key"], item["key"])
            self.assertEqual(updated["label"], "绕行空间与时序缺失")
            self.assertEqual(updated["active"], 1)
            deleted = database.delete_missing_evidence(
                key=item["key"],
                deleted_by="other",
            )
            self.assertEqual(deleted["key"], item["key"])
            self.assertEqual(deleted["active"], 0)
            self.assertEqual(
                database.list_missing_evidence_catalog(include_inactive=False),
                [],
            )
            with self.assertRaisesRegex(ValueError, "已经存在"):
                database.create_missing_evidence(
                    label="绕行空间与时序缺失",
                    hint="另一个说明",
                    created_by="other",
                )

    def test_annotation_requires_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            with self.assertRaisesRegex(ValueError, "复核人不能为空"):
                database.create_annotation(
                    issue_id="cn12345",
                    label="误触发",
                    review_status="reviewed",
                    tags=[],
                    missing_evidence=[],
                    note="missing reviewer",
                    author=" ",
                )

    def test_annotation_persists_issue_exclusion_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            annotation = database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="needs_gt_review",
                tags=["queue"],
                missing_evidence=[],
                note="not a model-scope case",
                author="jasper",
                is_excluded=True,
            )
            self.assertTrue(annotation["is_excluded"])
            self.assertTrue(database.get_case("cn12345")["annotations"][0]["is_excluded"])

    def test_annotation_delete_reconnects_history_and_removes_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            first = database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="first",
                author="jasper",
            )
            second = database.create_annotation(
                issue_id="cn12345",
                label="正确触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="second",
                author="jasper",
                attachments=[
                    {
                        "id": "attachment-1",
                        "original_name": "review.png",
                        "stored_name": "stored-review.png",
                        "media_type": "image/png",
                        "size_bytes": 12,
                        "width": 2,
                        "height": 2,
                        "sha256": "a" * 64,
                    }
                ],
            )
            third = database.create_annotation(
                issue_id="cn12345",
                label="无需协助",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="third",
                author="jasper",
            )
            revision = database.change_revision()

            deleted = database.delete_annotation(
                issue_id="cn12345",
                annotation_id=second["id"],
            )

            self.assertEqual(deleted["id"], second["id"])
            self.assertEqual(deleted["attachments"][0]["id"], "attachment-1")
            case = database.get_case("cn12345")
            self.assertEqual(
                [item["id"] for item in case["annotations"]],
                [third["id"], first["id"]],
            )
            self.assertEqual(case["annotations"][0]["supersedes_id"], first["id"])
            self.assertIsNone(database.get_review_attachment("attachment-1"))
            self.assertGreater(database.change_revision(), revision)
            self.assertIsNone(
                database.delete_annotation(
                    issue_id="cn12345",
                    annotation_id=second["id"],
                )
            )

    def test_queued_batch_survives_restart_and_remains_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triage.sqlite3"
            database = Database(path)
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345"}, {"issue_id": "cn12346"}],
                source="test",
                replace_gt=False,
            )
            first = self._create_job(database)
            second = self._create_job(database, "cn12346")
            with database.connect() as conn:
                conn.execute(
                    "UPDATE batch_prediction_jobs SET created_at = ? WHERE id IN (?, ?)",
                    ("2026-08-02T00:00:00+00:00", first["id"], second["id"]),
                )
            restarted = Database(path)
            restarted.init()
            restored = restarted.get_batch_prediction_job(first["id"])
            self.assertEqual(restored["status"], "queued")
            self.assertEqual(
                restarted.next_queued_batch_prediction_job()["id"],
                first["id"],
            )

    def test_job_keeps_exact_prompt_and_input_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345"}],
                source="test",
                replace_gt=False,
            )
            prompt = "三分类：误触发、正确触发、无需协助。" * 4
            job = database.create_batch_prediction_job(
                name="prompt experiment",
                issue_ids=["cn12345"],
                requested_by="jasper",
                requested_model_id="auto",
                resolved_model_id="Qwen3.5/base",
                model_source="ra_model_gateway",
                catalog_sha256="a" * 64,
                model_validation_status="validated",
                prompt_version="stuck_triage_auto_opt_api",
                prompt_template=prompt,
                prompt_template_sha256="b" * 64,
                prompt_mode="custom",
                input_profile="camera_ra_event",
                input_config={
                    "profile_id": "camera_ra_event",
                    "frame_offsets_ms": [-1000, 0, 1000],
                    "use_ra_event": True,
                    "use_ra_options": False,
                },
            )
            self.assertEqual(job["prompt_template"], prompt)
            self.assertEqual(job["input_config"]["frame_offsets_ms"], [-1000, 0, 1000])
            filtered = database.list_batch_prediction_jobs(
                model_id="auto",
                prompt_version="stuck_triage_auto_opt_api",
                prompt_mode="custom",
                prompt_sha256="b" * 64,
                input_profile="camera_ra_event",
            )
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(
                {item["id"] for item in filtered["facets"]["models"]},
                {"auto", "Qwen3.5/base"},
            )
            self.assertEqual(
                filtered["facets"]["prompts"],
                [
                    {
                        "version": "stuck_triage_auto_opt_api",
                        "mode": "custom",
                        "sha256": "b" * 64,
                        "job_count": 1,
                    }
                ],
            )
            self.assertEqual(
                filtered["facets"]["input_profiles"],
                [{"id": "camera_ra_event", "job_count": 1}],
            )

    def test_model_run_delete_cascades_predictions_but_keeps_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            run, duplicate = database.import_model_run(
                name="delete me",
                source_name="results.csv",
                source_sha256="c" * 64,
                metadata={},
                rows=[
                    {
                        "issue_id": "cn12345",
                        "model_label": "正确触发",
                        "model_reason": "test",
                        "raw": {"issue_id": "cn12345", "model_label": "正确触发"},
                    }
                ],
            )
            self.assertFalse(duplicate)
            self.assertIsNotNone(database.get_case("cn12345"))
            deleted = database.delete_model_run(run["id"])
            self.assertEqual(deleted["id"], run["id"])
            self.assertIsNone(database.get_model_run(run["id"]))
            case = database.get_case("cn12345")
            self.assertIsNotNone(case)
            self.assertEqual(case["predictions"], [])
