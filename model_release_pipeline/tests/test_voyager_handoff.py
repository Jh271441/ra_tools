"""Tests for handoff generation."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from typing import Sequence

from model_release_pipeline.config import default_config
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService


class VoyagerHandoffTest(unittest.TestCase):
    def test_generate_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            config = default_config()
            service = VoyagerHandoffService(config.voyager)
            result = service.generate(
                run_dir=run_dir,
                ifx_mapping={
                    "onnx": {
                        "name": "vectorized_scenario_remote_assist_model.onnx",
                        "version": 64,
                    },
                    "fp32_x86": {"name": "model_x86.ifxmodel", "version": 1},
                    "fp16_6000": {"name": "model_6000.ifxmodel", "version": 2},
                    "fp16_3060": {"name": "model_3060.ifxmodel", "version": 3},
                    "fp16_gen4": {"name": "model_gen4.ifxmodel", "version": 4},
                    "fp16_thor": {"name": "model_thor.ifxmodel", "version": 5},
                },
                description="demo",
                experiment_name="exp",
                selected_epoch=10,
            )
            manifest = Path(result["manifest_snippet"]).read_text(encoding="utf-8")
            self.assertIn("model_gen4.ifxmodel", manifest)
            commands = Path(result["commands_file"]).read_text(encoding="utf-8")
            self.assertIn("dcl diff -n -u 5716859", commands)

    def test_apply_to_docker_builds_safe_command(self) -> None:
        captured = {}

        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="Updated MANIFEST\n",
                stderr="",
            )

        config = default_config()
        config.ifx.truck_docker_container = "voyager-dev"
        service = VoyagerHandoffService(config.voyager, command_runner=fake_runner)

        result = service.apply_to_docker(
            ifx_config=config.ifx,
            ifx_mapping={
                "onnx": {
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 65,
                },
                "fp32_x86": {"name": "model_x86.ifxmodel", "version": 73},
                "fp16_6000": {"name": "model_6000.ifxmodel", "version": 38},
                "fp16_3060": {"name": "model_3060.ifxmodel", "version": 46},
                "fp16_gen4": {"name": "model_gen4.ifxmodel", "version": 46},
                "fp16_thor": {"name": "model_thor.ifxmodel", "version": 38},
            },
            description="demo",
            experiment_name="exp",
            selected_epoch=7,
            branch="master",
        )

        command = captured["command"]
        self.assertEqual(command[:3], ["docker", "exec", "voyager-dev"])
        self.assertIn("git checkout jasperchen/2026Q1_test_scenario_dnn_dev", command[-1])
        self.assertIn("git checkout master-Release_CN-a6d66b30c89 || true", command[-1])
        self.assertIn("git commit -m", command[-1])
        self.assertIn("V65. exp, epoch=7. demo", result["commit_message"])
        self.assertEqual(
            result["dcl_commands"],
            [
                "dcl diff -n -u 5716859 --nolint",
                "# optional explicit lint: dcl lint && dcl diff -n -u 5716859",
            ],
        )

    def test_apply_to_docker_dry_run_does_not_commit(self) -> None:
        captured = {}

        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="Would update MANIFEST\n",
                stderr="",
            )

        config = default_config()
        config.ifx.truck_docker_container = "voyager-dev"
        service = VoyagerHandoffService(config.voyager, command_runner=fake_runner)

        service.apply_to_docker(
            ifx_config=config.ifx,
            ifx_mapping={
                "onnx": {
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 65,
                }
            },
            description="demo",
            experiment_name="exp",
            selected_epoch=7,
            dry_run=True,
            allow_append=True,
        )

        shell_script = captured["command"][-1]
        self.assertIn("[dry-run] skip git add/commit", shell_script)
        self.assertNotIn("git commit -m", shell_script)

    def test_dcl_to_docker_uses_nolint_and_returns_to_base_branch(self) -> None:
        captured = {}

        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="DCL OK\n",
                stderr="",
            )

        config = default_config()
        config.ifx.truck_docker_container = "voyager-dev"
        service = VoyagerHandoffService(config.voyager, command_runner=fake_runner)

        result = service.dcl_to_docker(
            ifx_config=config.ifx,
            branch="master",
        )

        shell_script = captured["command"][-1]
        self.assertIn("dcl diff -n -u 5716859 --nolint", shell_script)
        self.assertIn("git checkout master-Release_CN-a6d66b30c89 || true", shell_script)
        self.assertEqual(result["returncode"], 0)

    def test_apply_script_preserves_manifest_spacing_and_skips_same_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = Path(tmp_dir) / "MANIFEST.txt"
            original = (
                "planner.model-files vectorized_scenario_remote_assist_model.onnx"
                "    62    ./planner_models/vectorized_scenario_remote_assist_model.onnx"
                "    Vectorized scenario assist stuck model.\n"
                "planner.model-files vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel"
                "    70    ./planner_models/vectorized_scenario_remote_assist_model_x86.ifxmodel\n"
            )
            manifest.write_text(original, encoding="utf-8")
            service = VoyagerHandoffService(default_config().voyager)
            payload = {
                "manifest_path": str(manifest),
                "manifest_lines": [
                    (
                        "planner.model-files vectorized_scenario_remote_assist_model.onnx "
                        "65 ./planner_models/vectorized_scenario_remote_assist_model.onnx "
                        "Vectorized scenario assist stuck model."
                    ),
                    (
                        "planner.model-files vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel "
                        "73 ./planner_models/vectorized_scenario_remote_assist_model_x86.ifxmodel"
                    ),
                ],
                "allow_append": False,
                "dry_run": False,
            }
            encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

            first = subprocess.run(
                ["python3", "-c", service._apply_script(), encoded],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            updated = manifest.read_text(encoding="utf-8")
            self.assertIn("    65    ./planner_models", updated)
            self.assertIn("    73    ./planner_models", updated)
            self.assertNotIn(".onnx 65 ./planner_models", updated)

            second = subprocess.run(
                ["python3", "-c", service._apply_script(), encoded],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(manifest.read_text(encoding="utf-8"), updated)
            self.assertIn("No MANIFEST changes needed", second.stdout)


if __name__ == "__main__":
    unittest.main()
