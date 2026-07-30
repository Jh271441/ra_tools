from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


class BatchConfigDatabaseTest(unittest.TestCase):
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
