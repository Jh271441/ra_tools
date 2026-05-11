"""Remote Luban execution helpers."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Dict

from model_release_pipeline.config import LubanConfig
from model_release_pipeline.models import ExperimentInfo


class LubanRunner:
    """Runs export and offboard commands on a remote Luban host."""

    def __init__(self, config: LubanConfig) -> None:
        self.config = config

    def _host(self, experiment: ExperimentInfo | None = None) -> str:
        if experiment and experiment.remote_host:
            return experiment.remote_host
        return self.config.host_alias

    def _run(self, args: list[str], dry_run: bool = False) -> Dict[str, object]:
        command_text = " ".join(shlex.quote(arg) for arg in args)
        if dry_run:
            return {
                "command": command_text,
                "returncode": None,
                "stdout": "",
                "stderr": "",
            }
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        return {
            "command": command_text,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def export_onnx(
        self,
        experiment: ExperimentInfo,
        checkpoint_path: Path,
        onnx_file_name: str,
        local_output_dir: Path,
        dry_run: bool = False,
    ) -> Dict[str, object]:
        if not experiment.hparams_file:
            raise RuntimeError("hparams.yaml not found in experiment log directory.")

        remote_hparams = experiment.hparams_file
        checkpoint_rel = checkpoint_path.relative_to(experiment.experiment_path)
        epoch_dir_name = checkpoint_path.stem
        remote_temp_yaml = remote_hparams.with_name(
            f"{remote_hparams.stem}.release_{epoch_dir_name}.yaml"
        )
        export_epoch_dir = (
            experiment.experiment_path
            / "export"
            / experiment.version_name
            / epoch_dir_name
        )
        remote_onnx_file = export_epoch_dir / onnx_file_name
        inline_python = f"""
from pathlib import Path
src = Path({remote_hparams.as_posix()!r})
dst = Path({remote_temp_yaml.as_posix()!r})
target = {checkpoint_rel.as_posix()!r}
lines = src.read_text(encoding='utf-8').splitlines()
rewritten = []
found = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith('trained_model_relative_path:'):
        indent = line[:len(line) - len(line.lstrip())]
        rewritten.append(f"{{indent}}trained_model_relative_path: {{target}}")
        found = True
    else:
        rewritten.append(line)
if not found:
    rewritten.append(f"trained_model_relative_path: {{target}}")
dst.write_text("\\n".join(rewritten) + "\\n", encoding='utf-8')
"""
        remote_script = "\n".join(
            [
                "set -e",
                f"{self.config.remote_python_bin} - <<'PY'",
                inline_python.strip(),
                "PY",
                f"cd {shlex.quote(self.config.train_repo)}",
                f"{self.config.python_bin} "
                f"{shlex.quote(self.config.export_script)} "
                f"--config-yaml {shlex.quote(remote_temp_yaml.as_posix())}",
            ]
        )
        export_result = self._run(
            ["ssh", self._host(experiment), "bash", "-lc", remote_script],
            dry_run=dry_run,
        )
        local_output_dir.mkdir(parents=True, exist_ok=True)
        local_onnx_file = local_output_dir / onnx_file_name
        scp_result = self._run(
            [
                "scp",
                f"{self._host(experiment)}:{remote_onnx_file.as_posix()}",
                str(local_onnx_file),
            ],
            dry_run=dry_run,
        )
        return {
            "host": self._host(experiment),
            "temp_config": remote_temp_yaml.as_posix(),
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_relative_path": checkpoint_rel.as_posix(),
            "remote_onnx_file": remote_onnx_file.as_posix(),
            "local_onnx_file": str(local_onnx_file),
            "export_dir": export_epoch_dir.as_posix(),
            "export": export_result,
            "scp": scp_result,
        }

    def run_offboard_test(
        self,
        checkpoint_path: Path,
        remote_host: str | None = None,
        dry_run: bool = False,
    ) -> Dict[str, object]:
        remote_config = Path(self.config.train_repo) / self.config.offboard_config_path
        remote_temp_yaml = remote_config.with_name(
            f"{remote_config.stem}.release_offboard_{checkpoint_path.stem}.yaml"
        )
        inline_python = f"""
from pathlib import Path
src = Path({remote_config.as_posix()!r})
dst = Path({remote_temp_yaml.as_posix()!r})
target = {checkpoint_path.as_posix()!r}
lines = src.read_text(encoding='utf-8').splitlines()
rewritten = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith('load_partial_checkpoint:'):
        indent = line[:len(line) - len(line.lstrip())]
        rewritten.append(f"{{indent}}load_partial_checkpoint: {{target}}")
    else:
        rewritten.append(line)
dst.write_text("\\n".join(rewritten) + "\\n", encoding='utf-8')
"""
        remote_script = "\n".join(
            [
                "set -e",
                f"{self.config.remote_python_bin} - <<'PY'",
                inline_python.strip(),
                "PY",
                f"cd {shlex.quote(self.config.train_repo)}",
                f"{self.config.python_bin} "
                f"{shlex.quote(self.config.offboard_entry_script)} "
                f"--config-yaml {shlex.quote(remote_temp_yaml.as_posix())}",
            ]
        )
        result = self._run(
            ["ssh", remote_host or self.config.host_alias, "bash", "-lc", remote_script],
            dry_run=dry_run,
        )
        return {
            "host": remote_host or self.config.host_alias,
            "temp_config": remote_temp_yaml.as_posix(),
            "checkpoint_path": str(checkpoint_path),
            "command": result["command"],
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
