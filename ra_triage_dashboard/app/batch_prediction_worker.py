"""Isolated RA batch prediction and AutoTriage publishing worker.

The request is read from stdin. Model credentials are injected by the
dashboard parent only for prediction and are never accepted from the browser
or passed to the AutoTriage publishing worker.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


RESULT_PREFIX = "__RA_TRIAGE_BATCH_RESULT__"
EVENT_PREFIX = "__RA_TRIAGE_BATCH_EVENT__"
LABELS = {"误触发", "正确触发", "无需协助"}
ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._/@:+-]{1,160}$")
MAX_BATCH_ISSUES = 50
PUBLISH_RESULT_FIELDS = {
    "issue_id",
    "trip_id",
    "experiment_id",
    "ra_merge_result",
    "ra_result",
    "model_label",
    "model_reason",
    "model_confidence",
    "model_stuck",
    "model_extra",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "duration_sec",
    "success",
    "error",
}
PLATFORM_BATCH_FIELDS = {
    "id",
    "batch_name",
    "username",
    "status",
    "prompt_version",
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
_SENSITIVE_VALUES: set[str] = set()


def install_parent_death_guard() -> None:
    """Kill the whole isolated worker group if the dashboard parent dies."""
    if not sys.platform.startswith("linux") or os.getpgrp() != os.getpid():
        return
    parent_pid = os.getppid()

    def terminate_group(_signum: int, _frame: Any) -> None:
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        finally:
            os._exit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, terminate_group)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM) != 0:  # PR_SET_PDEATHSIG
        errno_value = ctypes.get_errno()
        raise OSError(errno_value, "无法设置 Batch worker parent-death signal")
    if os.getppid() != parent_pid:
        terminate_group(signal.SIGTERM, None)


def register_sensitive_values(*values: Any) -> None:
    for value in values:
        text = str(value or "").strip()
        if text:
            _SENSITIVE_VALUES.add(text)
            if text.lower().startswith("apikey:") and text[7:]:
                _SENSITIVE_VALUES.add(text[7:])
            parsed = urlsplit(text)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                _SENSITIVE_VALUES.add(parsed.netloc)


def redact_text(value: str) -> str:
    result = value
    for secret in sorted(_SENSITIVE_VALUES, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    return result


def scrub_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): scrub_object(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [scrub_object(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return scrub_object(item())
        except Exception:
            pass
    return redact_text(str(value))


def emit(payload: dict[str, Any]) -> None:
    print(
        RESULT_PREFIX + json.dumps(scrub_object(payload), ensure_ascii=False),
        flush=True,
    )


def emit_event(payload: dict[str, Any]) -> None:
    print(
        EVENT_PREFIX + json.dumps(scrub_object(payload), ensure_ascii=False),
        flush=True,
    )


def fail(message: str) -> int:
    emit({"success": False, "partial": False, "error": message})
    return 1


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalise_issue_ids(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("issue_ids 必须是非空数组。")
    if len(values) > MAX_BATCH_ISSUES:
        raise ValueError(f"单批最多允许 {MAX_BATCH_ISSUES} 个 issue。")
    issue_ids: list[str] = []
    for value in values:
        issue_id = str(value or "").strip()
        if not ISSUE_ID_RE.fullmatch(issue_id):
            raise ValueError(f"issue_id 格式非法: {issue_id or '<empty>'}")
        issue_ids.append(issue_id)
    duplicates = sorted(
        issue_id for issue_id, count in Counter(issue_ids).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"issue_ids 含重复值: {duplicates}")
    return issue_ids


def string_list(value: Any, *, fallback: str = "") -> list[str]:
    if value is None:
        values: list[Any] = []
    elif isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result and fallback.strip():
        result = [fallback.strip()]
    return result


def int_list(value: Any, *, allow_none: bool = False) -> list[int] | None:
    if value is None and allow_none:
        return None
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        values: list[Any] = [part.strip() for part in str(value).split(",")]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return [int(item) for item in values if str(item).strip()]


def pair_of_ints(value: Any, field: str) -> tuple[int, int]:
    values = int_list(value)
    if values is None or len(values) != 2:
        raise ValueError(f"默认模型 {field} 必须包含两个整数。")
    return values[0], values[1]


def normalise_experiment_types(experiment: Any) -> None:
    camera_topic = str(getattr(experiment, "camera_topic", "") or "").strip()
    experiment.camera_topics = string_list(
        getattr(experiment, "camera_topics", None),
        fallback=camera_topic,
    )
    if not experiment.camera_topics:
        raise ValueError("默认模型未配置 camera_topics。")
    experiment.camera_topic = camera_topic or experiment.camera_topics[0]
    experiment.frame_offsets_ms = int_list(experiment.frame_offsets_ms) or []
    if not experiment.frame_offsets_ms:
        raise ValueError("默认模型未配置 frame_offsets_ms。")
    experiment.time_window_offsets_ms = int_list(
        experiment.time_window_offsets_ms,
        allow_none=True,
    )
    experiment.gateway_window_ms = pair_of_ints(
        experiment.gateway_window_ms, "gateway_window_ms"
    )
    experiment.pose_yielding_window_ms = pair_of_ints(
        experiment.pose_yielding_window_ms, "pose_yielding_window_ms"
    )


def prompt_sha256(experiment: Any) -> str:
    supplied = str(getattr(experiment, "prompt_template_sha256", "") or "").strip()
    if supplied:
        return supplied
    template = str(getattr(experiment, "prompt_template", "") or "")
    if not template:
        try:
            from vlm.prompts import get_template

            template = get_template(str(experiment.prompt_version or ""))
        except Exception:
            template = ""
    return hashlib.sha256(template.encode("utf-8")).hexdigest() if template else ""


def load_default_experiment():
    from vlm.experiment_loader import load_experiment_for_args

    args = argparse.Namespace(
        experiment=None,
        experiment_id=None,
        experiment_revision_id=None,
        allow_stale_experiment_cache=False,
        prompt_version=None,
        model=None,
        provider=None,
        base_url=None,
        api_key=None,
        use_bev_animation=False,
        use_ra_options=False,
        time_window_offsets_ms=None,
        bev_mode=None,
        bev_animation_manifest=None,
        bev_frame_offsets_ms=None,
        frame_offsets_ms=None,
        temperature=0.6,
        max_tokens=512,
        description=None,
        tags=None,
        limit=None,
    )
    loaded = load_experiment_for_args(args)
    experiment = loaded.experiment
    normalise_experiment_types(experiment)
    register_sensitive_values(
        getattr(experiment, "api_key", ""),
        getattr(experiment, "base_url", ""),
    )
    # Ares remains review-only even if a future server default enables it.
    experiment.use_bev_animation = False
    experiment.bev_mode = "disabled"
    experiment.bev_animation_manifest = ""
    experiment.bev_frame_offsets_ms = []
    experiment.use_ares_capture = False
    experiment.ares_capture_manifest = ""
    experiment.ares_capture_on_miss = False
    # Freeze the materialised server default.  A child worker may only refill
    # credentials; it must never merge global input flags and re-enable Ares.
    experiment.config_merge_mode = "credentials_only"
    return experiment, loaded.source


def apply_gateway_model_metadata(experiment: Any, model_id: Any) -> str:
    model_id = str(model_id or "").strip()
    if not MODEL_ID_RE.fullmatch(model_id):
        raise ValueError("Batch worker model_id 格式非法。")
    experiment.model_name = model_id
    experiment.provider = "kylin"
    experiment.model_profile = ""
    # The selected gateway model is fully materialised. Refuse any merge which
    # could bring the old default model or review-only Ares inputs back.
    experiment.config_merge_mode = "none"
    experiment.use_bev_animation = False
    experiment.bev_mode = "disabled"
    experiment.bev_animation_manifest = ""
    experiment.bev_frame_offsets_ms = []
    experiment.use_ares_capture = False
    experiment.ares_capture_manifest = ""
    experiment.ares_capture_on_miss = False
    return "dashboard_ra_model_gateway"


def apply_gateway_model(experiment: Any, request: dict[str, Any]) -> str:
    source = apply_gateway_model_metadata(experiment, request.get("model_id"))
    gateway = request.pop("_model_gateway", None)
    if not isinstance(gateway, dict):
        raise ValueError("Batch worker 缺少模型网关配置。")
    provider = str(gateway.pop("provider", "") or "").strip()
    chat_url = str(gateway.pop("chat_url", "") or "").strip()
    api_key = str(gateway.pop("api_key", "") or "").strip()
    gateway.clear()
    parsed = urlsplit(chat_url)
    host = (parsed.hostname or "").lower()
    if (
        provider != "kylin"
        or parsed.scheme not in {"http", "https"}
        or host != "ra-model.intra.xiaojukeji.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1/chat/completions"
        or not api_key
    ):
        raise ValueError("Batch worker 模型网关环境配置非法。")
    auth_value = api_key if api_key.lower().startswith("apikey:") else f"apikey:{api_key}"
    register_sensitive_values(api_key, auth_value, chat_url)
    experiment.provider = provider
    experiment.base_url = chat_url
    experiment.api_key = auth_value
    return source


def safe_experiment_config(experiment: Any, source: str) -> dict[str, Any]:
    return {
        "model_name": str(experiment.model_name or ""),
        "provider": str(getattr(experiment, "provider", "") or ""),
        "model_profile": str(getattr(experiment, "model_profile", "") or ""),
        "prompt_version": str(experiment.prompt_version or ""),
        "prompt_sha256": prompt_sha256(experiment),
        "experiment_source": str(source or ""),
        "config_merge_mode": str(experiment.config_merge_mode or ""),
        "platform_experiment_id": getattr(experiment, "platform_experiment_id", None),
        "platform_revision_id": getattr(experiment, "platform_revision_id", None),
        "frame_offsets_ms": int_list(experiment.frame_offsets_ms) or [],
        "gateway_window_ms": list(experiment.gateway_window_ms),
        "pose_yielding_window_ms": list(experiment.pose_yielding_window_ms),
        "time_window_offsets_ms": int_list(
            experiment.time_window_offsets_ms, allow_none=True
        ),
        "camera_topic": str(experiment.camera_topic or ""),
        "camera_topics": string_list(experiment.camera_topics),
        "use_ra_event": bool(experiment.use_ra_event),
        "strip_ra_cmd": bool(getattr(experiment, "strip_ra_cmd", False)),
        "use_ra_options": bool(experiment.use_ra_options),
        "use_trajectory_summary": bool(
            getattr(experiment, "use_trajectory_summary", False)
        ),
        "stitch_front_views": bool(
            getattr(experiment, "stitch_front_views", False)
        ),
        "compress_quality": int(getattr(experiment, "compress_quality", 65)),
        "compress_max_dimension": int(
            getattr(experiment, "compress_max_dimension", 1280)
        ),
        "use_bev_animation": False,
        "use_ares_capture": False,
        "max_tokens": int(experiment.max_tokens),
        "temperature": float(experiment.temperature),
        "top_p": float(experiment.top_p),
        "top_k": int(experiment.top_k),
    }


def repo_commit(ra_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ra_root,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def load_tasks(issue_ids: list[str]):
    from utils.config import config
    from utils.get_ra_issue_utils import get_self_issue
    from vlm.scripts.internal.models import ProcessingTask
    from vlm.trigger_time import resolve_request_timestamp

    view_id = int(config.get("vlm_triage.default_view_id", 1000) or 1000)
    frame = get_self_issue(
        additional_conditions=[
            {"attr_id": "issue_id", "val": issue_ids, "operator": "in"}
        ],
        view_id=view_id,
        size=max(200, len(issue_ids)),
    )
    if frame.empty:
        raise ValueError("Voyager Issue 查询为空。")
    if "issue_id" not in frame.columns or "trip_id" not in frame.columns:
        raise ValueError("Voyager Issue 响应缺少 issue_id 或 trip_id。")
    requested = set(issue_ids)
    returned_ids = [
        str(value or "").strip() for value in frame["issue_id"].tolist()
    ]
    duplicates = sorted(
        issue_id
        for issue_id, count in Counter(returned_ids).items()
        if issue_id and count > 1
    )
    if duplicates:
        raise ValueError(f"Voyager Issue 返回重复 issue: {duplicates}")
    missing = sorted(requested - set(returned_ids))
    extras = sorted(set(returned_ids) - requested)
    if missing or extras:
        raise ValueError(
            f"Voyager Issue 返回集合不一致：缺少 {missing or '无'}，"
            f"额外 {extras or '无'}。"
        )
    rows = {
        str(row["issue_id"]): row.to_dict()
        for _, row in frame.iterrows()
        if str(row.get("issue_id") or "") in requested
    }

    tasks = []
    for ordinal, issue_id in enumerate(issue_ids):
        row = rows[issue_id]
        request_timestamp, timestamp_source = resolve_request_timestamp(row)
        if request_timestamp is None:
            raise ValueError(f"{issue_id} 缺少有效触发时间。")
        trip_id = str(row.get("trip_id") or "").strip()
        if not trip_id:
            raise ValueError(f"{issue_id} 缺少 trip_id。")
        row["_dashboard_timestamp_source"] = str(timestamp_source or "")
        tasks.append(
            ProcessingTask(
                idx=ordinal,
                issue_id=issue_id,
                trip_id=trip_id,
                request_ts=int(request_timestamp),
                row_data=row,
            )
        )
    return tasks, view_id


def inspect_default(ra_root: Path) -> int:
    """Validate the server-owned default model without running inference."""
    from vlm.vision_client import ensure_vision_credentials

    experiment, source = load_default_experiment()
    model_base_url, model_api_key = ensure_vision_credentials(experiment)
    register_sensitive_values(model_base_url, model_api_key)
    safe_config = safe_experiment_config(experiment, source)
    emit(
        {
            "success": True,
            "status": "ready",
            "model_name": safe_config["model_name"],
            "prompt_version": safe_config["prompt_version"],
            "experiment_source": safe_config["experiment_source"],
            "config_sha256": canonical_hash(safe_config),
            "safe_experiment": safe_config,
            "ra_repo_commit": repo_commit(ra_root),
            "ares_bev_input": False,
            "bag_cache_read_only": os.environ.get(
                "BAG_CACHE_READ_ONLY", "true"
            ).lower()
            == "true",
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
        }
    )
    return 0


def predict(request: dict[str, Any], ra_root: Path) -> int:
    from core.batch_engine import run_sliding_window
    from utils.config import config
    from vlm.vision_client import ensure_vision_credentials
    from vlm.scripts.internal import (
        ProcessingResult,
        RateLimiter,
        experiment_to_worker_dict,
        process_single_issue,
    )
    from vlm.scripts.internal.utils import clean_for_json

    issue_ids = normalise_issue_ids(request.get("issue_ids"))
    experiment, source = load_default_experiment()
    source = apply_gateway_model(experiment, request)
    model_base_url, model_api_key = ensure_vision_credentials(experiment)
    register_sensitive_values(model_base_url, model_api_key)
    safe_config = safe_experiment_config(experiment, source)
    config_sha256 = canonical_hash(safe_config)
    tasks, view_id = load_tasks(issue_ids)
    worker_experiment = experiment_to_worker_dict(experiment)
    # Verify the exact payload reconstructed by ProcessPool children.  This is
    # intentionally stricter than checking the parent Experiment alone.
    from vlm import Experiment

    reconstructed = Experiment(**worker_experiment)
    if (
        reconstructed.use_bev_animation
        or getattr(reconstructed, "use_ares_capture", False)
        or reconstructed.bev_mode != "disabled"
    ):
        raise ValueError("Batch 模型输入策略校验失败：Ares/BEV 被重新启用。")
    if (
        str(reconstructed.model_name or "") != str(request.get("model_id") or "")
        or str(reconstructed.provider or "") != "kylin"
        or str(reconstructed.config_merge_mode or "") != "none"
        or not str(reconstructed.base_url or "")
        or not str(reconstructed.api_key or "")
    ):
        raise ValueError("Batch 模型网关配置未完整传递到子进程。")

    rate_limiter = RateLimiter(
        rpm_limit=int(config.get("vlm_triage.rpm_limit", 500) or 500),
        tpm_limit=int(config.get("vlm_triage.tpm_limit", 200000) or 200000),
        tokens_per_request=int(
            config.get("vlm_triage.tokens_per_request", 10000) or 10000
        ),
    )

    def error_factory(task, message: str):
        row = task.row_data or {}
        return ProcessingResult(
            idx=task.idx,
            issue_id=task.issue_id,
            result_data={
                "issue_id": task.issue_id,
                "trip_id": task.trip_id,
                "experiment_id": experiment.experiment_id,
                "ra_merge_result": row.get("ra_merge_result", ""),
                "ra_result": row.get("ra_result", ""),
                "success": False,
                "error": message,
            },
        )

    results_by_index = run_sliding_window(
        tasks=tasks,
        worker_fn=process_single_issue,
        experiment_dict=worker_experiment,
        rate_limiter=rate_limiter,
        max_workers=min(
            4, max(1, int(config.get("vlm_triage.max_workers", 4) or 4))
        ),
        task_timeout_sec=int(
            config.get("vlm_triage.task_timeout_sec", 1000) or 1000
        ),
        error_factory=error_factory,
    )
    results: list[dict[str, Any]] = []
    for task in tasks:
        processed = results_by_index.get(task.idx)
        if processed is None:
            processed = error_factory(task, "worker 未返回结果。")
        results.append(scrub_object(clean_for_json(processed.result_data)))

    success_count = sum(
        1
        for result in results
        if result.get("success") and result.get("model_label") in LABELS
    )
    failed_count = len(results) - success_count
    if failed_count == 0:
        status = "succeeded"
    elif success_count:
        status = "partial"
    else:
        status = "failed"
    emit(
        {
            "success": failed_count == 0,
            "partial": status == "partial",
            "status": status,
            "model_name": safe_config["model_name"],
            "requested_model_id": str(request.get("requested_model_id") or ""),
            "catalog_sha256": str(request.get("catalog_sha256") or ""),
            "prompt_version": safe_config["prompt_version"],
            "experiment_source": safe_config["experiment_source"],
            "config_sha256": config_sha256,
            "safe_experiment": safe_config,
            "ra_repo_commit": repo_commit(ra_root),
            "trail_view_id": view_id,
            "requested_count": len(issue_ids),
            "completed_count": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "ares_bev_input": False,
            "bag_cache_read_only": os.environ.get(
                "BAG_CACHE_READ_ONLY", "false"
            ).lower()
            == "true",
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
            "results": results,
        }
    )
    return 0 if failed_count == 0 else 1


def normalise_record_base_url(value: Any) -> str:
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "").lower()
        != "auto-triage.intra.xiaojukeji.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/ra/model_triage/records"
    ):
        raise ValueError("AutoTriage records 地址配置非法。")
    return base_url


def sanitise_publish_results(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise ValueError("没有可推送的 Batch 结果。")
    if len(values) > MAX_BATCH_ISSUES:
        raise ValueError(f"单批最多允许 {MAX_BATCH_ISSUES} 个结果。")

    results: list[dict[str, Any]] = []
    issue_ids: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Batch 结果必须是对象数组。")
        issue_id = str(value.get("issue_id") or "").strip()
        if not ISSUE_ID_RE.fullmatch(issue_id):
            raise ValueError(f"结果 issue_id 格式非法: {issue_id or '<empty>'}")
        trip_id = str(value.get("trip_id") or "").strip()
        if not trip_id:
            raise ValueError(f"{issue_id} 的结果缺少 trip_id。")

        result = {
            key: scrub_object(value.get(key))
            for key in PUBLISH_RESULT_FIELDS
            if key in value
        }
        result["issue_id"] = issue_id
        result["trip_id"] = trip_id
        label = str(result.get("model_label") or "").strip()
        inference_ok = bool(result.get("success")) and label in LABELS
        if result.get("success") and not inference_ok:
            prior_error = str(result.get("error") or "").strip()
            result["error"] = (
                f"{prior_error}; 模型未返回合法三分类标签。".strip("; ")
            )
        result["success"] = inference_ok
        results.append(result)
        issue_ids.append(issue_id)

    duplicates = sorted(
        issue_id for issue_id, count in Counter(issue_ids).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"Batch 结果含重复 issue: {duplicates}")
    return results


def platform_get_data(client: Any, path: str, expected_type: type) -> Any:
    url = f"{client.base_url.rstrip('/')}{path}"
    response = client._get_session().get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError("平台 readback 返回失败状态。")
    data = payload.get("data")
    if not isinstance(data, expected_type):
        raise ValueError(f"平台 readback data 不是 {expected_type.__name__}。")
    return data


def fetch_platform_readback(
    client: Any,
    batch_id: str,
    expected_issue_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    batch: dict[str, Any] = {}
    errors: list[str] = []
    for attempt in range(6):
        errors = []
        try:
            rows = platform_get_data(
                client,
                f"/api/v1/model_triage/batches/{batch_id}/results/",
                list,
            )
        except Exception as exc:
            errors.append(f"results: {exc}")
        try:
            batch = platform_get_data(
                client,
                f"/api/v1/model_triage/batches/{batch_id}/",
                dict,
            )
        except Exception as exc:
            errors.append(f"batch: {exc}")

        returned = {
            str(row.get("issue_id") or "").strip()
            for row in rows
            if isinstance(row, dict)
        }
        if (
            not errors
            and expected_issue_ids.issubset(returned)
            and str(batch.get("status") or "") in {"completed", "abnormal", "failed"}
        ):
            return rows, batch
        if attempt < 5:
            time.sleep(1)
    if errors and not rows and not batch:
        raise ValueError("; ".join(errors))
    return rows, batch


def safe_platform_batch(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: scrub_object(value.get(key))
        for key in PLATFORM_BATCH_FIELDS
        if key in value
    }


def publish(request: dict[str, Any]) -> int:
    from vlm.scripts.internal import RaToolsClient

    experiment, source = load_default_experiment()
    source = apply_gateway_model_metadata(experiment, request.get("model_id"))
    safe_config = safe_experiment_config(experiment, source)
    config_sha256 = canonical_hash(safe_config)
    expected_hash = str(request.get("config_sha256") or "").strip().lower()
    if not expected_hash or expected_hash != config_sha256:
        return fail("开发机默认模型配置已变化；请重新创建 Batch 预测后再推送。")

    results = sanitise_publish_results(request.get("results"))
    record_base_url = normalise_record_base_url(request.get("record_base_url"))
    client = RaToolsClient()
    register_sensitive_values(client.base_url)
    if not client.enabled:
        return fail("AutoTriage 平台推送未启用。")
    if not client.sso_username:
        return fail("缺少 AutoTriage 写入身份；未创建平台 Batch。")
    experiment.author = client.sso_username
    batch_id = client.create_batch(experiment, len(results))
    if batch_id is None:
        return fail("创建 AutoTriage Batch 失败；未发送模型结果。")
    batch_id = str(batch_id)
    if not batch_id.isdigit():
        return fail("AutoTriage 返回了非法 Batch ID；未发送模型结果。")
    record_url = f"{record_base_url}/{batch_id}?tab=results"
    emit_event(
        {
            "event": "autotriage_batch_created",
            "batch_id": batch_id,
            "record_url": record_url,
            "writer": client.sso_username,
        }
    )

    push_accepted_issue_ids: list[str] = []
    push_rejected_issue_ids: list[str] = []
    for result in results:
        issue_id = str(result.get("issue_id") or "")
        try:
            accepted = client.push_result(batch_id, result)
        except Exception:
            accepted = False
        if accepted:
            push_accepted_issue_ids.append(issue_id)
        else:
            push_rejected_issue_ids.append(issue_id)

    try:
        platform_stats = client.finish_batch(batch_id)
    except Exception:
        platform_stats = None

    expected_issue_ids = {str(row["issue_id"]) for row in results}
    try:
        platform_results, platform_batch = fetch_platform_readback(
            client,
            batch_id,
            expected_issue_ids,
        )
    except Exception as exc:
        platform_results = []
        platform_batch = {}
        platform_error = str(exc)
    else:
        platform_error = ""

    platform_issue_ids = {
        str(row.get("issue_id") or "").strip()
        for row in platform_results
        if isinstance(row, dict) and str(row.get("issue_id") or "").strip()
    }
    missing_issue_ids = sorted(expected_issue_ids - platform_issue_ids)
    unexpected_issue_ids = sorted(platform_issue_ids - expected_issue_ids)
    verified_issue_ids = sorted(platform_issue_ids & expected_issue_ids)
    batch_status = str(platform_batch.get("status") or "")
    success = (
        not missing_issue_ids
        and not unexpected_issue_ids
        and platform_stats is not None
        and batch_status == "completed"
    )
    if success:
        status = "succeeded"
    elif verified_issue_ids or push_accepted_issue_ids:
        status = "partial"
    else:
        status = "failed"

    error_parts: list[str] = []
    if platform_error:
        error_parts.append(platform_error)
    if platform_stats is None:
        error_parts.append("AutoTriage Batch finish 未返回统计。")
    if push_rejected_issue_ids:
        error_parts.append(
            f"push 未确认: {sorted(push_rejected_issue_ids)}"
        )
    if missing_issue_ids:
        error_parts.append(f"readback 缺少: {missing_issue_ids}")
    if unexpected_issue_ids:
        error_parts.append(f"readback 出现额外 issue: {unexpected_issue_ids}")
    if batch_status and batch_status != "completed":
        error_parts.append(f"平台 Batch 状态: {batch_status}")

    emit(
        {
            "success": success,
            "partial": status == "partial",
            "status": status,
            "model_name": safe_config["model_name"],
            "prompt_version": safe_config["prompt_version"],
            "platform_batch_id": batch_id,
            "record_url": record_url,
            "records_url": record_url,
            "writer": client.sso_username,
            "requested_count": len(results),
            "completed_count": len(verified_issue_ids),
            "success_count": len(verified_issue_ids),
            "failed_count": len(missing_issue_ids),
            "pushed_count": len(push_accepted_issue_ids),
            "push_accepted_count": len(push_accepted_issue_ids),
            "push_rejected_issue_ids": sorted(push_rejected_issue_ids),
            "failed_issue_ids": missing_issue_ids,
            "published_issue_ids": verified_issue_ids,
            "unexpected_issue_ids": unexpected_issue_ids,
            "platform_result_count": len(platform_results),
            "platform_stats": scrub_object(platform_stats or {}),
            "platform_batch": safe_platform_batch(platform_batch),
            "error": "; ".join(error_parts),
        }
    )
    return 0 if success else 1


def main() -> int:
    install_parent_death_guard()
    try:
        request = json.loads(sys.stdin.read())
    except (TypeError, ValueError):
        return fail("Batch worker 需要 JSON stdin。")
    if not isinstance(request, dict):
        return fail("Batch worker 请求必须是对象。")

    action = str(request.get("action") or "").strip()
    if action == "predict":
        try:
            request["issue_ids"] = normalise_issue_ids(request.get("issue_ids"))
        except ValueError as exc:
            return fail(str(exc))

    ra_root_value = os.environ.get("RA_AUTO_TRIAGE_ROOT", "").strip()
    if not ra_root_value:
        return fail("RA_AUTO_TRIAGE_ROOT 未配置。")
    ra_root = Path(ra_root_value).expanduser().resolve()
    if not (ra_root / "vlm").is_dir():
        return fail("RA_AUTO_TRIAGE_ROOT 无效。")

    if action == "predict":
        bag_path_value = os.environ.get("BAG_PATH", "").strip()
        if not bag_path_value:
            return fail("Batch 预测缺少独立 BAG_PATH，拒绝使用 RA 仓库共享缓存。")
        bag_path = Path(bag_path_value).expanduser().resolve()
        if (
            bag_path == ra_root
            or ra_root in bag_path.parents
            or bag_path in ra_root.parents
        ):
            return fail("Batch BAG_PATH 必须与 RA_AUTO_TRIAGE_ROOT 完全隔离。")
    os.environ.setdefault("BAG_CACHE_READ_ONLY", "true")
    os.environ["RA_TOOLS_ENABLED"] = "true" if action == "publish" else "false"
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ[name] = ""
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"
    if str(ra_root) not in sys.path:
        sys.path.insert(0, str(ra_root))

    try:
        if action == "inspect":
            return inspect_default(ra_root)
        if action == "predict":
            return predict(request, ra_root)
        if action == "publish":
            return publish(request)
        return fail("未知 Batch worker action。")
    except Exception as exc:
        print(redact_text(traceback.format_exc()), file=sys.stderr, flush=True)
        return fail(f"Batch worker 失败: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
