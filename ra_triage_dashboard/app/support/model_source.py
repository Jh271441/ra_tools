"""Model Source HTTP helpers."""

from __future__ import annotations

import csv
import io
import json
import mimetypes
from pathlib import Path
from typing import Any

from ..contracts import MAX_SOURCE_PREVIEW_CELL_LENGTH
from ..filenames import safe_filename as _safe_filename
from ..sanitization import redact_sensitive_fields
from ..runtime import database, settings
from .common import _as_text


def _model_source_artifact_path(source_hash: str, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".json", ".csv", ".xlsx", ".xlsm"}:
        suffix = ".bin"
    return settings.uploads_dir / f"model-run-{source_hash}{suffix}"

def _store_model_source(content: bytes, filename: str, source_hash: str) -> dict[str, str]:
    root = settings.uploads_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = _model_source_artifact_path(source_hash, filename).resolve()
    if root not in path.parents:
        raise OSError("模型结果来源文件路径越界。")
    if not path.is_file():
        path.write_bytes(content)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return {
        "stored_name": path.name,
        "filename": _safe_filename(filename),
        "media_type": media_type,
    }

def _model_source_file(run: dict[str, Any]) -> tuple[Path, str] | None:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    artifact = metadata.get("source_artifact") if isinstance(metadata.get("source_artifact"), dict) else {}
    stored_name = _as_text(artifact.get("stored_name"))
    if stored_name:
        root = settings.uploads_dir.resolve()
        candidate = (root / stored_name).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate, _safe_filename(_as_text(artifact.get("filename")) or candidate.name)

    # Runs created before source_artifact metadata was introduced can still be
    # resolved by their immutable content hash when the archive was written.
    source_hash = _as_text(run.get("source_sha256"))
    source_name = _as_text(run.get("source_name"))
    if source_hash and run.get("kind", "upload") == "upload":
        root = settings.uploads_dir.resolve()
        candidate = _model_source_artifact_path(source_hash, source_name).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate, _safe_filename(Path(source_name).name or candidate.name)

    # Older runs may point at a source file that was already present on the
    # server. Keep this fallback constrained to known dashboard/data roots.
    if source_name:
        candidate = Path(source_name).expanduser()
        allowed_roots = (
            settings.uploads_dir.resolve(),
            settings.data_dir.resolve(),
            settings.ra_auto_triage_root.resolve(),
        )
        if candidate.is_absolute() and candidate.is_file():
            resolved = candidate.resolve()
            if any(root == resolved or root in resolved.parents for root in allowed_roots):
                return resolved, _safe_filename(resolved.name)
    return None

def _source_preview_value(value: Any) -> str:
    """Return a bounded, credential-redacted cell value for the preview UI."""

    safe_value = redact_sensitive_fields(value)
    if isinstance(safe_value, (dict, list, tuple)):
        text = json.dumps(
            safe_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    else:
        text = _as_text(safe_value)
    if len(text) <= MAX_SOURCE_PREVIEW_CELL_LENGTH:
        return text
    return text[: MAX_SOURCE_PREVIEW_CELL_LENGTH - 1] + "…"

def _model_source_filename(run: dict[str, Any]) -> str:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    artifact = metadata.get("source_artifact") if isinstance(metadata.get("source_artifact"), dict) else {}
    return _safe_filename(
        _as_text(artifact.get("filename"))
        or Path(_as_text(run.get("source_name"))).name
        or "model-results.json"
    )

def _reconstructed_model_source(
    run_id: str,
    run: dict[str, Any],
) -> tuple[bytes, str, str] | None:
    """Rebuild a safe source copy for uploads made before file archiving."""

    filename = _model_source_filename(run)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".json", ".csv"}:
        return None
    rows = database.model_run_source_rows(run_id)
    if not rows:
        return None
    if suffix == ".csv":
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8-sig"), filename, "text/csv; charset=utf-8"
    payload = {
        "schema_version": "reconstructed-model-run-v1",
        "source_name": _as_text(run.get("source_name")),
        "source_sha256": _as_text(run.get("source_sha256")),
        "results": rows,
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        filename,
        "application/json",
    )
