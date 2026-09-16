"""External Links HTTP helpers."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from ..sanitization import redact_sensitive_fields
from ..trail_sync import ares_playback_metadata
from ..runtime import settings
from .common import _as_text


_ARES_TASK_INFO_URL = (
    "https://voyager-hb.intra.xiaojukeji.com/proxy/get_task_info_for_ares/"
)
_disable_ra_version_cache: dict[str, tuple[float, int]] = {}
_disable_ra_version_cache_lock = threading.Lock()


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


def resolve_disable_ra_simulation_version(
    task_id: Any,
    *,
    cache_seconds: int = 300,
    timeout_seconds: float = 3.0,
    max_versions: int = 8,
) -> int:
    """Resolve the highest completed Ares retry for a disable-RA task.

    The Trail view exposes only the task id.  Ares accepts ``-1`` for its
    task-info lookup, but its page later filters events/results by the literal
    URL version, so a ``task_version=-1`` page can be empty.  Retry versions
    are contiguous; stop at the first version without a completed result.
    """

    value = _as_text(task_id)
    if not value or not value.isdigit():
        return 0
    now = time.monotonic()
    ttl = max(0, int(cache_seconds))
    with _disable_ra_version_cache_lock:
        cached = _disable_ra_version_cache.get(value)
        if ttl > 0 and cached and now - cached[0] < ttl:
            return cached[1]

    deadline = now + max(0.2, float(timeout_seconds))
    latest_completed = 0
    for version in range(max(1, min(int(max_versions), 32))):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        body = json.dumps(
            {
                "task_id": value,
                "version": version,
                "extra_fields": "result",
            }
        ).encode("utf-8")
        request = Request(
            _ARES_TASK_INFO_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(0.2, remaining)) as response:
                payload = json.loads(response.read(2 * 1024 * 1024))
        except Exception:
            break
        if not isinstance(payload, dict):
            break
        data = payload.get("data")
        if (
            payload.get("code") != 0
            or not isinstance(data, dict)
            or not data.get("result")
        ):
            break
        latest_completed = version

    if ttl > 0:
        with _disable_ra_version_cache_lock:
            _disable_ra_version_cache[value] = (time.monotonic(), latest_completed)
    return latest_completed


def _disable_ra_simulation_url(task_id: Any, task_version: Any = 0) -> str:
    """Build a read-only Ares Animation link from Trail's task id."""

    value = _as_text(task_id)
    if not value or not value.isdigit():
        return ""
    try:
        version = int(task_version)
    except (TypeError, ValueError, OverflowError):
        version = 0
    version = max(0, version)
    voyager = urlsplit(settings.voyager_issue_base_url)
    if voyager.scheme not in {"http", "https"} or not voyager.netloc:
        return ""
    query = urlencode({"task_id": value, "task_version": str(version)})
    return f"{voyager.scheme}://{voyager.netloc}/static/ares-animation/?{query}"


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
        "disable_ra_simulation_url": _disable_ra_simulation_url(
            metadata.get("te_task_id_disabe_ra"),
            metadata.get("te_task_version_disabe_ra", 0),
        ),
        "ra_task_id": _as_text(metadata.get("ra_id")),
        "disable_ra_simulation_task_id": _as_text(
            metadata.get("te_task_id_disabe_ra")
        ),
        "disable_ra_simulation_task_version": metadata.get(
            "te_task_version_disabe_ra", 0
        ),
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
        for key in (
            "ra_id",
            "ra_event",
            "te_task_id_disabe_ra",
            "te_task_version_disabe_ra",
        ):
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
