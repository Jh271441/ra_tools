"""Experiment discovery helpers."""

from __future__ import annotations

import json
import base64
import re
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

from model_release_pipeline.models import ExperimentInfo


_EPOCH_FILE_RE = re.compile(r"epoch=(\d+)\.pth$")


def _pick_first_dir(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    dirs = sorted([item for item in path.iterdir() if item.is_dir()])
    version_dirs = [item for item in dirs if item.name.startswith("version_")]
    if version_dirs:
        return version_dirs[0]
    return dirs[0] if dirs else None


def _exported_epochs(export_version_dir: Optional[Path]) -> List[str]:
    if not export_version_dir or not export_version_dir.exists():
        return []
    return sorted([item.name for item in export_version_dir.iterdir() if item.is_dir()])


def _extract_current_model_path(hparams_file: Optional[Path]) -> Optional[str]:
    if not hparams_file or not hparams_file.exists():
        return None
    for line in hparams_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("trained_model_relative_path:"):
            return line.split(":", 1)[1].strip()
    return None


def _extract_tasks(hparams_file: Optional[Path]) -> List[str]:
    if not hparams_file or not hparams_file.exists():
        return []
    text = hparams_file.read_text(encoding="utf-8", errors="ignore")
    tasks = []
    in_activated = False
    activated_indent = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lstrip("- ").startswith("activated_tasks:"):
            in_activated = True
            activated_indent = len(line) - len(line.lstrip())
            continue
        if not in_activated:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= activated_indent:
            in_activated = False
            continue
        if stripped.startswith("- "):
            task = stripped[2:].strip()
            if task and task not in tasks:
                tasks.append(task)
    return tasks


def _sorted_checkpoints(checkpoints_dir: Optional[Path]) -> List[Path]:
    if not checkpoints_dir or not checkpoints_dir.exists():
        return []
    checkpoints = []
    for item in checkpoints_dir.iterdir():
        match = _EPOCH_FILE_RE.search(item.name)
        if item.is_file() and match:
            checkpoints.append((int(match.group(1)), item))
    return [item for _, item in sorted(checkpoints, key=lambda pair: pair[0])]


class ExperimentInspector:
    """Inspects a scenario dnn experiment directory."""

    def __init__(self, remote_python_bin: str = "python3") -> None:
        self.remote_python_bin = remote_python_bin

    def inspect(
        self, experiment_path: str | Path, remote_host: Optional[str] = None
    ) -> ExperimentInfo:
        if remote_host:
            return self._inspect_remote(experiment_path, remote_host)
        return self._inspect_local(experiment_path)

    def _inspect_local(self, experiment_path: str | Path) -> ExperimentInfo:
        root = Path(experiment_path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Experiment path does not exist: {root}")

        checkpoints_version_dir = _pick_first_dir(root / "checkpoints")
        log_version_dir = _pick_first_dir(root / "log")
        export_version_dir = _pick_first_dir(root / "export")
        version_name = "version_0"
        if log_version_dir:
            version_name = log_version_dir.name
        elif checkpoints_version_dir:
            version_name = checkpoints_version_dir.name

        checkpoints_dir = checkpoints_version_dir
        log_dir = log_version_dir
        export_dir = root / "export"
        log_file = log_dir / "train_scenario_dnn.log" if log_dir else None
        hparams_file = log_dir / "hparams.yaml" if log_dir else None
        tensorboard_files = (
            sorted(log_dir.glob("events.out.tfevents.*")) if log_dir else []
        )
        return ExperimentInfo(
            name=root.name,
            experiment_path=root,
            version_name=version_name,
            checkpoints_dir=checkpoints_dir,
            log_dir=log_dir,
            export_dir=export_dir if export_dir.exists() else None,
            log_file=log_file if log_file and log_file.exists() else None,
            hparams_file=hparams_file if hparams_file and hparams_file.exists() else None,
            tensorboard_files=tensorboard_files,
            checkpoints=_sorted_checkpoints(checkpoints_dir),
            exported_epochs=_exported_epochs(export_version_dir),
            current_trained_model_relative_path=_extract_current_model_path(
                hparams_file if hparams_file and hparams_file.exists() else None
            ),
            tasks=_extract_tasks(
                hparams_file if hparams_file and hparams_file.exists() else None
            ),
        )

    def _inspect_remote(
        self, experiment_path: str | Path, remote_host: str
    ) -> ExperimentInfo:
        script = r"""
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.exists():
    raise FileNotFoundError(f"Experiment path does not exist: {root}")

epoch_re = re.compile(r"epoch=(\d+)\.pth$")

def first_dir(path):
    if not path.exists():
        return None
    dirs = sorted([item for item in path.iterdir() if item.is_dir()])
    version_dirs = [item for item in dirs if item.name.startswith("version_")]
    if version_dirs:
        return version_dirs[0]
    return dirs[0] if dirs else None

def list_checkpoints(path):
    if path is None or not path.exists():
        return []
    found = []
    for item in path.iterdir():
        match = epoch_re.search(item.name)
        if item.is_file() and match:
            found.append((int(match.group(1)), item.as_posix()))
    return [item for _, item in sorted(found, key=lambda pair: pair[0])]

def exported_epochs(path):
    if path is None or not path.exists():
        return []
    return sorted([item.name for item in path.iterdir() if item.is_dir()])

def read_text(path):
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="ignore")

def read_metric_text(path):
    text = read_text(path)
    if not text:
        return None
    keep = []
    metric_keywords = ("loss", "precision", "prec", "recall", "auc", "accuracy", "f1")
    block_remaining = 0
    for line in text.splitlines():
        lower = line.lower()
        if "validation metrics (epoch" in lower:
            block_remaining = 14
        if block_remaining > 0:
            keep.append(line)
            block_remaining -= 1
            continue
        if "epoch" in lower and any(keyword in lower for keyword in metric_keywords):
            keep.append(line)
    return "\n".join(keep)

def metric_counts(text):
    if not text:
        return {}
    counts = {}
    pattern = re.compile(r"Task\s+([^:]+):\s+Validation Metrics \(Epoch\s+(\d+)", re.IGNORECASE)
    for line in text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        task = match.group(1).strip()
        counts.setdefault(task, set()).add(int(match.group(2)))
    return {task: len(epochs) for task, epochs in counts.items()}

def needs_tensorboard(metric_text, tasks, checkpoint_count):
    if not tasks:
        return not metric_text
    if not metric_text:
        return True
    minimum = max(1, int(checkpoint_count * 0.8 + 0.999))
    counts = metric_counts(metric_text)
    return any(counts.get(task, 0) < minimum for task in tasks)

def extract_tasks(path):
    text = read_text(path)
    if not text:
        return []
    tasks = []
    in_activated = False
    activated_indent = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lstrip("- ").startswith("activated_tasks:"):
            in_activated = True
            activated_indent = len(line) - len(line.lstrip())
            continue
        if not in_activated:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= activated_indent:
            in_activated = False
            continue
        if stripped.startswith("- "):
            task = stripped[2:].strip()
            if task and task not in tasks:
                tasks.append(task)
    return tasks

def current_model_path(path):
    text = read_text(path)
    if not text:
        return None
    for line in text.splitlines():
        if line.strip().startswith("trained_model_relative_path:"):
            return line.split(":", 1)[1].strip()
    return None

def normalize_metric(tag):
    lower = tag.lower()
    if not lower.startswith("val/"):
        return None
    if "roc_auc" in lower or "auc/roc" in lower or "roc-auc" in lower:
        return "roc_auc"
    if "pr_auc" in lower or "auc/pr" in lower or "prauc" in lower:
        return "pr_auc"
    if "precision" in lower or lower.endswith("/prec") or "prec" in lower:
        return "precision"
    if "recall" in lower:
        return "recall"
    if "loss" in lower:
        return "loss"
    if "accuracy" in lower or lower.endswith("/acc") or "acc" in lower:
        return "accuracy"
    if "f1_score" in lower or lower.endswith("/f1") or "f1" in lower:
        return "f1_score"
    return None

def task_for_tag(tag, tasks):
    lower = tag.lower()
    for task in sorted(tasks, key=len, reverse=True):
        if task.lower() in lower:
            return task
    return tasks[0] if len(tasks) == 1 else "default"

def read_tensorboard_scalars(paths, tasks):
    if not paths:
        return {}
    try:
        from tensorboard.backend.event_processing import event_accumulator
    except Exception:
        return {}
    collected = {}
    for raw_path in paths:
        try:
            accumulator = event_accumulator.EventAccumulator(
                raw_path, size_guidance={"scalars": 0}
            )
            accumulator.Reload()
        except Exception:
            continue
        tags = accumulator.Tags().get("scalars", [])
        step_to_epoch = {}
        if "epoch" in tags:
            try:
                for scalar in accumulator.Scalars("epoch"):
                    step_to_epoch[int(scalar.step)] = int(round(float(scalar.value)))
            except Exception:
                step_to_epoch = {}
        for tag in tags:
            if tag == "epoch":
                continue
            metric = normalize_metric(tag)
            if not metric:
                continue
            task = task_for_tag(tag, tasks)
            task_bucket = collected.setdefault(task, {})
            try:
                scalars = accumulator.Scalars(tag)
            except Exception:
                continue
            for scalar in scalars:
                epoch = step_to_epoch.get(int(scalar.step), int(scalar.step))
                task_bucket.setdefault(epoch, {})[metric] = float(scalar.value)
    return collected

checkpoints_version_dir = first_dir(root / "checkpoints")
log_version_dir = first_dir(root / "log")
export_version_dir = first_dir(root / "export")
version_name = "version_0"
if log_version_dir:
    version_name = log_version_dir.name
elif checkpoints_version_dir:
    version_name = checkpoints_version_dir.name

log_file = log_version_dir / "train_scenario_dnn.log" if log_version_dir else None
hparams_file = log_version_dir / "hparams.yaml" if log_version_dir else None
tb_files = (
    sorted([item.as_posix() for item in log_version_dir.glob("events.out.tfevents.*")])
    if log_version_dir
    else []
)
tasks = extract_tasks(hparams_file)
metric_text = read_metric_text(log_file)
checkpoint_list = list_checkpoints(checkpoints_version_dir)

payload = {
    "name": root.name,
    "experiment_path": root.as_posix(),
    "version_name": version_name,
    "checkpoints_dir": checkpoints_version_dir.as_posix() if checkpoints_version_dir else None,
    "log_dir": log_version_dir.as_posix() if log_version_dir else None,
    "export_dir": (root / "export").as_posix() if (root / "export").exists() else None,
    "log_file": log_file.as_posix() if log_file and log_file.exists() else None,
    "hparams_file": hparams_file.as_posix() if hparams_file and hparams_file.exists() else None,
    "tensorboard_files": tb_files,
    "checkpoints": checkpoint_list,
    "exported_epochs": exported_epochs(export_version_dir),
    "current_trained_model_relative_path": current_model_path(hparams_file),
    "tasks": tasks,
    "log_text": metric_text,
    "tensorboard_scalars": (
        {}
        if not needs_tensorboard(metric_text, tasks, len(checkpoint_list))
        else read_tensorboard_scalars(tb_files, tasks)
    ),
}
print(json.dumps(payload, ensure_ascii=False))
"""
        encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
        python_eval = (
            "import base64; "
            f"exec(base64.b64decode({encoded_script!r}).decode('utf-8'))"
        )
        remote_command = (
            f"{self.remote_python_bin} -c {shlex.quote(python_eval)} "
            f"{shlex.quote(str(experiment_path))}"
        )
        result = subprocess.run(
            [
                "ssh",
                remote_host,
                remote_command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            command = (
                f"ssh {shlex.quote(remote_host)} {remote_command}"
            )
            raise RuntimeError(
                f"Remote inspect failed: {command}\n{result.stderr.strip()}"
            )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Remote inspect did not return JSON.\n"
                f"stdout:\n{result.stdout[:2000]}\n"
                f"stderr:\n{result.stderr[:2000]}"
            ) from exc
        return ExperimentInfo(
            name=data["name"],
            experiment_path=Path(data["experiment_path"]),
            version_name=data["version_name"],
            checkpoints_dir=Path(data["checkpoints_dir"]) if data["checkpoints_dir"] else None,
            log_dir=Path(data["log_dir"]) if data["log_dir"] else None,
            export_dir=Path(data["export_dir"]) if data["export_dir"] else None,
            log_file=Path(data["log_file"]) if data["log_file"] else None,
            hparams_file=Path(data["hparams_file"]) if data["hparams_file"] else None,
            tensorboard_files=[Path(item) for item in data["tensorboard_files"]],
            checkpoints=[Path(item) for item in data["checkpoints"]],
            exported_epochs=data["exported_epochs"],
            current_trained_model_relative_path=data[
                "current_trained_model_relative_path"
            ],
            tasks=data.get("tasks", []),
            remote_host=remote_host,
            log_text=data.get("log_text"),
            tensorboard_scalars=data.get("tensorboard_scalars", {}),
        )
