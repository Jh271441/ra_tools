from __future__ import annotations

"""HTTP/shared helpers extracted from main.py."""

import asyncio
import csv
import hashlib
import io
import json
import logging
import math
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .auth import (
    normalise_username,
    request_identity,
)
from .autotriage_source import AutoTriageSourceError, normalise_batch_id
from .baseline import load_baseline_entry
from .baseline_registry import (
    detect_issue_scope_overlaps,
    ids_to_scopes,
    normalize_baseline_ids,
)
from .contracts import (
    MAX_REVIEW_ATTACHMENT_BYTES,
    MAX_REVIEW_ATTACHMENT_PIXELS,
    MAX_REVIEW_ATTACHMENT_STORAGE_BYTES,
    MAX_REVIEW_ATTACHMENTS,
    MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
    MAX_SOURCE_PREVIEW_CELL_LENGTH,
    MIN_REVIEW_ATTACHMENT_DISK_FREE,
)
from .filenames import safe_filename as _safe_filename
from .db import AnnotationConflictError, LABELS, MODEL_LABELS, REVIEW_STATUSES
from .import_parsing import normalize_model_row, parse_source_bytes
from .model_labels import canonical_model_label
from .gt_sync import TRAIL_GT_FIELD, read_trail_gt_labels
from .review_analysis import COMPARISON_STATUSES, build_review_reason_analysis
from .review_mentions import extract_review_mentions, notification_recipients
from .review_workflow import (
    derive_review_status,
    resolve_expected_output,
)
from .sanitization import redact_sensitive_fields
from .trail_sync import (
    TRAIL_INFO_FIELD,
    TRAIL_RESULT_FIELD,
    ares_playback_metadata,
    read_trail_model_fields,
)
from .runtime import (
    MISSING_EVIDENCE_CATALOG,
    REVIEW_TAG_CATALOG,
    REVIEW_TAG_ALIASES,
    REVIEW_TAG_MANAGED_GROUPS,
    _public_path,
    autotriage_source,
    baseline_registry,
    database,
    gt_sync_lock,
    media_registry,
    review_image_semaphore,
    runtime_state,
    settings,
    trail_sync_lock,
)

logger = logging.getLogger("ra_triage_dashboard")

def _detail(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


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


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


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


def _voyager_issue_url(issue_id: str) -> str:
    return (
        f"{settings.voyager_issue_base_url.rstrip('/')}/"
        f"{quote(issue_id, safe='')}?view_id={settings.voyager_issue_view_id}"
    )


def _ra_recording_url(ra_id: Any) -> str:
    """Build the read-only RA dashboard URL from Trail's canonical ra_id."""

    value = _as_text(ra_id)
    if not value:
        return ""
    return (
        f"{settings.ra_recording_base_url.rstrip('/')}/"
        f"{quote(value, safe='')}?returnUrl="
    )


def _case_external_links(issue_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Expose the small, read-only RA link/event subset to the browser."""

    events = metadata.get("ra_event")
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except (TypeError, ValueError, json.JSONDecodeError):
            events = []
    safe_events: list[dict[str, Any]] = []
    if isinstance(events, (list, tuple)):
        for item in events:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or "").strip()[:128]
            if not event:
                continue
            raw_timestamp = item.get("timestamp")
            try:
                timestamp = int(raw_timestamp) if raw_timestamp is not None else None
            except (TypeError, ValueError, OverflowError):
                timestamp = None
            raw_value = item.get("value")
            if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                value = raw_value
            else:
                value = str(raw_value)[:256]
            safe_events.append({"event": event, "value": value, "timestamp": timestamp})
    safe_events = safe_events[:64]
    event_count = len(safe_events)
    ares_metadata = ares_playback_metadata(metadata, safe_events)
    return {
        "ra_recording_url": _ra_recording_url(metadata.get("ra_id")),
        "ra_event_url": _voyager_issue_url(issue_id) if event_count else "",
        "ra_task_id": _as_text(metadata.get("ra_id")),
        "ra_event_count": event_count,
        "ra_events": safe_events,
        # These two allowlisted values are sufficient to construct the Ares
        # read-only playback link after the asynchronous Trail lookup.  Keep
        # them inside external_links instead of mutating the persisted Issue.
        **ares_metadata,
    }


def _case_link_metadata_fallback(case: dict[str, Any]) -> dict[str, Any]:
    """Use explicitly imported RA fields when Trail detail lookup is disabled."""

    fallback: dict[str, Any] = {}
    for source in (case, case.get("extra")):
        if not isinstance(source, dict):
            continue
        for key in ("ra_id", "ra_event"):
            if key not in fallback and source.get(key) not in (None, "", []):
                fallback[key] = source[key]
    return fallback


def _autotriage_record_url(batch_id: str) -> str:
    if not batch_id:
        return ""
    return (
        f"{settings.auto_triage_record_base_url.rstrip('/')}/"
        f"{quote(batch_id, safe='')}?tab=results"
    )


def _public_batch_job(
    job: dict[str, Any],
    *,
    include_prompt: bool = False,
) -> dict[str, Any]:
    public = dict(job)
    prompt_template = _as_text(public.get("prompt_template"))
    public["prompt_template_length"] = len(prompt_template)
    public["prompt_preview"] = re.sub(r"\s+", " ", prompt_template)[:240]
    if not include_prompt:
        public.pop("prompt_template", None)
    public["record_url"] = _autotriage_record_url(
        _as_text(job.get("autotriage_batch_id"))
    )
    if "items" in job:
        public["items"] = [
            {
                **item,
                "voyager_issue_url": _voyager_issue_url(
                    _as_text(item.get("issue_id"))
                ),
            }
            for item in job.get("items", [])
        ]
    return public


def _safe_autotriage_batch(batch: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "batch_name",
        "username",
        "status",
        "prompt_version",
        "prompt_text",
        "model_name",
        "total_count",
        "completed_count",
        "success_count",
        "failed_count",
        "match_count",
        "mismatch_count",
        "accuracy",
        "experiment_id",
        "experiment_revision_id",
        "experiment_source",
        "created_at",
        "started_at",
        "finished_at",
    }
    safe = redact_sensitive_fields(
        {key: batch.get(key) for key in allowed if key in batch}
    )
    prompt_text = _as_text(safe.pop("prompt_text", ""))
    safe["prompt_sha256"] = (
        hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        if prompt_text
        else ""
    )
    safe["prompt_preview"] = re.sub(r"\s+", " ", prompt_text)[:240]
    safe["prompt_length"] = len(prompt_text)
    return safe


def _thumbnail_cache_path(issue_id: str, source: Path) -> Path:
    stat = source.stat()
    fingerprint = (
        f"{issue_id}\0{source}\0{stat.st_mtime_ns}\0{stat.st_size}"
    ).encode("utf-8")
    digest = hashlib.sha256(fingerprint).hexdigest()
    return settings.case_thumbnails_dir / f"{digest}.jpg"


def _render_case_thumbnail(source: Path, destination: Path) -> None:
    """Generate a small gallery JPEG quickly.

    Homepage loads many thumbs at once; prefer BILINEAR + modest size over
    LANCZOS on full 2K BEV frames so cold cache misses stay interactive.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    thumb_size = (480, 270)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.width * image.height > MAX_REVIEW_ATTACHMENT_PIXELS:
            raise ValueError("BEV 图片像素数过大。")
        if image.mode != "RGB":
            image = image.convert("RGB")
        # Draft first for very large sources, then final contain — much faster
        # than LANCZOS on 2560x1440 for gallery cards.
        if image.width > 1280 or image.height > 720:
            image.thumbnail((1280, 720), resample=Image.Resampling.BILINEAR)
        contained = ImageOps.contain(
            image,
            thumb_size,
            method=Image.Resampling.BILINEAR,
        )
        canvas = Image.new("RGB", thumb_size, color=(11, 18, 32))
        canvas.paste(
            contained,
            ((thumb_size[0] - contained.width) // 2, (thumb_size[1] - contained.height) // 2),
        )
        temp_path = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            canvas.save(
                temp_path,
                format="JPEG",
                quality=72,
                optimize=True,
                progressive=True,
            )
            temp_path.replace(destination)
        finally:
            temp_path.unlink(missing_ok=True)


def _action_actor(request: Request, submitted_name: Any = "") -> tuple[str, str, bool]:
    """Resolve an audit/display actor without trusting direct-IP client claims."""

    identity = request_identity(request, settings)
    if identity.verified and identity.username:
        return identity.username, identity.source, True
    username = normalise_username(_as_text(submitted_name))
    if username:
        return username, "client_claim_unverified", False
    return "", "anonymous", False


def _can_manage_team_default(request: Request) -> bool:
    identity = request_identity(request, settings)
    return bool(
        identity.verified
        and identity.username
        and database.access_role(identity.username) == "admin"
    )


def _admin_identity(request: Request):
    identity = request_identity(request, settings)
    if not (
        identity.verified
        and identity.username
        and database.access_role(identity.username) == "admin"
    ):
        raise _detail(403, "该操作仅限 Dashboard 管理员。")
    return identity


def _review_tag_catalog() -> tuple[dict[str, Any], ...]:
    """Return built-in tags plus shared scene tags from the database.

    Built-ins remain source-controlled, but a database row can override their
    label/hint/group or soft-delete them (same pattern as missing evidence).
    """

    merged: dict[str, dict[str, Any]] = {
        str(item["key"]): {
            **item,
            "builtin": True,
            "deleted": False,
        }
        for item in REVIEW_TAG_CATALOG
    }
    builtin_keys = set(merged)
    for row in database.list_review_tag_catalog(include_inactive=True):
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        item = {
            str(name): value
            for name, value in row.items()
            if str(name) != "active"
        }
        if "group_key" in item and "group" not in item:
            item["group"] = item.pop("group_key")
        item.setdefault("section", "scene")
        item.setdefault("group", "environment")
        item.setdefault("hint", "")
        item["builtin"] = key in builtin_keys
        item["deleted"] = not bool(row.get("active", 1))
        if key in merged:
            merged[key].update(item)
            merged[key]["builtin"] = True
        else:
            merged[key] = item
    return tuple(merged.values())


def _missing_evidence_catalog() -> tuple[dict[str, Any], ...]:
    """Return the merged catalog, including soft-deleted historical entries.

    Built-ins remain source-controlled, but a database row can override their
    label/hint or retire them.  Retired entries stay in the payload so old
    annotations remain readable; the Review form hides them unless selected
    by the current version.
    """

    merged: dict[str, dict[str, Any]] = {
        str(item["key"]): {
            **item,
            "builtin": True,
            "deleted": False,
        }
        for item in MISSING_EVIDENCE_CATALOG
    }
    builtin_keys = set(merged)
    for row in database.list_missing_evidence_catalog(include_inactive=True):
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        item = {
            str(name): value
            for name, value in row.items()
            if str(name) != "active"
        }
        item["builtin"] = key in builtin_keys
        item["deleted"] = not bool(row.get("active", 1))
        if key in merged:
            merged[key].update(item)
            merged[key]["builtin"] = True
        else:
            merged[key] = item
    return tuple(merged.values())


def _csv_filter_values(
    raw: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if raw is None:
        return ()
    parts = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    for part in parts:
        text = _as_text(part).strip()
        if text:
            values.append(text)
    return tuple(dict.fromkeys(values))


def resolve_review_exclusion_filter(value: str = "") -> tuple[str, bool | None]:
    """Normalize the analysis Issue-exclusion slice.

    ``all`` is deliberately the default: exclusion is a review dimension, not
    a data deletion rule.  The two explicit slices remain useful for auditing
    model-problem cases separately from Issues that were manually shielded.
    A few boolean aliases are accepted for bookmarked/API clients from the
    previous hard-filter release.
    """

    normalized = _as_text(value).strip().casefold() or "all"
    aliases = {
        "all": "all",
        "any": "all",
        "included": "included",
        "include": "included",
        "not_excluded": "included",
        "false": "included",
        "0": "included",
        "excluded": "excluded",
        "exclude": "excluded",
        "only_excluded": "excluded",
        "true": "excluded",
        "1": "excluded",
    }
    canonical = aliases.get(normalized)
    if canonical is None:
        raise _detail(
            400,
            "exclusion 仅支持 all、included 或 excluded。",
        )
    return canonical, {"all": None, "included": False, "excluded": True}[canonical]


def _parse_issue_id_filter(raw: str) -> list[str]:
    tokens = re.split(r"[\s,;|]+", _as_text(raw))
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        issue_id = token.strip()
        if not issue_id or issue_id in seen:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", issue_id):
            continue
        seen.add(issue_id)
        cleaned.append(issue_id)
        if len(cleaned) >= 2000:
            break
    return cleaned


def _case_filter_kwargs(
    *,
    search: str = "",
    gt_label: str = "",
    model_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    review_status: str = "",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
    exclusion: str = "",
    baselines: str = "",
    request: Request | None = None,
) -> dict[str, Any]:
    comparison_values = [
        value
        for value in _csv_filter_values(comparison)
        if value in COMPARISON_STATUSES and value != "all"
    ]
    if failure_only and comparison_values and comparison_values != ["mismatch"]:
        if comparison and set(comparison_values) != {"mismatch"}:
            raise _detail(400, "failure_only=true 与 comparison 参数冲突。")
    if failure_only and not comparison_values:
        comparison_values = ["mismatch"]
    if comparison_values and set(comparison_values) == {
        "match",
        "mismatch",
        "none",
    }:
        comparison_values = []
    comparison_status = ",".join(comparison_values) if comparison_values else "all"
    if comparison_status != "all" and not model_run_id:
        raise _detail(400, "筛选模型对比关系时必须选择 Model Run。")
    model_labels = [
        canonical_model_label(value) for value in _csv_filter_values(model_label)
    ]
    for label in model_labels:
        if label not in MODEL_LABELS:
            raise _detail(400, "model_label 不在支持的三分类或 Stage1 范围内。")
    if model_labels and not model_run_id:
        raise _detail(400, "按模型标注筛选时必须选择 Model Run。")
    gt_labels = _csv_filter_values(gt_label)
    for label in gt_labels:
        if label not in LABELS:
            raise _detail(400, "gt_label 不在三分类范围内。")
    review_statuses = _csv_filter_values(review_status)
    for status in review_statuses:
        if status not in REVIEW_STATUSES:
            raise _detail(400, "review_status 不在支持范围内。")
    exclusion_filter, is_excluded = resolve_review_exclusion_filter(exclusion)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "baseline_scope": scopes[0] if len(scopes) == 1 else "",
        "baseline_scopes": scopes,
        "search": search,
        "gt_label": ",".join(gt_labels),
        "model_label": ",".join(model_labels),
        "annotation_label": annotation_label,
        "annotation_author": annotation_author,
        # Case status is derived from effective expected output versus GT in
        # the router so historical Tag-only Reviews stay aligned with analysis.
        "review_statuses": tuple(review_statuses),
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": failure_only,
        "missing_evidence": missing_evidence,
        "issue_ids": _parse_issue_id_filter(issue_ids),
        "work_assignee": _as_text(work_assignee).strip(),
        "is_excluded": is_excluded,
        "exclusion": exclusion_filter,
    }


def _review_tag_payload(
    item: dict[str, Any], *, builtin: bool = False
) -> dict[str, Any]:
    payload = {
        **item,
        "builtin": bool(item.get("builtin", builtin)),
        "deleted": not bool(item.get("active", 1))
        if "active" in item
        else bool(item.get("deleted", False)),
    }
    payload.pop("active", None)
    payload.setdefault("section", "scene")
    payload.setdefault("group", payload.pop("group_key", "environment"))
    payload.setdefault("hint", "")
    return payload


def _validate_review_tag_input(
    body: dict[str, Any], *, default_group: str = "environment"
) -> tuple[str, str, str, str]:
    """Return (label, hint, group, section) for managed Issue-tag rows."""

    label = _as_text(body.get("label"))
    hint = _as_text(body.get("hint"))
    group = _as_text(body.get("group") or default_group)
    if not label:
        raise _detail(400, "场景标签标题不能为空。")
    if len(label) > 48 or re.search(r"[\x00-\x1f\x7f]", label):
        raise _detail(400, "场景标签标题长度或字符不合法。")
    if len(hint) > 160 or re.search(r"[\x00-\x1f\x7f]", hint):
        raise _detail(400, "场景标签说明长度或字符不合法。")
    section = REVIEW_TAG_MANAGED_GROUPS.get(group)
    if section is None:
        raise _detail(400, "场景标签分组不合法。")
    return label, hint, group, section


def _review_reason_analysis_payload(
    *,
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    annotation_author: str = "",
    review_status: str = "",
    gt_label: str = "",
    annotation_label: str = "",
    model_label: str = "",
    missing_evidence: str = "",
    theme: str = "",
    tag: str = "",
    scene_tag: str = "",
    trigger_tag: str = "",
    egress_tag: str = "",
    search: str = "",
    exclusion: str = "all",
    page: int = 1,
    page_size: int = 20,
    unbounded: bool = False,
    baselines: str = "",
    baseline_scopes: list[str] | None = None,
) -> dict[str, Any]:
    exclusion, is_excluded = resolve_review_exclusion_filter(exclusion)
    missing_evidence_catalog = _missing_evidence_catalog()
    evidence_catalog = {
        str(item["key"]): {
            "label": str(item["label"]),
            "description": str(item["hint"]),
        }
        for item in missing_evidence_catalog
    }
    # Free-text keyword themes are not part of the current Review contract.
    # Ignore the retired theme parameter so old bookmarked URLs remain usable.
    theme = ""
    comparison_values = [
        value
        for value in _csv_filter_values(comparison)
        if value in COMPARISON_STATUSES and value != "all"
    ]
    if failure_only and comparison_values and comparison_values != ["mismatch"]:
        if comparison and set(comparison_values) != {"mismatch"}:
            raise _detail(400, "failure_only=true 与 comparison 参数冲突。")
    if failure_only and not comparison_values:
        comparison_values = ["mismatch"]
    if comparison_values and set(comparison_values) == {
        "match",
        "mismatch",
        "none",
    }:
        comparison_values = []
    comparison_status = ",".join(comparison_values) if comparison_values else "all"
    authors = _csv_filter_values(annotation_author)
    statuses = _csv_filter_values(review_status)
    gt_labels = _csv_filter_values(gt_label)
    annotation_labels = _csv_filter_values(annotation_label)
    model_labels = [
        canonical_model_label(value) for value in _csv_filter_values(model_label)
    ]
    evidence_keys = _csv_filter_values(missing_evidence)
    for status in statuses:
        if status not in REVIEW_STATUSES:
            raise _detail(400, "review_status 不在支持范围内。")
    for label in gt_labels:
        if label not in LABELS:
            raise _detail(400, "gt_label 不在三分类范围内。")
    for label in annotation_labels:
        if label not in LABELS:
            raise _detail(400, "annotation_label 不在三分类范围内。")
    for label in model_labels:
        if label not in MODEL_LABELS:
            raise _detail(400, "model_label 不在支持的三分类或 Stage1 范围内。")
    if model_labels and not model_run_id:
        raise _detail(400, "按模型预测筛选时必须选择 Model Run。")
    for key in evidence_keys:
        if key not in evidence_catalog:
            raise _detail(400, "missing_evidence 不在稳定字段目录中。")
    tag_catalog = _review_tag_catalog()
    tag_by_key = {str(item["key"]): item for item in tag_catalog}
    scene_tags = _csv_filter_values(scene_tag)
    trigger_tags = _csv_filter_values(trigger_tag)
    egress_tags = _csv_filter_values(egress_tag)
    legacy_tags = _csv_filter_values(tag)
    for requested_tag in (*legacy_tags, *scene_tags, *trigger_tags, *egress_tags):
        if requested_tag not in tag_by_key:
            raise _detail(400, "场景 Tags 不在共享目录中。")
    for key in scene_tags:
        if tag_by_key[key].get("section") != "scene":
            raise _detail(400, "scene_tag 必须属于场景 Tags。")
    for key in trigger_tags:
        if tag_by_key[key].get("section") != "interaction_decision":
            raise _detail(400, "trigger_tag 必须属于触发判定 Tags。")
    for key in egress_tags:
        if tag_by_key[key].get("section") != "egress":
            raise _detail(400, "egress_tag 必须属于如何脱困 Tags。")
    if comparison_status != "all" and not model_run_id:
        raise _detail(400, "筛选模型对比关系时必须选择 Model Run。")

    selected_run: dict[str, Any] | None = None
    if model_run_id:
        selected_run = next(
            (
                run
                for run in database.list_model_runs(
                    baseline_scopes=baseline_scopes
                    or resolve_request_baseline_scopes(baselines)
                )
                if run["id"] == model_run_id
            ),
            None,
        )
        if selected_run is None:
            raise _detail(404, "Model Run 不存在。")

    normalized_search = _as_text(search)[:256]
    folded_search = normalized_search.casefold()
    search_aliases = tuple(
        str(item["key"])
        for item in (*_review_tag_catalog(), *missing_evidence_catalog)
        if folded_search
        and (
            folded_search in str(item["label"]).casefold()
            or str(item["label"]).casefold() in folded_search
        )
    )
    status_labels = {
        "待补充": "pending",
        "与 GT 一致": "reviewed",
        "GT 需复核": "needs_gt_review",
        "Pending": "pending",
        "Matches GT": "reviewed",
        "Needs GT review": "needs_gt_review",
    }
    search_statuses = tuple(
        status
        for label, status in status_labels.items()
        if folded_search
        and (
            folded_search in label.casefold()
            or label.casefold() in folded_search
        )
    )
    effective_statuses = tuple(statuses)
    status_filter_impossible = False
    if search_statuses:
        search_status_set = set(search_statuses)
        if effective_statuses:
            effective_statuses = tuple(
                status
                for status in effective_statuses
                if status in search_status_set
            )
            status_filter_impossible = not effective_statuses
        else:
            effective_statuses = tuple(dict.fromkeys(search_statuses))
    scopes = baseline_scopes or resolve_request_baseline_scopes(baselines)
    rows = []
    if not status_filter_impossible:
        rows = database.review_reason_rows(
            baseline_scopes=scopes,
            model_run_id=model_run_id,
            comparison_status=comparison_status,
            # Reason clustering is a read-only progress/analysis surface.
            # Pre-Run Review history remains useful human evidence when no
            # selected-Run Review exists for the Issue. The selected Run
            # always wins inside the DB join; a prior bound Review is then
            # reusable human evidence. Trail candidate generation keeps its
            # strict default and never receives this compatibility view.
            include_unbound_fallback=True,
            include_bound_history_fallback=True,
            # Keep the exclusion slice at the DB boundary so cards, charts,
            # detail rows, and all analysis exports agree.  ``None`` means
            # the default all-inclusive view.
            is_excluded=is_excluded,
            annotation_author=",".join(authors),
            # Historical persisted status/label fields predate expected output.
            # Apply both filters after read-time Tag inference below.
            review_status="",
            gt_label=",".join(gt_labels),
            annotation_label="",
            model_label=",".join(model_labels),
            missing_evidence=list(evidence_keys),
            tag_filters=legacy_tags,
            scene_tags=scene_tags,
            trigger_tags=trigger_tags,
            egress_tags=egress_tags,
            # Exact automatic-status searches are evaluated from the same
            # derived value as the dedicated filter instead of stale storage.
            search="" if search_statuses else normalized_search,
            search_aliases=() if search_statuses else search_aliases,
        )
    tag_catalog_for_analysis = {
        str(item["key"]): {
            "label": str(item["label"]),
            "description": str(item.get("hint") or item.get("description") or ""),
            "section": str(item.get("section") or ""),
            "group": str(item.get("group") or ""),
        }
        for item in tag_catalog
    }
    result = build_review_reason_analysis(
        rows,
        theme="",
        evidence_catalog=evidence_catalog,
        tag_catalog=tag_catalog_for_analysis,
        has_model_run=bool(model_run_id),
        include_reason_themes=False,
        is_excluded=is_excluded,
        review_statuses=effective_statuses,
        annotation_labels=annotation_labels,
        page=page,
        page_size=max(len(rows), 1) if unbounded else page_size,
        page_size_limit=None if unbounded else 200,
    )
    for item in result["items"]:
        issue_id = _as_text(item.get("issue_id"))
        review_params = [f"issue={quote(issue_id, safe='')}"]
        if model_run_id:
            review_params.append(f"run={quote(model_run_id, safe='')}")
        if comparison_status == "mismatch" and model_run_id:
            review_params.append("failure=1")
        item["voyager_issue_url"] = _voyager_issue_url(issue_id)
        item["review_url"] = _public_path(f"/review?{'&'.join(review_params)}")
    result["scope"] = {
        "baseline_scope": settings.baseline_scope,
        "model_run": (
            {
                "id": selected_run["id"],
                "name": selected_run["name"],
                "kind": selected_run["kind"],
                "prediction_count": selected_run["baseline_prediction_count"],
                "failure_count": selected_run["failure_count"],
            }
            if selected_run
            else None
        ),
        "comparison_status": comparison_status,
        "exclusion": exclusion,
        "failure_only": comparison_status == "mismatch",
        "review_binding": (
            "latest_annotation_per_issue_per_model_run"
            if model_run_id
            else "latest_annotation_per_issue_all_runs"
        ),
        "review_is_run_bound": bool(model_run_id),
    }
    result["filters"] = {
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "exclusion": exclusion,
        "failure_only": comparison_status == "mismatch",
        "annotation_author": list(authors),
        "review_status": list(statuses),
        "gt_label": list(gt_labels),
        "annotation_label": list(annotation_labels),
        "model_label": list(model_labels),
        "missing_evidence": list(evidence_keys),
        "theme": theme,
        "tag": list(legacy_tags),
        "scene_tag": list(scene_tags),
        "trigger_tag": list(trigger_tags),
        "egress_tag": list(egress_tags),
        "search": normalized_search,
    }
    return result


def _fetch_autotriage_snapshot(batch_ref: Any) -> dict[str, Any]:
    batch_id = normalise_batch_id(batch_ref)
    batch = autotriage_source.fetch_batch(batch_id)
    source_rows = autotriage_source.fetch_results(batch_id)
    safe_batch = _safe_autotriage_batch(batch)
    rows: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for source_row in source_rows:
        redacted_row = redact_sensitive_fields(source_row)
        normalized = normalize_model_row(redacted_row)
        explicit_success = source_row.get("success")
        row_failed = explicit_success is False or (
            isinstance(explicit_success, str)
            and explicit_success.strip().lower() in {"false", "0", "failed"}
        )
        if (
            row_failed
            or normalized is None
            or normalized.get("model_label") not in LABELS
        ):
            rejected += 1
            continue
        issue_id = _as_text(normalized.get("issue_id"))
        if issue_id in seen:
            raise AutoTriageSourceError(
                f"AutoTriage Batch {batch_id} 含重复 Issue：{issue_id}。"
            )
        seen.add(issue_id)
        normalized["raw"] = redacted_row
        rows.append(normalized)
    if not rows:
        raise AutoTriageSourceError(
            "该 AutoTriage Batch 没有可导入的三分类预测结果。"
        )

    def platform_count(field: str) -> int:
        try:
            count = int(batch.get(field) or 0)
        except (TypeError, ValueError):
            raise AutoTriageSourceError(
                f"AutoTriage Batch 的 {field} 非法。"
            )
        if count < 0:
            raise AutoTriageSourceError(
                f"AutoTriage Batch 的 {field} 不能为负数。"
            )
        return count

    declared_total = platform_count("total_count")
    completed_total = platform_count("completed_count")
    failed_total = platform_count("failed_count")
    platform_status = _as_text(batch.get("status")).lower()
    partial = bool(
        rejected
        or failed_total
        or platform_status not in {"completed", "succeeded"}
        or (declared_total and len(source_rows) != declared_total)
        or (declared_total and completed_total != declared_total)
        or (declared_total and len(rows) != declared_total)
    )
    fingerprint_rows = [
        {
            "issue_id": row["issue_id"],
            "trip_id": row["trip_id"],
            "model_label": row["model_label"],
            "model_reason": row["model_reason"],
            "model_confidence": row["model_confidence"],
            "model_extra": row["model_extra"],
        }
        for row in sorted(rows, key=lambda item: item["issue_id"])
    ]
    fingerprint = {
        "schema_version": "autotriage-snapshot-v1",
        "batch_id": batch_id,
        "batch": safe_batch,
        "predictions": fingerprint_rows,
        "source_result_count": len(source_rows),
        "rejected_result_count": rejected,
    }
    source_sha256 = hashlib.sha256(
        json.dumps(
            fingerprint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    coverage = {
        "declared_total": declared_total,
        "completed_total": completed_total,
        "failed_total": failed_total,
        "platform_status": platform_status,
        "source_result_count": len(source_rows),
        "accepted_result_count": len(rows),
        "rejected_result_count": rejected,
        "unique_issue_count": len(seen),
        "partial": partial,
    }
    return {
        "batch_id": batch_id,
        "batch": safe_batch,
        "rows": rows,
        "coverage": coverage,
        "source_sha256": source_sha256,
    }


def _normalise_review_image(content: bytes) -> tuple[bytes, str, str, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.seek(0)
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_REVIEW_ATTACHMENT_PIXELS:
                raise _detail(400, "截图尺寸非法或像素数超过 4000 万。")
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            image_format = (source.format or "").upper()
            output = io.BytesIO()
            if image_format == "PNG":
                if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="PNG", optimize=True)
                media_type, suffix = "image/png", ".png"
            elif image_format in {"JPEG", "JPG"}:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.save(output, format="JPEG", quality=92, optimize=True)
                media_type, suffix = "image/jpeg", ".jpg"
            elif image_format == "WEBP":
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="WEBP", quality=92, method=4)
                media_type, suffix = "image/webp", ".webp"
            else:
                raise _detail(400, "截图仅支持 PNG、JPEG 或 WebP。")
            normalized = output.getvalue()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise _detail(400, "截图无法解码或文件已损坏。")
    if not normalized or len(normalized) > MAX_REVIEW_ATTACHMENT_BYTES:
        raise _detail(413, "规范化后的单张截图不能超过 8 MB。")
    return normalized, media_type, suffix, width, height


async def _store_review_attachments(
    uploads: list[UploadFile],
) -> tuple[list[dict[str, Any]], list[Path]]:
    if len(uploads) > MAX_REVIEW_ATTACHMENTS:
        raise _detail(400, f"每次最多粘贴 {MAX_REVIEW_ATTACHMENTS} 张截图。")
    prepared: list[tuple[dict[str, Any], bytes]] = []
    raw_total_bytes = 0
    total_bytes = 0
    for upload in uploads:
        content = await upload.read(MAX_REVIEW_ATTACHMENT_BYTES + 1)
        if not content:
            raise _detail(400, "截图文件为空。")
        if len(content) > MAX_REVIEW_ATTACHMENT_BYTES:
            raise _detail(413, "单张截图不能超过 8 MB。")
        raw_total_bytes += len(content)
        if raw_total_bytes > MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES:
            raise _detail(413, "本次截图总大小不能超过 24 MB。")
        async with review_image_semaphore:
            normalized, media_type, suffix, width, height = await asyncio.to_thread(
                _normalise_review_image,
                content,
            )
        total_bytes += len(normalized)
        if total_bytes > MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES:
            raise _detail(413, "本次截图总大小不能超过 24 MB。")
        attachment_id = str(uuid.uuid4())
        stored_name = f"{attachment_id[:2]}/{attachment_id}{suffix}"
        prepared.append(
            (
                {
                    "id": attachment_id,
                    "original_name": _safe_filename(
                        upload.filename or f"clipboard{suffix}"
                    ),
                    "stored_name": stored_name,
                    "media_type": media_type,
                    "size_bytes": len(normalized),
                    "width": width,
                    "height": height,
                    "sha256": hashlib.sha256(normalized).hexdigest(),
                },
                normalized,
            )
        )

    return await asyncio.to_thread(
        _persist_review_attachments,
        prepared,
        total_bytes,
    )


def _persist_review_attachments(
    prepared: list[tuple[dict[str, Any], bytes]],
    total_bytes: int,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Persist normalized Review images outside the asyncio event loop."""

    root = settings.review_attachments_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (
        prepared
        and database.review_attachment_storage_bytes() + total_bytes
        > MAX_REVIEW_ATTACHMENT_STORAGE_BYTES
    ):
        raise _detail(507, "Review 截图已达到 20 GB 存储配额，请联系管理员清理或扩容。")
    if prepared and shutil.disk_usage(root).free < total_bytes + MIN_REVIEW_ATTACHMENT_DISK_FREE:
        raise _detail(507, "截图存储空间不足，请联系管理员。")
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        for record, content in prepared:
            stored_name = str(record["stored_name"])
            path = (settings.review_attachments_dir / stored_name).resolve()
            if root not in path.parents:
                raise _detail(400, "截图存储路径非法。")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            temp_path.write_bytes(content)
            temp_paths.append(temp_path)
            final_paths.append(path)
        for temp_path, final_path in zip(temp_paths, final_paths):
            temp_path.replace(final_path)
    except Exception:
        for path in [*temp_paths, *final_paths]:
            path.unlink(missing_ok=True)
        raise
    return [record for record, _ in prepared], final_paths


def _public_review_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": attachment["id"],
        "media_type": attachment["media_type"],
        "size_bytes": int(attachment["size_bytes"]),
        "width": int(attachment["width"]),
        "height": int(attachment["height"]),
        "created_at": attachment.get("created_at"),
        "url": _public_path(f"/api/review-attachments/{attachment['id']}"),
    }


def _normalise_review_tags(values: list[Any]) -> list[str]:
    if len(values) > 24:
        raise _detail(400, "每条 review 最多选择 24 个 tags。")
    catalog_keys = {str(item["key"]) for item in _review_tag_catalog()}
    normalized: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        if len(raw) > 48 or re.search(r"[\x00-\x1f\x7f]", raw):
            raise _detail(400, "tag 长度或字符不合法。")
        key = REVIEW_TAG_ALIASES.get(raw, raw)
        if key in catalog_keys:
            normalized.add(key)
        else:
            raise _detail(400, "tag 不在默认场景 Tags 目录中。")
    return [item["key"] for item in _review_tag_catalog() if item["key"] in normalized]


def _normalise_missing_evidence(values: list[Any]) -> list[str]:
    if len(values) > 24:
        raise _detail(400, "每条 review 最多选择 24 个缺失信息。")
    catalog_keys = {str(item["key"]) for item in _missing_evidence_catalog()}
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw or raw in seen:
            continue
        if len(raw) > 160 or re.search(r"[\x00-\x1f\x7f]", raw):
            raise _detail(400, "缺失信息字段长度或字符不合法。")
        # Legacy per-Review custom values remain readable and editable. New
        # values are opaque keys from the shared catalog above.
        if raw not in catalog_keys and not raw.startswith("custom:"):
            raise _detail(400, "缺失信息不在共享目录中。")
        seen.add(raw)
        normalized.append(raw)
    return normalized


def _normalise_review_excluded(value: Any) -> bool:
    """Parse the explicit Issue-level exclusion flag without truthiness traps."""

    if value is None or value is False or value == 0:
        return False
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"", "0", "false", "no", "否", "不排除"}:
            return False
        if normalized in {"1", "true", "yes", "是", "排除"}:
            return True
    raise _detail(400, "is_excluded 必须是布尔值。")


def _create_annotation_record(
    *,
    issue_id: str,
    request: Request,
    body: dict[str, Any],
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    is_excluded = _normalise_review_excluded(body.get("is_excluded", False))
    tags = body.get("tags") or []
    missing_evidence = body.get("missing_evidence") or []
    if not isinstance(tags, list):
        raise _detail(400, "tags 必须是数组。")
    if not isinstance(missing_evidence, list):
        raise _detail(400, "missing_evidence 必须是数组。")
    tags = _normalise_review_tags(tags)
    missing_evidence = _normalise_missing_evidence(missing_evidence)
    expected_output = _as_text(body.get("expected_output"))
    legacy_label = _as_text(body.get("label"))
    if expected_output and legacy_label and expected_output != legacy_label:
        raise _detail(400, "expected_output 与兼容字段 label 不一致。")
    try:
        expected_output = resolve_expected_output(
            expected_output or legacy_label,
            tags,
            _review_tag_catalog(),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    case = database.get_case(issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    review_status = derive_review_status(
        expected_output,
        case.get("gt_label"),
    )
    model_run_id = _as_text(body.get("model_run_id"))
    has_expected_previous = "expected_previous_annotation_id" in body
    expected_previous_annotation_id: int | None = None
    if has_expected_previous:
        raw_expected = body.get("expected_previous_annotation_id")
        if raw_expected in (None, "", 0, "0"):
            expected_previous_annotation_id = None
        else:
            try:
                expected_previous_annotation_id = int(raw_expected)
            except (TypeError, ValueError) as exc:
                raise _detail(400, "expected_previous_annotation_id 不合法。") from exc
            if expected_previous_annotation_id <= 0:
                raise _detail(400, "expected_previous_annotation_id 不合法。")
    author, author_source, author_verified = _action_actor(request, body.get("author"))
    note = _as_text(body.get("note"))
    try:
        mentions = extract_review_mentions(note)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    enabled_mentions = database.enabled_mention_recipients(mentions)
    unsupported_mentions = [
        username for username in mentions if username not in enabled_mentions
    ]
    if unsupported_mentions:
        raise _detail(
            400,
            "以下用户不在可 @ / DChat 通知人员目录中："
            + "、".join(f"@{item}" for item in unsupported_mentions),
        )
    recipients = notification_recipients(enabled_mentions, author=author)
    queued_recipients = (
        recipients
        if settings.dchat_notifications_enabled and author_verified
        else []
    )
    annotation_kwargs: dict[str, Any] = {
        "issue_id": issue_id,
        "model_run_id": model_run_id,
        # ``annotations.label`` is the existing compatible storage column for
        # the newly named expected output.  Keep it populated so older readers,
        # filters and history remain valid without a schema rewrite.
        "label": expected_output,
        "review_status": review_status,
        "is_excluded": is_excluded,
        "tags": tags,
        "missing_evidence": missing_evidence,
        "note": note,
        "author": author,
        "author_source": author_source,
        "author_verified": author_verified,
        "attachments": attachments,
        "mentions": mentions,
        "notification_recipients": queued_recipients,
    }
    if has_expected_previous:
        annotation_kwargs["expected_previous_annotation_id"] = expected_previous_annotation_id
    try:
        annotation = database.create_annotation(
            **annotation_kwargs,
        )
        annotation["notification"] = {
            "mentions": mentions,
            "queued": queued_recipients,
            "status": (
                "no_mentions" if not recipients
                else "queued" if queued_recipients
                else "disabled" if not settings.dchat_notifications_enabled
                else "unverified_identity"
            ),
        }
        return annotation
    except AnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))


def bootstrap_model_result() -> None:
    path = settings.bootstrap_model_json
    if not path or not path.is_file():
        return
    content = path.read_bytes()
    try:
        source_rows, metadata = parse_source_bytes(path.name, content)
        rows = [normalized for row in source_rows if (normalized := normalize_model_row(row))]
        if not rows:
            return
        experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
        name = _as_text(experiment.get("model_name")) or path.stem
        database.import_model_run(
            name=name,
            source_name=str(path),
            source_sha256=hashlib.sha256(content).hexdigest(),
            metadata=metadata,
            rows=rows,
            created_by="system",
            created_by_source="service_bootstrap",
            created_by_verified=False,
        )
    except Exception as exc:
        print(f"[ra_triage_dashboard] bootstrap model result skipped: {exc}", flush=True)


def bootstrap_baseline() -> dict[str, Any]:
    """Load every registry baseline; keep legacy runtime_state["baseline"] = default 0508."""

    return bootstrap_all_baselines()


def bootstrap_all_baselines() -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    memberships: list[tuple[str, str]] = []
    overlap_mode = str(getattr(settings, "baseline_overlap_mode", "fail_skip") or "fail_skip")
    for entry in baseline_registry.entries:
        loaded = load_baseline_entry(
            loader=entry.loader,
            path=entry.xlsx,
            dataset=entry.dataset,
        )
        item: dict[str, Any] = {
            "id": entry.id,
            "label": entry.label,
            "scope": entry.scope,
            "loader": entry.loader,
            "dataset": entry.dataset,
            "path": str(entry.xlsx),
            "source_rows": loaded.source_rows,
            "count": len(loaded.rows),
            "skipped_rows": loaded.skipped_rows,
            "message": loaded.message,
            "status": "ready" if loaded.rows else "unavailable",
            "default_selected": entry.default_selected,
            "media_provider": entry.media.provider,
        }
        if loaded.rows:
            # Overlap detection vs already-accepted memberships.
            proposed = [str(row.get("issue_id") or "").strip() for row in loaded.rows]
            existing_map: dict[str, str] = {issue: scope for issue, scope in memberships}
            conflicts = [
                issue for issue in proposed if issue and issue in existing_map
            ]
            if conflicts and overlap_mode != "last_writer":
                conflict_set = set(conflicts)
                kept = [
                    row
                    for row in loaded.rows
                    if str(row.get("issue_id") or "").strip() not in conflict_set
                ]
                item["conflict_count"] = len(conflicts)
                item["message"] = (
                    f"{loaded.message}；跳过与其它 baseline 重叠的 {len(conflicts)} 条"
                )
                if not kept:
                    item["status"] = "conflict"
                    item["count"] = 0
                    summaries.append(item)
                    continue
                loaded_rows = kept
                item["count"] = len(kept)
            else:
                loaded_rows = list(loaded.rows)
                item["conflict_count"] = len(conflicts)
            item["upsert"] = database.replace_baseline_scope(
                scope=entry.scope,
                rows=loaded_rows,
                source=entry.loader,
            )
            for row in loaded_rows:
                issue = str(row.get("issue_id") or "").strip()
                if issue:
                    memberships.append((issue, entry.scope))
        summaries.append(item)

    overlaps = detect_issue_scope_overlaps(memberships)
    runtime_state["baseline_conflicts"] = [
        {"issue_id": issue, "scopes": scopes} for issue, scopes in sorted(overlaps.items())
    ]
    runtime_state["baselines"] = summaries
    # Legacy primary baseline slot = default selected entry (usually 0508).
    default_ids = baseline_registry.default_ids()
    primary = next(
        (item for item in summaries if item["id"] in default_ids),
        summaries[0] if summaries else {
            "status": "unavailable",
            "message": "无 baseline registry 条目。",
            "count": 0,
            "scope": settings.baseline_scope,
            "dataset": settings.baseline_dataset,
        },
    )
    runtime_state["baseline"] = primary
    return primary


def resolve_request_baseline_ids(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    """Resolve short baseline ids from query/header; never trust raw scopes."""

    allowed = baseline_registry.allowed_ids()
    default = baseline_registry.default_ids()
    if not allowed:
        return ["0508"]
    candidate = raw
    if (candidate is None or candidate == "") and request is not None:
        candidate = request.query_params.get("baselines") or request.query_params.get(
            "baseline_scopes"
        )
    return normalize_baseline_ids(candidate, allowed=allowed, default=default)


def resolve_request_baseline_scopes(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    ids = resolve_request_baseline_ids(raw, request=request)
    scopes = ids_to_scopes(ids, baseline_registry)
    if not scopes:
        # Fail closed to default primary scope.
        entry = baseline_registry.by_id(baseline_registry.default_ids()[0]) if baseline_registry.entries else None
        return [entry.scope if entry else settings.baseline_scope]
    return scopes


def media_for_issue(issue_id: str, baseline_scope: str = "") -> Any:
    provider = media_registry.resolve_for_issue(issue_id, baseline_scope=baseline_scope)
    return provider or media_registry.for_baseline_id(baseline_registry.default_ids()[0])


def _infer_baseline_ids_from_scope_coverage(
    coverage: list[dict[str, Any]],
    *,
    dominant_ratio: float = 0.9,
) -> list[str]:
    """Map prediction-per-scope counts to short baseline ids for auto topbar select.

    Evaluation runs almost always target a single GT workset. Prefer the single
    dominant matched scope; fall back to every matched scope when mixed.
    """

    matched: list[tuple[str, int]] = []
    for item in coverage:
        scope = str(item.get("baseline_scope") or "").strip()
        count = int(item.get("prediction_count") or 0)
        if not scope or count <= 0:
            continue
        baseline_id = baseline_registry.scope_to_id(scope)
        if not baseline_id:
            continue
        matched.append((baseline_id, count))
    if not matched:
        return []
    # Merge duplicate ids if registry ever aliases (shouldn't).
    by_id: dict[str, int] = {}
    for baseline_id, count in matched:
        by_id[baseline_id] = by_id.get(baseline_id, 0) + count
    ordered = sorted(by_id.items(), key=lambda pair: (-pair[1], pair[0]))
    total = sum(count for _, count in ordered)
    if len(ordered) == 1:
        return [ordered[0][0]]
    top_id, top_count = ordered[0]
    if total > 0 and top_count / total >= dominant_ratio:
        return [top_id]
    return [baseline_id for baseline_id, _ in ordered]


def enrich_model_run_baseline_hint(
    run: dict[str, Any] | None,
    *,
    coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach per-scope coverage + inferred dataset ids for UI auto-select.

    Pass ``coverage`` when the caller already batched
    ``model_run_scope_coverage_map`` so list endpoints stay O(1) SQL.
    """

    if not isinstance(run, dict):
        return {}
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        return run
    if coverage is None:
        coverage = database.model_run_scope_coverage(run_id)
    by_id: list[dict[str, Any]] = []
    unmatched = 0
    for item in coverage:
        scope = str(item.get("baseline_scope") or "").strip()
        count = int(item.get("prediction_count") or 0)
        if not scope:
            unmatched += count
            continue
        baseline_id = baseline_registry.scope_to_id(scope) or ""
        by_id.append(
            {
                "id": baseline_id,
                "scope": scope,
                "label": (
                    baseline_registry.by_id(baseline_id).label
                    if baseline_id and baseline_registry.by_id(baseline_id)
                    else scope
                ),
                "prediction_count": count,
            }
        )
    inferred = _infer_baseline_ids_from_scope_coverage(coverage)
    payload = dict(run)
    payload["baseline_coverage"] = by_id
    payload["unmatched_prediction_count"] = unmatched
    payload["inferred_baseline_ids"] = inferred
    return payload


def configured_gt_sync_baseline_ids() -> list[str]:
    configured = tuple(settings.gt_sync_baseline_ids)
    if "*" in configured:
        return [entry.id for entry in baseline_registry.entries]
    return list(dict.fromkeys(configured))


def resolve_gt_sync_baseline_ids(
    raw: Any = None,
    *,
    strict: bool = False,
) -> list[str]:
    configured = configured_gt_sync_baseline_ids()
    if raw is None or raw == "":
        return configured
    values: list[str] = []
    source = raw if isinstance(raw, (list, tuple, set)) else [raw]
    for item in source:
        values.extend(
            part.strip()
            for part in str(item or "").split(",")
            if part.strip()
        )
    requested = list(dict.fromkeys(values))
    invalid = [
        baseline_id
        for baseline_id in requested
        if baseline_id not in configured
    ]
    if strict and invalid:
        raise ValueError(
            "GT 同步仅支持已配置数据集："
            + "、".join(configured)
            + "；不支持："
            + "、".join(invalid)
        )
    return [baseline_id for baseline_id in requested if baseline_id in configured]


def _gt_sync_item(baseline_id: str) -> dict[str, Any]:
    entry = baseline_registry.by_id(baseline_id)
    if entry is None:
        return {
            "status": "unavailable",
            "enabled": settings.gt_sync_enabled,
            "baseline_id": baseline_id,
            "baseline_label": baseline_id,
            "baseline_scope": "",
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
            "message": f"GT 同步 baseline {baseline_id} 不存在。",
        }
    persisted = database.gt_sync_status(entry.scope)
    running_by_scope = runtime_state.get("gt_sync") or {}
    running = running_by_scope.get(entry.scope) or {}
    if running.get("status") == "running":
        persisted = {**persisted, **running}
    return {
        **persisted,
        "enabled": settings.gt_sync_enabled,
        "baseline_id": entry.id,
        "baseline_label": entry.label,
        "baseline_scope": entry.scope,
        "interval_seconds": settings.gt_sync_interval_seconds,
        "source_view_id": settings.gt_sync_view_id,
        "source_field": TRAIL_GT_FIELD,
    }


def gt_sync_status(baseline_ids: Any = None) -> dict[str, Any]:
    configured = configured_gt_sync_baseline_ids()
    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    items = [_gt_sync_item(baseline_id) for baseline_id in requested]
    status_names = [str(item.get("status") or "not_started") for item in items]
    if not items:
        aggregate_status = "unavailable"
        message = "没有已配置的 GT 同步数据集。"
    elif any(status == "running" for status in status_names):
        aggregate_status = "running"
        message = "正在同步：" + "、".join(
            str(item.get("baseline_label") or item.get("baseline_id") or "")
            for item in items
            if item.get("status") == "running"
        )
    elif any(status in {"failed", "unavailable"} for status in status_names):
        aggregate_status = "failed"
        ready_count = sum(status == "ready" for status in status_names)
        failed_labels = "、".join(
            str(item.get("baseline_label") or item.get("baseline_id") or "")
            for item in items
            if item.get("status") in {"failed", "unavailable"}
        )
        message = f"{ready_count}/{len(items)} 个数据集同步成功；{failed_labels} 失败。"
    elif status_names and all(status == "ready" for status in status_names):
        aggregate_status = "ready"
        changed = sum(
            int(item.get("last_check_change_count") or 0) for item in items
        )
        message = f"{len(items)}/{len(items)} 个数据集 GT 已完整校验，本次更新 {changed} 条。"
    else:
        aggregate_status = "not_started"
        message = "尚未从 Trail 同步全部权威 GT。"

    payload: dict[str, Any] = dict(items[0]) if len(items) == 1 else {}
    payload.update(
        {
            "status": aggregate_status,
            "enabled": settings.gt_sync_enabled,
            "baseline_ids": requested,
            "configured_baseline_ids": configured,
            "baselines": items,
            "interval_seconds": settings.gt_sync_interval_seconds,
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
            "source_row_count": sum(
                int(item.get("source_row_count") or 0) for item in items
            ),
            "last_check_change_count": sum(
                int(item.get("last_check_change_count") or 0) for item in items
            ),
            "last_applied_change_count": sum(
                int(item.get("last_applied_change_count") or 0) for item in items
            ),
            "message": message,
        }
    )
    return payload


def _mark_authoritative_gt_sync_running(requested: list[str]) -> None:
    running_by_scope = runtime_state.setdefault("gt_sync", {})
    for baseline_id in requested:
        entry = baseline_registry.by_id(baseline_id)
        if entry is None:
            continue
        running_by_scope[entry.scope] = {
            "status": "running",
            "message": (
                f"正在从 Trail view {settings.gt_sync_view_id} 完整校验 "
                f"{entry.label} GT。"
            ),
            "baseline_id": entry.id,
            "baseline_label": entry.label,
            "baseline_scope": entry.scope,
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
        }


def reserve_authoritative_gt_sync(
    baseline_ids: Any = None,
) -> tuple[list[str], bool]:
    """Reserve the global worker before returning an asynchronous HTTP accept."""

    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    if not gt_sync_lock.acquire(blocking=False):
        return requested, False
    _mark_authoritative_gt_sync_running(requested)
    return requested, True


def sync_authoritative_gt(
    *,
    baseline_ids: Any = None,
    requested_by: str = "",
    identity_source: str = "service",
    identity_verified: bool = False,
    trigger: str = "manual",
    _lock_acquired: bool = False,
) -> dict[str, Any]:
    """Read complete fixed Trail snapshots and atomically update local GT."""

    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    if not _lock_acquired and not gt_sync_lock.acquire(blocking=False):
        return {
            **gt_sync_status(requested),
            "status": "running",
            "message": "已有权威 GT 同步任务在运行。",
        }
    try:
        running_by_scope = runtime_state.setdefault("gt_sync", {})
        _mark_authoritative_gt_sync_running(requested)
        for baseline_id in requested:
            entry = baseline_registry.by_id(baseline_id)
            if entry is None:
                continue
            try:
                issue_ids = database.baseline_issue_ids(scope=entry.scope)
                result = read_trail_gt_labels(
                    ra_root=settings.ra_auto_triage_root,
                    issue_ids=issue_ids,
                    view_id=settings.gt_sync_view_id,
                    chunk_size=settings.gt_sync_chunk_size,
                )
                if (
                    not result.complete
                    or result.returned_issues != result.queried_issues
                    or TRAIL_GT_FIELD not in result.fields_visible
                ):
                    database.record_gt_sync_failure(
                        scope=entry.scope,
                        error_text=result.message,
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
                else:
                    database.apply_gt_sync_snapshot(
                        scope=entry.scope,
                        rows=result.rows,
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
            except Exception as exc:
                logger.exception(
                    "authoritative GT sync failed for baseline %s", entry.id
                )
                try:
                    database.record_gt_sync_failure(
                        scope=entry.scope,
                        error_text=str(exc),
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
                except Exception:
                    logger.exception(
                        "failed to persist authoritative GT sync failure for %s",
                        entry.id,
                    )
            finally:
                running_by_scope.pop(entry.scope, None)
        return gt_sync_status(requested)
    finally:
        gt_sync_lock.release()


def sync_trail_model_fields(
    *,
    create_run: bool = False,
    requested_by: str = "",
    identity_source: str = "anonymous",
    identity_verified: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Inspect Trail fields and optionally create/reuse an immutable local snapshot.

    This function only calls the Trail query client.  Creating a snapshot writes
    local SQLite rows, but never writes Trail and never changes the shared
    default model run.
    """

    if not trail_sync_lock.acquire(blocking=False):
        return {
            **runtime_state["trail_sync"],
            "status": "running",
            "message": "已有 Trail 字段检查或快照任务在运行。",
        }
    action = "创建只读快照" if create_run else "检查字段"
    runtime_state["trail_sync"] = {
        "status": "running",
        "message": f"正在从 Trail view {settings.trail_view_id} 只读{action}。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
        "action": "create" if create_run else "preview",
    }
    try:
        issue_ids = database.baseline_issue_ids(
            baseline_scopes=ids_to_scopes(baseline_registry.default_ids(), baseline_registry)
            or [settings.baseline_scope]
        )
        result = read_trail_model_fields(
            ra_root=settings.ra_auto_triage_root,
            issue_ids=issue_ids,
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        state: dict[str, Any] = {
            "status": "unavailable",
            "message": result.message,
            "view_id": result.view_id,
            "queried_issues": result.queried_issues,
            "returned_issues": result.returned_issues,
            "fields_visible": list(result.fields_visible),
            "run_id": "",
            "complete": result.complete,
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        if not result.complete or result.returned_issues < result.queried_issues:
            state.update(
                {
                    "status": "failed",
                    "message": (
                        result.message
                        + (
                            f" 仅返回 {result.returned_issues} / {result.queried_issues} 个 baseline issue；"
                            if result.complete
                            else " "
                        )
                        + "为避免部分快照，未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        if TRAIL_RESULT_FIELD not in result.fields_visible:
            state["message"] = result.message + " 未创建 Run，团队默认 Run 未变化。"
            runtime_state["trail_sync"] = state
            return state
        normalized = [row for raw in result.rows if (row := normalize_model_row(raw))]
        # Trail snapshots participate in three-class evaluation, so only the
        # canonical labels are usable. Keep non-standard values out of the
        # snapshot rather than treating placeholders such as "nan" as labels.
        usable = [row for row in normalized if row["model_label"] in LABELS]
        if not usable:
            state.update(
                {
                    "status": "empty",
                    "message": (
                        result.message
                        + " 字段已出现，但当前 baseline 没有非空模型结果；未创建 Run。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        snapshot_rows = sorted(usable, key=lambda row: row["issue_id"])
        state.update(
            {
                "can_create": True,
                "usable_predictions": len(usable),
                "missing_predictions": max(result.queried_issues - len(usable), 0),
            }
        )
        if not create_run:
            state.update(
                {
                    "status": "preview_ready",
                    "message": (
                        result.message
                        + f" 检查完成：{len(usable)} / {result.queried_issues} 条可生成快照。"
                        + " 尚未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        payload = {
            "scope": settings.baseline_scope,
            "view_id": settings.trail_view_id,
            "fields": [TRAIL_RESULT_FIELD, TRAIL_INFO_FIELD],
            "rows": snapshot_rows,
        }
        source_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        run, duplicate = database.import_model_run(
            name=f"Trail view {settings.trail_view_id} · {TRAIL_RESULT_FIELD}",
            source_name=f"Trail view {settings.trail_view_id}",
            source_sha256=source_hash,
            metadata={
                "schema_version": "trail-fields-v1",
                "origin": "trail_readonly_snapshot",
                "baseline_scope": settings.baseline_scope,
                "view_id": settings.trail_view_id,
                "fields_visible": list(result.fields_visible),
                "queried_issues": result.queried_issues,
                "returned_issues": result.returned_issues,
                "usable_predictions": len(usable),
                "trigger": trigger,
            },
            rows=snapshot_rows,
            kind="trail_snapshot",
            make_default=False,
            created_by=requested_by,
            created_by_source=identity_source,
            created_by_verified=identity_verified,
        )
        state.update(
            {
                "status": "ready",
                "run_id": run["id"],
                "usable_predictions": len(usable),
                "duplicate": duplicate,
                "message": (
                    result.message
                    + (
                        f" 内容未变化，已复用现有只读快照（{len(usable)} 条）。"
                        if duplicate
                        else f" 已创建只读快照（{len(usable)} 条）。"
                    )
                    + " Trail、GT、人工复核和团队默认 Run 均未修改。"
                ),
            }
        )
        runtime_state["trail_sync"] = state
        return state
    except Exception as exc:
        state = {
            "status": "failed",
            "message": f"Trail 只读{action}失败: {exc}；未创建 Run，团队默认 Run 未变化。",
            "run_id": "",
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        runtime_state["trail_sync"] = state
        return state
    finally:
        trail_sync_lock.release()
