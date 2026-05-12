"""Remote Luban execution helpers."""

from __future__ import annotations

import shlex
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

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

    def _separator(self, char: str = "=") -> str:
        columns = shutil.get_terminal_size((100, 20)).columns
        width = max(40, int(columns * 0.9))
        return char * width

    def _progress(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def _progress_header(
        self, title: str, icon: str, step: int, total: int
    ) -> None:
        self._progress("")
        self._progress(self._separator("="))
        self._progress(f"{icon} {title}")
        self._progress(f"step: {step}/{total}")
        self._progress(f"tasks_remaining: {max(total - step, 0)}")
        self._progress(self._separator("="))

    def _emit_stream_text(
        self, stream_name: str, text: str, chunks: list[str]
    ) -> None:
        if not text:
            return
        chunks.append(text)
        for line in text.rstrip("\n").splitlines():
            self._progress(f"[{stream_name}] {line}")

    def _run(
        self,
        args: list[str],
        dry_run: bool = False,
        progress_label: Optional[str] = None,
        progress_interval_sec: int = 30,
    ) -> Dict[str, object]:
        command_text = " ".join(shlex.quote(arg) for arg in args)
        if dry_run:
            return {
                "command": command_text,
                "returncode": None,
                "stdout": "",
                "stderr": "",
            }
        if not progress_label:
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            return {
                "command": command_text,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        started = time.monotonic()
        next_report = started + progress_interval_sec
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        selector = selectors.DefaultSelector()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        if process.stdout is not None:
            selector.register(process.stdout, selectors.EVENT_READ, ("stdout", stdout_chunks))
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ, ("stderr", stderr_chunks))

        self._progress("")
        self._progress(f"---------- {progress_label} log begin ----------")
        while selector.get_map():
            timeout = max(0.1, next_report - time.monotonic())
            events = selector.select(timeout)
            if not events:
                if process.poll() is not None:
                    for key in list(selector.get_map().values()):
                        stream_name, chunks = key.data
                        remainder = key.fileobj.read()
                        self._emit_stream_text(stream_name, remainder, chunks)
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    break
                elapsed = int(time.monotonic() - started)
                self._progress(f"{progress_label} still running ({elapsed}s)...")
                next_report = time.monotonic() + progress_interval_sec
                continue

            for key, _ in events:
                stream_name, chunks = key.data
                line = key.fileobj.readline()
                if line:
                    self._emit_stream_text(stream_name, line, chunks)
                else:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
        returncode = process.wait()
        self._progress(f"---------- {progress_label} log end (returncode={returncode}) ----------")
        self._progress("")
        return {
            "command": command_text,
            "returncode": returncode,
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
        }

    def _skipped_result(self, args: list[str], reason: str) -> Dict[str, object]:
        return {
            "command": " ".join(shlex.quote(arg) for arg in args),
            "returncode": None,
            "stdout": "",
            "stderr": reason,
        }

    def _remote_python_c(self, code: str) -> str:
        return f"{self.config.remote_python_bin} -c {shlex.quote(code)}"

    def _remote_test_file(
        self,
        host: str,
        path: Path,
        dry_run: bool = False,
    ) -> Dict[str, object]:
        return self._run(
            [
                "ssh",
                host,
                "test",
                "-f",
                path.as_posix(),
            ],
            dry_run=dry_run,
        )

    def export_onnx(
        self,
        experiment: ExperimentInfo,
        checkpoint_path: Path,
        onnx_file_name: str,
        local_output_dir: Path,
        dry_run: bool = False,
        show_progress: bool = False,
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
        existing_onnx = self._remote_test_file(
            self._host(experiment),
            remote_onnx_file,
            dry_run=dry_run,
        )
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
                self._remote_python_c(inline_python.strip()),
                f"cd {shlex.quote(self.config.train_repo)}",
                f"export PYTHONPATH={shlex.quote(self.config.train_repo)}:${{PYTHONPATH:-}}",
                f"{self.config.python_bin} "
                f"{shlex.quote(self.config.export_script)} "
                f"--config-yaml {shlex.quote(remote_temp_yaml.as_posix())}",
            ]
        )
        if existing_onnx["returncode"] == 0:
            export_result = self._skipped_result(
                ["ssh", self._host(experiment), "bash", "-c", remote_script],
                "Skipped because remote ONNX already exists.",
            )
            if show_progress:
                self._progress(
                    f"remote ONNX already exists, skip export: {remote_onnx_file.as_posix()}"
                )
        else:
            export_result = self._run(
                ["ssh", self._host(experiment), "bash", "-c", remote_script],
                dry_run=dry_run,
                progress_label=(
                    f"remote export on {self._host(experiment)}"
                    if show_progress
                    else None
                ),
            )
        local_output_dir.mkdir(parents=True, exist_ok=True)
        local_onnx_file = local_output_dir / onnx_file_name
        scp_args = [
            "scp",
            f"{self._host(experiment)}:{remote_onnx_file.as_posix()}",
            str(local_onnx_file),
        ]
        if dry_run or export_result["returncode"] in (0, None):
            if show_progress:
                self._progress_header("Copy exported ONNX", "📥", 3, 3)
            scp_result = self._run(
                scp_args,
                dry_run=dry_run,
                progress_label="scp exported ONNX" if show_progress else None,
            )
        else:
            scp_result = self._skipped_result(
                scp_args, "Skipped because remote export failed."
            )
        return {
            "host": self._host(experiment),
            "temp_config": remote_temp_yaml.as_posix(),
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_relative_path": checkpoint_rel.as_posix(),
            "remote_onnx_file": remote_onnx_file.as_posix(),
            "local_onnx_file": str(local_onnx_file),
            "export_dir": export_epoch_dir.as_posix(),
            "existing_onnx": existing_onnx,
            "export": export_result,
            "scp": scp_result,
        }

    def run_offboard_test(
        self,
        checkpoint_path: Path,
        remote_host: str | None = None,
        dry_run: bool = False,
        show_progress: bool = False,
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
                self._remote_python_c(inline_python.strip()),
                f"cd {shlex.quote(self.config.train_repo)}",
                f"export PYTHONPATH={shlex.quote(self.config.train_repo)}:${{PYTHONPATH:-}}",
                f"{self.config.python_bin} "
                f"{shlex.quote(self.config.offboard_entry_script)} "
                f"--config-yaml {shlex.quote(remote_temp_yaml.as_posix())}",
            ]
        )
        result = self._run(
            ["ssh", remote_host or self.config.host_alias, "bash", "-c", remote_script],
            dry_run=dry_run,
            progress_label=(
                f"offboard test on {remote_host or self.config.host_alias}"
                if show_progress
                else None
            ),
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
