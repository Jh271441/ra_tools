"""Tests for the read-only release web console helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_release_pipeline.config import default_config
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web_app import JobManager, ReleaseWebApp, _timeline


class WebAppTest(unittest.TestCase):
    def test_lists_runs_with_summary_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create("/nfs/exp_a", "demo")
            record["experiment"] = {"name": "exp_a"}
            record["selection"] = {
                "selected_epoch": 7,
                "selection_source": "picker",
            }
            record["ifx"] = {
                "ifx_mapping": {
                    "onnx": {"name": "model.onnx", "version": 67},
                    "fp32_x86": {"name": "model_x86.ifxmodel", "version": 78},
                }
            }
            store.save(record)

            payload = ReleaseWebApp(config).list_runs()

            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(payload["runs"][0]["experiment_name"], "exp_a")
            self.assertEqual(payload["runs"][0]["selected_epoch"], 7)
            self.assertEqual(payload["runs"][0]["onnx_version"], 67)
            self.assertEqual(payload["runs"][0]["ifx_platforms"], 1)

    def test_run_detail_includes_timeline_logs_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create("/nfs/exp_b", "demo")
            record["experiment"] = {"name": "exp_b"}
            record["selection"] = {
                "selected_epoch": 9,
                "selection_source": "manual_epoch",
            }
            record["offboard"] = {
                "returncode": 0,
                "stdout": "Task stuck_detect: Validation Metrics (Epoch 9, Global_step 1):\n| precision | recall |\n| 0.7 | 0.6 |",
                "stderr": "",
            }
            store.save(record)

            payload = ReleaseWebApp(config).get_run(record["release_id"])

            self.assertIn("timeline", payload)
            self.assertIn("offboard_stdout", payload["logs"])
            self.assertIn("--run-id", payload["commands"]["offboard"])
            self.assertIn("actions", payload)
            self.assertTrue(payload["offboard_metrics"])

    def test_timeline_marks_failed_export(self) -> None:
        record = {
            "stage": "export_failed",
            "status": "failed",
            "experiment": {"name": "exp"},
            "selection": {"selected_epoch": 1},
            "export": {
                "export": {"returncode": 1},
                "scp": {"returncode": None, "stderr": "Skipped because remote export failed."},
            },
        }

        statuses = {step["key"]: step["status"] for step in _timeline(record)}

        self.assertEqual(statuses["export"], "failed")

    def test_job_command_uses_cli_and_dry_run(self) -> None:
        manager = JobManager(config_path="/tmp/release.yaml")

        command = manager.build_command("run123", "offboard", dry_run=True)

        self.assertIn("-m", command)
        self.assertIn("model_release_pipeline.cli", command)
        self.assertIn("--config", command)
        self.assertIn("/tmp/release.yaml", command)
        self.assertIn("offboard", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--remote", command)

    def test_export_job_command_uses_form_payload(self) -> None:
        manager = JobManager()

        command = manager.build_command(
            "unused",
            "export",
            dry_run=True,
            payload={
                "experiment": "/nfs/exp",
                "epoch": "007",
                "remote": "luban_2_card",
                "desc": "demo",
            },
        )

        self.assertIn("export", command)
        self.assertIn("--experiment", command)
        self.assertIn("/nfs/exp", command)
        self.assertIn("--epoch", command)
        self.assertIn("7", command)
        self.assertIn("--remote", command)
        self.assertNotIn("--run-id", command)

    def test_real_action_requires_release_id_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create("/nfs/exp_c", "demo")
            store.save(record)
            app = ReleaseWebApp(config)

            with self.assertRaises(PermissionError):
                app.start_action(
                    record["release_id"],
                    "offboard",
                    {"dry_run": False, "confirm_text": "wrong"},
                )


if __name__ == "__main__":
    unittest.main()
