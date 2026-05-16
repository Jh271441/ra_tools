"""Tests for Trail/truck command handling."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_release_pipeline.config import IfxConfig, SimPlanConfig
from model_release_pipeline.services.sim_plan import SimPlanClient
from model_release_pipeline.services.trail_client import TrailClient


class TrailClientTest(unittest.TestCase):
    def test_sim_plan_client_reads_token_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            token_file = Path(tmp_dir) / "token"
            token_file.write_text("demo-token\n", encoding="utf-8")

            client = SimPlanClient(SimPlanConfig(token_file=str(token_file)))

            self.assertEqual(client._token(), "demo-token")

    def test_docker_truck_command_sources_voyager_setup(self) -> None:
        config = IfxConfig(
            truck_runner="docker",
            truck_docker_container="voyager_dev",
            truck_docker_shell="/bin/zsh",
            truck_docker_workdir="/home/didi/workspace/voyager",
            truck_docker_setup="source /home/didi/workspace/voyager/bazel/scripts/setup.sh",
        )

        args = TrailClient(config)._docker_truck_args(["--help"])

        self.assertEqual(args[:3], ["docker", "exec", "voyager_dev"])
        self.assertIn("/bin/zsh", args)
        self.assertIn(
            "source /home/didi/workspace/voyager/bazel/scripts/setup.sh",
            " ".join(args),
        )
        self.assertIn("|| true", " ".join(args))
        self.assertEqual(args[-1], "--help")

    def test_ssh_truck_command_sources_configured_voyager_root(self) -> None:
        config = IfxConfig(
            truck_runner="ssh",
            truck_ssh_host="cloud_server",
            truck_ssh_shell="/bin/zsh",
            truck_ssh_workdir="/home/didi/workspace/voyager2",
            truck_ssh_setup="source /home/didi/workspace/voyager2/bazel/scripts/setup.sh",
        )

        args = TrailClient(config)._ssh_truck_args(["list"])

        self.assertEqual(args[:2], ["ssh", "cloud_server"])
        command = args[2]
        self.assertIn("/bin/zsh", command)
        self.assertIn("/home/didi/workspace/voyager2", command)
        self.assertIn("truck.py", command)
        self.assertIn("list", command)

    def test_local_truck_command_can_include_extra_args(self) -> None:
        config = IfxConfig(truck_cmd="truck.py --user-location CN")

        args = TrailClient(config)._local_truck_args(["list"])

        self.assertEqual(args, ["truck.py", "--user-location", "CN", "list"])

    def test_runner_info_reports_selected_runner(self) -> None:
        client = TrailClient(IfxConfig(truck_runner="auto"))
        client._runner = "docker"
        client.runner_attempts = [{"runner": "docker", "returncode": 0, "stderr": ""}]

        info = client.runner_info()

        self.assertEqual(info["configured"], "auto")
        self.assertEqual(info["selected"], "docker")
        self.assertEqual(info["attempts"][0]["runner"], "docker")

    def test_explicit_push_version_is_verified_and_not_overwritten_by_latest_query(self) -> None:
        class FakeTrailClient(TrailClient):
            def _select_truck_runner(self) -> str:
                self._runner = "local"
                return "local"

            def _run_truck(self, args, runner=None):
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            def get_latest_version(self, module: str, name: str):
                return 65

            def version_exists(self, module, name, version, attempts=3, delay_sec=1.0):
                return True, subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "vectorized_scenario_remote_assist_model.onnx"
            path.write_text("onnx", encoding="utf-8")

            artifact = FakeTrailClient(IfxConfig(truck_runner="local")).push_file(
                file_path=path,
                module="planner.model-files",
                description="demo",
                version=66,
            )

        self.assertEqual(artifact.version, 66)

    def test_explicit_push_requires_version_to_exist_after_push(self) -> None:
        class FakeTrailClient(TrailClient):
            def _select_truck_runner(self) -> str:
                self._runner = "local"
                return "local"

            def _run_truck(self, args, runner=None):
                if args and args[0] == "list":
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        stdout=(
                            "planner.model-files "
                            "vectorized_scenario_remote_assist_model.onnx 65"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(args, 0, stdout="push ok", stderr="")

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "vectorized_scenario_remote_assist_model.onnx"
            path.write_text("onnx", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "uploaded version was not found"):
                FakeTrailClient(IfxConfig(truck_runner="local")).push_file(
                    file_path=path,
                    module="planner.model-files",
                    description="demo",
                    version=66,
                )

    def test_existing_same_file_error_is_concise(self) -> None:
        class FakeTrailClient(TrailClient):
            def _select_truck_runner(self) -> str:
                self._runner = "local"
                return "local"

            def _run_truck(self, args, runner=None):
                if args and args[0] == "list":
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        stdout=(
                            "planner.model-files "
                            "vectorized_scenario_remote_assist_model.onnx 65"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=(
                        "[OK] Rpc failed, url: http://trail/fileserver/file/add/ "
                        "code: 60 msg: The file is already exist, exist file info: "
                        "md5:f46f9ffe86055703834ec048d34cd2a2, "
                        "module: planner.model-files,"
                        "file_name: vectorized_scenario_remote_assist_model.onnx, "
                        "version: 65"
                    ),
                    stderr="",
                )

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "vectorized_scenario_remote_assist_model.onnx"
            path.write_text("onnx", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Use the existing version 65"):
                FakeTrailClient(IfxConfig(truck_runner="local")).push_file(
                    file_path=path,
                    module="planner.model-files",
                    description="demo",
                    version=66,
                )


if __name__ == "__main__":
    unittest.main()
