"""Tests for CLI selection helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_release_pipeline.cli import (
    _format_pick_result,
    _format_record_result,
    _select_candidate,
    _select_manual_epoch_candidate,
)
from model_release_pipeline.services.experiment import ExperimentInspector


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


if __name__ == "__main__":
    unittest.main()
