"""Helpers for versioned ONNX backups and local utility copies."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional


LOCAL_ONNX_DIR = Path("~/utils/onnx")


def _onnx_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return (record.get("ifx") or {}).get("onnx") or {}


def _onnx_version(record: Dict[str, Any]) -> int:
    version = _onnx_record(record).get("version")
    if version is None:
        version = (
            ((record.get("ifx") or {}).get("ifx_mapping") or {})
            .get("onnx", {})
            .get("version")
        )
    if not isinstance(version, int):
        raise RuntimeError("No uploaded ONNX version found in release record.")
    if version <= 0:
        raise RuntimeError("Dry-run ONNX version cannot be copied.")
    return version


def versioned_onnx_name(record: Dict[str, Any]) -> str:
    onnx = _onnx_record(record)
    source_name = str(onnx.get("name") or Path(str(onnx.get("local_path") or "")).name)
    if not source_name:
        raise RuntimeError("No uploaded ONNX name found in release record.")
    source_path = Path(source_name)
    suffix = source_path.suffix or ".onnx"
    return f"vectorized_{source_path.stem}_v{_onnx_version(record)}{suffix}"


def versioned_backup_path(runs_dir: Path, record: Dict[str, Any]) -> Path:
    release_id = str(record.get("release_id") or "")
    if not release_id:
        raise RuntimeError("No release_id found in release record.")
    return (
        Path(runs_dir).expanduser()
        / release_id
        / "artifacts"
        / versioned_onnx_name(record)
    )


def local_copy_target(record: Dict[str, Any], target_dir: Optional[Path] = None) -> Path:
    base_dir = Path(target_dir) if target_dir is not None else LOCAL_ONNX_DIR
    return base_dir.expanduser() / versioned_onnx_name(record)


def versioned_onnx_info(
    runs_dir: Path,
    record: Dict[str, Any],
    target_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    try:
        backup = versioned_backup_path(runs_dir, record)
        target = local_copy_target(record, target_dir=target_dir)
    except RuntimeError:
        return None
    source_exists = backup.exists() or any(
        Path(str(candidate)).expanduser().exists()
        for candidate in _source_candidates(record, backup)
    )
    return {
        "name": backup.name,
        "backup_path": str(backup),
        "target_path": str(target),
        "available": source_exists,
    }


def ensure_versioned_backup(runs_dir: Path, record: Dict[str, Any]) -> Path:
    backup = versioned_backup_path(runs_dir, record)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        return backup

    for candidate in _source_candidates(record, backup):
        source = Path(str(candidate)).expanduser()
        if source.exists() and source.resolve() != backup.resolve():
            shutil.copy2(source, backup)
            return backup
    raise FileNotFoundError(f"Versioned ONNX source not found for backup: {backup}")


def copy_versioned_onnx_to_utils(
    runs_dir: Path,
    record: Dict[str, Any],
    target_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    source = ensure_versioned_backup(runs_dir, record)
    target = local_copy_target(record, target_dir=target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "source": str(source),
        "target": str(target),
        "bytes": target.stat().st_size,
    }


def _source_candidates(record: Dict[str, Any], backup: Path) -> list[str]:
    onnx = _onnx_record(record)
    export = record.get("export") or {}
    candidates = [
        onnx.get("versioned_backup_path"),
        export.get("versioned_onnx_file"),
        str(backup),
        onnx.get("local_path"),
        export.get("local_onnx_file"),
    ]
    return [str(candidate) for candidate in candidates if candidate]
