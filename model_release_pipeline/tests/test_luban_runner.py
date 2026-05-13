"""Tests for Luban command generation."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from model_release_pipeline.config import LubanConfig, default_config
from model_release_pipeline.models import ExperimentInfo
from model_release_pipeline.services.luban_runner import LubanRunner


class LubanRunnerTest(unittest.TestCase):
    def test_export_command_uses_python_c_and_repo_pythonpath(self) -> None:
        experiment = ExperimentInfo(
            name="exp",
            experiment_path=Path("/nfs/exp"),
            version_name="version_0",
            checkpoints_dir=Path("/nfs/exp/checkpoints/version_0"),
            log_dir=Path("/nfs/exp/log/version_0"),
            export_dir=None,
            log_file=Path("/nfs/exp/log/version_0/train_scenario_dnn.log"),
            hparams_file=Path("/nfs/exp/log/version_0/hparams.yaml"),
            tensorboard_files=[],
            checkpoints=[Path("/nfs/exp/checkpoints/version_0/epoch=007.pth")],
            exported_epochs=[],
            remote_host="luban_2_card",
        )
        config = LubanConfig(
            train_repo="/nfs/stuck_assist_model",
            export_script="scenario_dnn/export/export_scenario_dnn.py",
            python_bin="/home/luban/miniconda3/bin/conda run -n scen_dnn python",
            remote_python_bin="/home/luban/miniconda3/bin/conda run -n scen_dnn python",
        )

        result = LubanRunner(config).export_onnx(
            experiment=experiment,
            checkpoint_path=Path("/nfs/exp/checkpoints/version_0/epoch=007.pth"),
            onnx_file_name="model.onnx",
            local_output_dir=Path("/tmp/ra_tools_test"),
            dry_run=True,
        )

        command = result["export"]["command"]
        self.assertIn(" python -c ", command)
        self.assertNotIn("python - <<", command)
        self.assertIn("export PYTHONPATH=/nfs/stuck_assist_model", command)

    def test_default_luban_python_streams_conda_output(self) -> None:
        config = default_config().luban

        self.assertIn("--no-capture-output", config.python_bin)
        self.assertIn("--no-capture-output", config.remote_python_bin)

    def test_export_skips_remote_export_when_onnx_exists(self) -> None:
        experiment = ExperimentInfo(
            name="exp",
            experiment_path=Path("/nfs/exp"),
            version_name="version_0",
            checkpoints_dir=Path("/nfs/exp/checkpoints/version_0"),
            log_dir=Path("/nfs/exp/log/version_0"),
            export_dir=None,
            log_file=Path("/nfs/exp/log/version_0/train_scenario_dnn.log"),
            hparams_file=Path("/nfs/exp/log/version_0/hparams.yaml"),
            tensorboard_files=[],
            checkpoints=[Path("/nfs/exp/checkpoints/version_0/epoch=007.pth")],
            exported_epochs=[],
            remote_host="luban_2_card",
        )
        runner = LubanRunner(LubanConfig(train_repo="/nfs/stuck_assist_model"))

        with mock.patch.object(runner, "_run") as run_mock:
            run_mock.side_effect = [
                {
                    "command": "ssh test -f model.onnx",
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
                {
                    "command": "scp model.onnx local",
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
            ]

            result = runner.export_onnx(
                experiment=experiment,
                checkpoint_path=Path("/nfs/exp/checkpoints/version_0/epoch=007.pth"),
                onnx_file_name="model.onnx",
                local_output_dir=Path("/tmp/ra_tools_test"),
            )

        self.assertEqual(result["existing_onnx"]["returncode"], 0)
        self.assertIsNone(result["export"]["returncode"])
        self.assertIn("already exists", result["export"]["stderr"])
        self.assertEqual(result["scp"]["returncode"], 0)
        self.assertEqual(run_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
