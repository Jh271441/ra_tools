"""Tests for CLI selection helpers."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_release_pipeline.cli import (
    _command_apply_handoff,
    _command_ifx_convert,
    _format_pick_result,
    _format_record_result,
    _select_candidate,
    _select_manual_epoch_candidate,
    _validate_upload_binding,
)
from model_release_pipeline.config import default_config
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.state_store import StateStore


class CliSelectionTest(unittest.TestCase):
    def test_selects_recommended_epoch_for_requested_task(self) -> None:
        pick_result = {
            "per_task": {
                "stuck_detect": {
                    "recommended_epoch": 0,
                    "all_candidates": [{"epoch": 0, "task": "stuck_detect"}],
                },
                "stuck_detect_neg_no_assist": {
                    "recommended_epoch": 41,
                    "all_candidates": [
                        {"epoch": 41, "task": "stuck_detect_neg_no_assist"}
                    ],
                },
            },
            "recommended_epoch": None,
            "all_candidates": [],
        }

        selected = _select_candidate(
            pick_result,
            "/tmp/exp",
            epoch=None,
            task="stuck_detect_neg_no_assist",
        )

        self.assertEqual(selected["epoch"], 41)
        self.assertEqual(selected["task"], "stuck_detect_neg_no_assist")

    def test_requires_task_or_epoch_for_multi_task(self) -> None:
        pick_result = {
            "per_task": {
                "task_a": {"recommended_epoch": 0, "all_candidates": []},
                "task_b": {"recommended_epoch": 1, "all_candidates": []},
            },
            "recommended_epoch": None,
            "all_candidates": [],
        }

        with self.assertRaisesRegex(RuntimeError, "--task or --epoch"):
            _select_candidate(pick_result, "/tmp/exp", epoch=None)

    def test_formats_pick_result_without_full_json_dump(self) -> None:
        pick_result = {
            "policy": "precision_first",
            "top_n": 1,
            "tasks": ["stuck_detect"],
            "recommended_epoch": 3,
            "notes": [],
            "per_task": {
                "stuck_detect": {
                    "recommended_epoch": 3,
                    "candidates": [
                        {
                            "epoch": 3,
                            "precision": 0.8,
                            "recall": 0.7,
                            "pr_auc": 0.9,
                            "roc_auc": 0.95,
                        }
                    ],
                    "all_candidates": [
                        {
                            "epoch": 3,
                            "precision": 0.8,
                            "recall": 0.7,
                            "pr_auc": 0.9,
                            "roc_auc": 0.95,
                        }
                    ],
                }
            },
        }

        text = _format_pick_result(pick_result)

        self.assertIn("===== stuck_detect: Top 1 by roc_auc =====", text)
        self.assertIn("Recommended epoch: 003", text)
        self.assertNotIn("checkpoint_path", text)

    def test_select_manual_epoch_candidate_uses_checkpoint_directly(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            checkpoint = root / "checkpoints" / "version_0" / "epoch=007.pth"
            checkpoint.write_text("", encoding="utf-8")
            experiment = ExperimentInspector().inspect(root)

            selected = _select_manual_epoch_candidate(experiment, str(root), 7)

            self.assertEqual(selected["epoch"], 7)
            self.assertEqual(selected["sources"], ["manual_epoch"])
            self.assertEqual(selected["checkpoint_path"], checkpoint)

    def test_formats_export_record_as_human_summary(self) -> None:
        record = {
            "release_id": "run123",
            "stage": "export_failed",
            "status": "failed",
            "experiment": {"name": "exp_a"},
            "selection": {
                "selected_epoch": 7,
                "selection_source": "manual_epoch",
            },
            "export": {
                "local_onnx_file": "/tmp/vectorized_scenario_remote_assist_model.onnx",
                "remote_onnx_file": "/nfs/exp/export/epoch=007/model.onnx",
                "export": {
                    "returncode": 1,
                    "stderr": "line1\nModuleNotFoundError: No module named 'utils'",
                },
                "scp": {
                    "returncode": None,
                    "stderr": "Skipped because remote export failed.",
                },
            },
        }

        text = _format_record_result(record)

        self.assertIn("release_id: run123", text)
        self.assertIn("selected epoch: 007", text)
        self.assertIn("remote export: FAILED(1)", text)
        self.assertIn("scp onnx: SKIPPED", text)
        self.assertIn("ModuleNotFoundError", text)
        self.assertNotIn('"checkpoints"', text)

    def test_upload_binding_rejects_version_change_without_replace(self) -> None:
        record = {
            "ifx": {
                "onnx": {
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 65,
                }
            }
        }
        args = argparse.Namespace(version=66, replace_upload=False)

        with self.assertRaisesRegex(RuntimeError, "version 65; requested version 66"):
            _validate_upload_binding(args, record)

    def test_upload_binding_allows_explicit_replace(self) -> None:
        record = {"ifx": {"onnx": {"name": "model.onnx", "version": 65}}}
        args = argparse.Namespace(version=66, replace_upload=True)

        _validate_upload_binding(args, record)

    def test_apply_handoff_without_branch_applies_all_configured_branches(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            config.ifx.truck_docker_container = "voyager-dev"
            config.voyager.branches = config.voyager.branches[:2]
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["experiment"] = {"name": "exp"}
            record["selection"] = {"selected_epoch": 7}
            record["ifx"] = {
                "ifx_mapping": {
                    "onnx": {"name": "model.onnx", "version": 65},
                    "fp32_x86": {"name": "model.ifxmodel", "version": 1},
                }
            }
            store.save(record)
            calls = []

            class FakeService:
                def __init__(self, _config):
                    pass

                def apply_to_docker(self, **kwargs):
                    calls.append(kwargs["branch"])
                    return {
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                        "branch": kwargs["branch"],
                        "checkout_branch": kwargs["branch"],
                        "dcl_commands": [f"dcl diff {kwargs['branch']}"],
                    }

            import model_release_pipeline.cli as cli_module

            original_service = cli_module.VoyagerHandoffService
            original_confirm = cli_module._confirm
            try:
                cli_module.VoyagerHandoffService = FakeService
                cli_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    branch=None,
                    yes=True,
                    json=True,
                    desc="",
                    docker="",
                    dry_run=False,
                    no_commit=False,
                    allow_dirty=False,
                    allow_append=False,
                )

                updated = _command_apply_handoff(args, config, store, record)
            finally:
                cli_module.VoyagerHandoffService = original_service
                cli_module._confirm = original_confirm

            self.assertEqual(calls, ["master", "gen4_release_20260403"])
            self.assertEqual(updated["apply_handoff"]["returncode"], 0)
            self.assertEqual(len(updated["apply_handoff"]["results"]), 2)

    def test_ifx_convert_dry_run_does_not_persist_preview(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["ifx"] = {
                "onnx": {
                    "module": "planner.model-files",
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 66,
                },
                "precision_test_arg": (
                    "ifx-precision-test ifx_fp32_after_scaling_pos1e1_5.zip -v 1"
                ),
            }
            store.save(record)

            class FakePipeline:
                def __init__(self, _config):
                    pass

                def convert(self, **_kwargs):
                    return {
                        "jenkins": {
                            "params": {
                                "truck_py_arguments_of_onnx": (
                                    "planner.model-files "
                                    "vectorized_scenario_remote_assist_model.onnx -v 66"
                                )
                            }
                        },
                        "ifx_mapping": {"onnx": {"version": 66}},
                        "label": None,
                    }

            import model_release_pipeline.cli as cli_module

            original_pipeline = cli_module.IfxPipeline
            try:
                cli_module.IfxPipeline = FakePipeline
                args = argparse.Namespace(
                    run_id=record["release_id"],
                    yes=True,
                    dry_run=True,
                    json=True,
                )

                preview = _command_ifx_convert(args, config, store)
            finally:
                cli_module.IfxPipeline = original_pipeline

            persisted = store.load(record["release_id"])
            self.assertEqual(preview["stage"], "ifx_convert_dry_run")
            self.assertEqual(persisted["stage"], "created")
            self.assertNotIn("ifx_mapping", persisted["ifx"])


if __name__ == "__main__":
    unittest.main()
