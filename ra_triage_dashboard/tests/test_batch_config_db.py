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
