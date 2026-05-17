"""Tests for remote experiment inspection."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

from model_release_pipeline.config import default_config
from model_release_pipeline.models import ExperimentInfo
from model_release_pipeline.onboard.export import _inspect_experiment_with_luban_fallback
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.model_picker import ModelPicker


class RemoteExperimentTest(unittest.TestCase):
    def test_remote_inspect_and_pick_uses_returned_log_text(self) -> None:
        payload = {
            "name": "remote_exp",
            "experiment_path": "/nfs/remote/remote_exp",
            "version_name": "version_0",
            "checkpoints_dir": "/nfs/remote/remote_exp/checkpoints/version_0",
            "log_dir": "/nfs/remote/remote_exp/log/version_0",
            "export_dir": None,
            "log_file": "/nfs/remote/remote_exp/log/version_0/train_scenario_dnn.log",
            "hparams_file": "/nfs/remote/remote_exp/log/version_0/hparams.yaml",
            "tensorboard_files": [],
            "checkpoints": [
                "/nfs/remote/remote_exp/checkpoints/version_0/epoch=000.pth",
                "/nfs/remote/remote_exp/checkpoints/version_0/epoch=001.pth",
            ],
            "exported_epochs": [],
            "current_trained_model_relative_path": "checkpoints/version_0/epoch=000.pth",
            "log_text": (
                "epoch=000 val_loss=0.3 val_precision=0.70 val_recall=0.80\n"
                "epoch=001 val_loss=0.2 val_precision=0.90 val_recall=0.75\n"
            ),
        }
        completed = CompletedProcess(
            args=["ssh"], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        remote_python = "/home/luban/miniconda3/bin/conda run -n scen_dnn python"
        with mock.patch("subprocess.run", return_value=completed) as run_mock:
            experiment = ExperimentInspector(
                remote_python_bin=remote_python
            ).inspect(
                "/nfs/remote/remote_exp", remote_host="luban_1_card"
            )

        self.assertEqual(experiment.remote_host, "luban_1_card")
        self.assertNotIn("log_text", experiment.to_dict())
        run_mock.assert_called_once()
        self.assertIn(remote_python, run_mock.call_args.args[0][2])
        result = ModelPicker().pick(experiment, policy="precision_first")
        self.assertEqual(result["recommended_epoch"], 1)

    def test_directory_pick_prefers_version_dir_over_export_epoch_dir(self) -> None:
        from model_release_pipeline.services.experiment import _pick_first_dir

        with self.subTest("version directory wins lexicographic sort"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                (root / "epoch=009").mkdir()
                (root / "version_0").mkdir()
                self.assertEqual(_pick_first_dir(root).name, "version_0")

    def test_remote_inspect_falls_back_when_luban_mount_is_broken(self) -> None:
        config = default_config()
        calls = []

        class FakeInspector:
            def __init__(self, *args, **kwargs):
                pass

            def inspect(self, experiment_path, remote_host=None):
                calls.append(remote_host)
                if remote_host == "luban_2_card":
                    raise RuntimeError(
                        "Remote inspect failed: OSError: [Errno 107] "
                        "Transport endpoint is not connected"
                    )
                return ExperimentInfo(
                    name="exp",
                    experiment_path=Path(experiment_path),
                    version_name="version_0",
                    checkpoints_dir=Path("/nfs/exp/checkpoints/version_0"),
                    log_dir=Path("/nfs/exp/log/version_0"),
                    export_dir=None,
                    log_file=None,
                    hparams_file=None,
                    tensorboard_files=[],
                    checkpoints=[],
                    exported_epochs=[],
                    remote_host=remote_host,
                )

        experiment = _inspect_experiment_with_luban_fallback(
            "/nfs/exp",
            config,
            remote="luban_2_card",
            remote_python=None,
            inspector_cls=FakeInspector,
        )

        self.assertEqual(calls, ["luban_2_card", "luban_1_card"])
        self.assertEqual(experiment.remote_host, "luban_1_card")


if __name__ == "__main__":
    unittest.main()
