"""Tests for the read-only release web console helpers."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from model_release_pipeline.config import default_config, IfxConfig
from model_release_pipeline.onboard.versioned_onnx import copy_versioned_onnx_to_utils
from model_release_pipeline.services.ifx_pipeline import IfxPipeline, IfxPipelineError
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web_app import (
    JobManager,
    ReleaseWebApp,
    _logs,
    _record_summary,
    _timeline,
)
from model_release_pipeline.web.actions import build_cli_command
from model_release_pipeline.web.summary import step_status


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

    def test_upload_job_command_uses_form_payload(self) -> None:
        manager = JobManager()

        command = manager.build_command(
            "run123",
            "upload",
            dry_run=True,
            payload={
                "desc": "demo upload",
                "version": "67",
                "replace_upload": True,
            },
        )

        self.assertIn("upload", command)
        self.assertIn("--run-id", command)
        self.assertIn("run123", command)
        self.assertIn("--desc", command)
        self.assertIn("demo upload", command)
        self.assertIn("--onnx-version", command)
        self.assertIn("67", command)
        self.assertIn("--replace-upload", command)

    def test_copy_versioned_onnx_to_utils_uses_run_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = default_config()
            config.runs_dir = root / "runs"
            store = StateStore(config.runs_dir)
            record = store.create("/nfs/exp", "demo")
            record["ifx"] = {
                "onnx": {
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 67,
                }
            }
            source = store.run_dir(record["release_id"]) / "artifacts" / "vectorized_scenario_remote_assist_model.onnx"
            source.write_bytes(b"onnx")
            record["export"] = {"local_onnx_file": str(source)}
            store.save(record)

            result = copy_versioned_onnx_to_utils(
                config.runs_dir,
                record,
                target_dir=root / "utils" / "onnx",
            )

            expected_name = "vectorized_vectorized_scenario_remote_assist_model_v67.onnx"
            self.assertTrue((config.runs_dir / record["release_id"] / "artifacts" / expected_name).exists())
            self.assertEqual(Path(result["target"]).name, expected_name)
            self.assertEqual(Path(result["target"]).read_bytes(), b"onnx")

    def test_dcl_action_is_exposed_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create("/nfs/exp_d", "demo")
            record["apply_handoff"] = {"returncode": 0}
            record["dcl"] = {
                "returncode": 0,
                "stdout": "DCL OK",
                "stderr": "",
            }
            record["stage"] = "dcl_complete"
            store.save(record)

            payload = ReleaseWebApp(config).get_run(record["release_id"])

            self.assertTrue(any(action["key"] == "dcl" for action in payload["actions"]))
            self.assertEqual(
                {step["key"]: step["status"] for step in payload["timeline"]}["dcl"],
                "done",
            )
            self.assertIn("DCL OK", "\n".join(payload["logs"]["dcl_stdout"]))

    def test_logs_include_upload_channels(self) -> None:
        record = {
            "stage": "ifx_uploaded",
            "ifx": {
                "onnx": {
                    "module": "planner.model-files",
                    "name": "model.onnx",
                    "version": 67,
                    "local_path": "/tmp/model.onnx",
                },
                "truck_runner": {"configured": "auto", "selected": "docker"},
                "upload_description": "demo",
                "precision_test_arg": "ifx-test test.zip -v 1",
            },
        }

        logs = _logs(record)

        self.assertIn("upload_stdout", logs)
        self.assertIn("upload_stderr", logs)
        self.assertTrue(any("model.onnx" in line for line in logs["upload_stdout"]))

    def test_logs_include_ifx_channels(self) -> None:
        record = {
            "stage": "ifx_complete",
            "ifx": {
                "onnx": {
                    "module": "planner.model-files",
                    "name": "model.onnx",
                    "version": 68,
                },
                "precision_test_arg": "ifx-test test.zip -v 1",
                "ifx_mapping": {
                    "onnx": {"name": "model.onnx", "version": 68},
                    "fp32_x86": {"name": "model_bs0_fp32_x86.ifxmodel", "version": 79},
                    "fp16_thor": {"name": "model_bs0_fp16_thor.ifxmodel", "version": 44},
                },
                "jenkins": {
                    "queue_url": "http://jenkins/queue/item/1/",
                    "build_url": "http://jenkins/job/demo/1/",
                    "build_number": 1,
                    "result": "SUCCESS",
                    "console_tail": ["\x1b[32mFinished: SUCCESS\x1b[0m"],
                },
            },
        }

        logs = _logs(record)

        self.assertIn("ifx_stdout", logs)
        self.assertIn("ifx_stderr", logs)
        self.assertTrue(any("model.onnx" in line for line in logs["ifx_stdout"]))
        self.assertTrue(any("fp32_x86" in line for line in logs["ifx_stdout"]))
        self.assertTrue(any("Finished: SUCCESS" in line for line in logs["ifx_stdout"]))

    def test_ifx_poll_action_accepts_manual_build_url(self) -> None:
        command = build_cli_command(
            "run1",
            "ifx-poll",
            payload={"build_url": "http://jenkins/job/demo/11669/"},
        )

        self.assertIn("--build-url", command)
        self.assertIn("http://jenkins/job/demo/11669/", command)

    def test_later_failure_does_not_mark_successful_export_failed(self) -> None:
        record = {
            "stage": "exported",
            "status": "failed",
            "experiment": {"name": "exp"},
            "selection": {"selected_epoch": 4},
            "export": {
                "export": {"returncode": 0},
                "scp": {"returncode": 0},
            },
            "errors": [{"message": "No uploaded ONNX found in release record."}],
        }
        statuses = {step["key"]: step["status"] for step in _timeline(record)}

        self.assertEqual(statuses["export"], "done")
        self.assertEqual(statuses["ifx"], "pending")

    def test_upload_failure_does_not_mark_ifx_failed(self) -> None:
        record = {
            "stage": "ifx_upload_dry_run",
            "status": "failed",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 0},
                "truck_runner": {"selected": "dry_run"},
            },
            "errors": [{"message": "upload failed"}],
        }
        statuses = {step["key"]: step["status"] for step in _timeline(record)}

        self.assertEqual(statuses["upload"], "dry_run")
        self.assertEqual(statuses["ifx"], "pending")

    def test_later_dry_run_does_not_downgrade_completed_export(self) -> None:
        record = {
            "stage": "apply_handoff_dry_run",
            "status": "dry_run",
            "experiment": {"name": "exp"},
            "selection": {"selected_epoch": 4},
            "export": {
                "export": {"returncode": 0},
                "scp": {"returncode": 0},
            },
            "apply_handoff": {"returncode": 0, "dcl_commands": ["dcl diff -n -u 1"]},
        }
        statuses = {step["key"]: step["status"] for step in _timeline(record)}

        self.assertEqual(statuses["export"], "done")
        self.assertEqual(statuses["handoff"], "dry_run")
        self.assertEqual(statuses["dcl"], "pending")

    def test_upload_dry_run_log_does_not_replace_actual_onnx_summary(self) -> None:
        record = {
            "stage": "ifx_upload_dry_run",
            "status": "dry_run",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 68},
                "dry_run_upload": {
                    "onnx": {"name": "model.onnx", "version": 99},
                    "truck_runner": {"selected": "dry_run"},
                },
            },
        }

        logs = _logs(record)
        summary = _record_summary(record)

        self.assertTrue(any("-v 99" in line for line in logs["upload_stdout"]))
        self.assertEqual(summary["onnx_version"], 68)

    def test_summary_ignores_legacy_dry_run_onnx_version(self) -> None:
        record = {
            "stage": "ifx_upload_dry_run",
            "status": "dry_run",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 0},
                "truck_runner": {"selected": "dry_run"},
                "ifx_mapping": {
                    "onnx": {"name": "model.onnx", "version": 68},
                },
            },
        }

        summary = _record_summary(record)

        self.assertEqual(summary["onnx_version"], 68)

    def test_draft_export_action_does_not_require_existing_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            app = ReleaseWebApp(config)
            captured = {}

            def fake_start(**kwargs):
                captured.update(kwargs)
                return {"job_id": "job1", "status": "running"}

            app.jobs.start = fake_start  # type: ignore[method-assign]

            result = app.start_action(
                "__draft__",
                "export",
                {
                    "dry_run": True,
                    "experiment": "/nfs/exp",
                    "epoch": "004",
                    "remote": "luban_2_card",
                },
            )

            self.assertEqual(result["job_id"], "job1")
            self.assertEqual(captured["release_id"], "__draft__")
            self.assertEqual(captured["action"], "export")
            self.assertTrue(captured["dry_run"])

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

    def test_pick_status_done_skipped_pending(self) -> None:
        self.assertEqual(step_status({}, "pick"), "pending")
        self.assertEqual(
            step_status({"selection": {"selected_epoch": 7}}, "pick"), "skipped"
        )
        self.assertEqual(
            step_status({"pick": {"recommended_epoch": 7}, "selection": {"selected_epoch": 7}}, "pick"),
            "done",
        )

    def test_offboard_is_ready_after_pick_and_pending_before(self) -> None:
        self.assertEqual(step_status({}, "offboard"), "pending")
        self.assertEqual(
            step_status({"selection": {"selected_epoch": 7}}, "offboard"), "ready"
        )
        self.assertEqual(
            step_status(
                {"selection": {"selected_epoch": 7}, "offboard": {"returncode": 0}},
                "offboard",
            ),
            "done",
        )

    def test_ifx_convert_failed_timeline_shows_failed(self) -> None:
        record = {
            "stage": "ifx_convert_failed",
            "status": "failed",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 64},
                "jenkins": {
                    "build_url": "http://jenkins/job/demo/1/",
                    "result": "SUCCESS",
                    "last_poll_status": "SUCCESS",
                },
            },
        }

        self.assertEqual(step_status(record, "ifx"), "failed")

    def test_ifx_polling_timeline_shows_running(self) -> None:
        record = {
            "stage": "ifx_polling",
            "status": "running",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 64},
                "jenkins": {"build_url": "http://jenkins/job/demo/1/"},
            },
        }

        self.assertEqual(step_status(record, "ifx"), "running")

    def test_ifx_poll_failed_stage_shows_failed(self) -> None:
        record = {
            "stage": "ifx_poll_failed",
            "status": "failed",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 64},
                "jenkins": {
                    "build_url": "http://jenkins/job/demo/1/",
                    "last_poll_status": "SUCCESS",
                },
            },
        }

        self.assertEqual(step_status(record, "ifx"), "failed")

    def test_dry_run_ifx_convert_does_not_save_to_store(self) -> None:
        from model_release_pipeline.onboard.upload import run_ifx_convert

        record = {
            "release_id": "test_dry_run",
            "stage": "ifx_uploaded",
            "status": "running",
            "ifx": {
                "onnx": {
                    "module": "planner.model-files",
                    "name": "model.onnx",
                    "version": 64,
                },
                "precision_test_arg": "ifx-test test.zip -v 1",
            },
        }
        args = argparse.Namespace(
            run_id="test_dry_run",
            dry_run=True,
            yes=True,
            json=False,
        )
        store = MagicMock()
        config = default_config()

        run_ifx_convert(
            args,
            config,
            store,
            record,
            progress=lambda *a, **kw: None,
            confirm=lambda *a, **kw: True,
            ifx_pipeline_cls=IfxPipeline,
            ifx_pipeline_error_cls=IfxPipelineError,
        )

        store.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
