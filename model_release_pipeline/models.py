"""Shared models for the model release pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass
class MetricCandidate:
    """Candidate epoch metrics used for ranking."""

    epoch: int
    task: Optional[str] = None
    checkpoint_path: Optional[Path] = None
    loss: Optional[float] = None
    accuracy: Optional[float] = None
    f1_score: Optional[float] = None
    pr_auc: Optional[float] = None
    roc_auc: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    tn: Optional[int] = None
    fp: Optional[int] = None
    fn: Optional[int] = None
    tp: Optional[int] = None
    sources: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class ExperimentInfo:
    """Discovered experiment layout."""

    name: str
    experiment_path: Path
    version_name: str
    checkpoints_dir: Optional[Path]
    log_dir: Optional[Path]
    export_dir: Optional[Path]
    log_file: Optional[Path]
    hparams_file: Optional[Path]
    tensorboard_files: List[Path]
    checkpoints: List[Path]
    exported_epochs: List[str]
    current_trained_model_relative_path: Optional[str] = None
    remote_host: Optional[str] = None
    tasks: List[str] = field(default_factory=list)
    log_text: Optional[str] = None
    tensorboard_scalars: Dict[str, Dict[int, Dict[str, float]]] = field(default_factory=dict)

    def checkpoint_for_epoch(self, epoch: int) -> Optional[Path]:
        for checkpoint in self.checkpoints:
            if checkpoint.stem == f"epoch={epoch:03d}":
                return checkpoint
        return None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("log_text", None)
        data.pop("tensorboard_scalars", None)
        return _jsonable(data)


@dataclass
class ArtifactVersion:
    """Uploaded artifact metadata."""

    module: str
    name: str
    version: Optional[int]
    local_path: Optional[Path] = None
    label: Optional[str] = None

    def truck_pull_arg(self) -> Optional[str]:
        if self.version is None:
            return None
        return f"{self.module} {self.name} -v {self.version}"

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(asdict(self))
