"""Tests for model selection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.model_picker import (
    ModelPicker,
    _metric_from_tag,
    _task_from_tag,
)


class ModelPickerTest(unittest.TestCase):
    def test_tensorboard_task_tag_prefers_longest_task_match(self) -> None:
        self.assertEqual(
            _task_from_tag(
                "val/stuck_detect_neg_no_assist/precision",
                ["stuck_detect", "stuck_detect_neg_no_assist"],
            ),
            "stuck_detect_neg_no_assist",
        )

    def test_tensorboard_fallback_uses_val_loss_not_train_loss(self) -> None:
        self.assertIsNone(_metric_from_tag("train/stuck_detect/task_all_loss"))
        self.assertEqual(_metric_from_tag("val/stuck_detect/task_all_loss"), "loss")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(10):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "\n".join(
                    [
                        "training:",
                        "  - activated_tasks:",
                        "    - stuck_detect",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            experiment.tensorboard_scalars = {
                "stuck_detect": {
                    1: {"loss": 0.10, "precision": 0.50},
                    2: {"loss": 0.20, "precision": 0.90},
                }
            }

            result = ModelPicker().pick(experiment, policy="precision_first", top_n=1)

            self.assertEqual(result["recommended_epoch"], 1)
            self.assertEqual(
                result["per_task"]["stuck_detect"]["tensorboard_loss_window"][
                    "min_loss_epoch"
                ],
                1,
            )

    def test_tensorboard_fallback_uses_loss_tolerance_band(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(10):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "\n".join(
                    [
                        "training:",
                        "  - activated_tasks:",
                        "    - stuck_detect",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            experiment.tensorboard_scalars = {
                "stuck_detect": {
                    1: {"loss": 1.00, "precision": 0.50},
                    2: {"loss": 1.03, "precision": 0.80},
                    8: {"loss": 1.20, "precision": 0.99},
                }
            }

            result = ModelPicker().pick(
                experiment,
                policy="precision_first",
                top_n=1,
                loss_tolerance_pct=0.05,
            )
            fallback = result["per_task"]["stuck_detect"]["tensorboard_loss_window"]

            self.assertEqual(result["recommended_epoch"], 2)
            self.assertEqual(fallback["candidate_count"], 2)
            self.assertAlmostEqual(fallback["max_allowed_loss"], 1.05)

    def test_pick_from_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(3):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "trained_model_relative_path: checkpoints/version_0/epoch=000.pth\n",
                encoding="utf-8",
            )
            (root / "log" / "version_0" / "train_scenario_dnn.log").write_text(
                "\n".join(
                    [
                        "epoch=000 val_loss=0.3 val_precision=0.80 val_recall=0.70",
                        "epoch=001 val_loss=0.2 val_precision=0.92 val_recall=0.83",
                        "epoch=002 val_loss=0.4 val_precision=0.85 val_recall=0.91",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            result = ModelPicker().pick(experiment, policy="precision_first", top_n=2)
            self.assertEqual(result["recommended_epoch"], 1)
            self.assertEqual(result["candidates"][0]["epoch"], 1)

    def test_pick_from_validation_table_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(2):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "trained_model_relative_path: checkpoints/version_0/epoch=000.pth\n",
                encoding="utf-8",
            )
            (root / "log" / "version_0" / "train_scenario_dnn.log").write_text(
                "\n".join(
                    [
                        "Task stuck_detect: Validation Metrics (Epoch 0, Global_step 164):",
                        "|  accuracy  |  f1_score  |  pr_auc  |  precision  |  recall  |",
                        "|  0.91      |  0.62      |  0.65    |   0.58      | 0.68     |",
                        "Task stuck_detect: Validation Metrics (Epoch 1, Global_step 328):",
                        "|  accuracy  |  f1_score  |  pr_auc  |  precision  |  recall  |",
                        "|  0.93      |  0.72      |  0.75    |   0.88      | 0.71     |",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            result = ModelPicker().pick(experiment, policy="precision_first", top_n=2)
            self.assertEqual(result["recommended_epoch"], 1)
            self.assertEqual(result["candidates"][0]["precision"], 0.88)

    def test_pick_groups_validation_table_by_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(2):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "\n".join(
                    [
                        "training:",
                        "  - activated_tasks:",
                        "    - stuck_detect",
                        "    - stuck_detect_neg_no_assist",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "log" / "version_0" / "train_scenario_dnn.log").write_text(
                "\n".join(
                    [
                        "Task stuck_detect: Validation Metrics (Epoch 0, Global_step 1):",
                        "| precision | recall |",
                        "| 0.60 | 0.80 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 0, Global_step 1):",
                        "| precision | recall |",
                        "| 0.40 | 0.70 |",
                        "Task stuck_detect: Validation Metrics (Epoch 1, Global_step 2):",
                        "| precision | recall |",
                        "| 0.50 | 0.90 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 1, Global_step 2):",
                        "| precision | recall |",
                        "| 0.90 | 0.30 |",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            result = ModelPicker().pick(experiment, policy="precision_first", top_n=1)
            self.assertEqual(
                result["tasks"], ["stuck_detect", "stuck_detect_neg_no_assist"]
            )
            self.assertNotIn("default", result["per_task"])
            self.assertIsNone(result["recommended_epoch"])
            self.assertEqual(
                result["per_task"]["stuck_detect"]["recommended_epoch"], 0
            )
            self.assertEqual(
                result["per_task"]["stuck_detect_neg_no_assist"]["recommended_epoch"], 1
            )

    def test_pick_builds_primary_weighted_combined_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(3):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "\n".join(
                    [
                        "training:",
                        "  - activated_tasks:",
                        "    - stuck_detect",
                        "    - stuck_detect_neg_no_assist",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "log" / "version_0" / "train_scenario_dnn.log").write_text(
                "\n".join(
                    [
                        "Task stuck_detect: Validation Metrics (Epoch 0, Global_step 1):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.90 | 0.70 | 0.92 | 0.85 | 0.86 | 0.93 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 0, Global_step 1):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.92 | 0.50 | 0.60 | 0.35 | 0.55 | 0.61 |",
                        "Task stuck_detect: Validation Metrics (Epoch 1, Global_step 2):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.91 | 0.72 | 0.90 | 0.84 | 0.84 | 0.91 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 1, Global_step 2):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.95 | 0.62 | 0.95 | 0.90 | 0.58 | 0.96 |",
                        "Task stuck_detect: Validation Metrics (Epoch 2, Global_step 3):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.89 | 0.68 | 0.88 | 0.83 | 0.83 | 0.90 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 2, Global_step 3):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.94 | 0.60 | 0.93 | 0.88 | 0.57 | 0.94 |",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            result = ModelPicker().pick(experiment, policy="precision_first", top_n=2)
            self.assertEqual(result["recommended_epoch"], 0)
            self.assertEqual(result["combined_recommendations"][0]["epoch"], 0)
            self.assertEqual(
                result["combined_recommendations"][0]["primary_task"],
                "stuck_detect",
            )

    def test_incomplete_log_prefers_primary_tensorboard_loss_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            for epoch in range(50):
                checkpoint = root / "checkpoints" / "version_0" / f"epoch={epoch:03d}.pth"
                checkpoint.write_text("", encoding="utf-8")
            (root / "log" / "version_0" / "hparams.yaml").write_text(
                "\n".join(
                    [
                        "training:",
                        "  - activated_tasks:",
                        "    - stuck_detect",
                        "    - stuck_detect_neg_no_assist",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "log" / "version_0" / "train_scenario_dnn.log").write_text(
                "\n".join(
                    [
                        "Task stuck_detect: Validation Metrics (Epoch 0, Global_step 1):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.90 | 0.70 | 0.92 | 0.95 | 0.86 | 0.93 |",
                        "Task stuck_detect_neg_no_assist: Validation Metrics (Epoch 0, Global_step 1):",
                        "| accuracy | f1_score | pr_auc | precision | recall | roc_auc |",
                        "| 0.92 | 0.50 | 0.60 | 0.35 | 0.55 | 0.61 |",
                    ]
                ),
                encoding="utf-8",
            )
            experiment = ExperimentInspector().inspect(root)
            experiment.tensorboard_scalars = {
                "stuck_detect": {
                    8: {"loss": 0.105, "precision": 0.60, "recall": 0.8, "pr_auc": 0.6, "roc_auc": 0.7},
                    10: {"loss": 0.10, "precision": 0.61, "recall": 0.8, "pr_auc": 0.6, "roc_auc": 0.7},
                    11: {"loss": 0.104, "precision": 0.90, "recall": 0.8, "pr_auc": 0.6, "roc_auc": 0.7},
                    20: {"loss": 0.30, "precision": 0.99, "recall": 0.8, "pr_auc": 0.6, "roc_auc": 0.7},
                },
                "stuck_detect_neg_no_assist": {
                    10: {"loss": 0.10, "precision": 0.70, "recall": 0.6, "pr_auc": 0.6, "roc_auc": 0.7},
                    11: {"loss": 0.11, "precision": 0.75, "recall": 0.6, "pr_auc": 0.6, "roc_auc": 0.7},
                },
            }

            result = ModelPicker().pick(experiment, policy="precision_first", top_n=2)

            self.assertEqual(result["recommended_epoch"], 11)
            self.assertIn("tensorboard", result["candidates"][0]["sources"])
            self.assertTrue(
                any("Log metrics are incomplete" in note for note in result["notes"])
            )


if __name__ == "__main__":
    unittest.main()
