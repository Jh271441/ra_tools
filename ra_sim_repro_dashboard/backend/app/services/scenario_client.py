from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ScenarioClient:
    """Queries source scenarios by label combinations from Trail Scenario API."""

    def query_label_set(self, labels: list[str]) -> list[dict[str, Any]]:
        clean_labels = [str(label).strip() for label in labels if str(label).strip()]
        if not clean_labels:
            return []
        if not settings.scenario_app_id or not settings.scenario_app_token:
            raise RuntimeError(
                "Scenario API is not configured. Set SCENARIO_APP_ID/SCENARIO_APP_TOKEN "
                "or TRAIL_APP_ID/TRAIL_APP_TOKEN."
            )
        first = self._query_page(clean_labels, page=1)
        data = first.get("data") or {}
        items = _extract_items(data)
        total = _extract_total(data, fallback=len(items))
        page_size = max(1, int(settings.scenario_query_page_size))
        page_count = max(1, math.ceil(total / page_size))
        if page_count <= 1:
            return items

        rows = list(items)
        for page in range(2, page_count + 1):
            payload = self._query_page(clean_labels, page=page)
            rows.extend(_extract_items(payload.get("data") or {}))
        return rows

    def _query_page(self, labels: list[str], page: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "labels": ",".join(labels),
            "page": page,
            "size": max(1, int(settings.scenario_query_page_size)),
        }
        content = json.dumps(body)
        headers = {
            "content-type": "application/json",
            "appid": settings.scenario_app_id,
            "time": str(int(time.time())),
            "sign": _sign_text(content, settings.scenario_app_token),
        }
        url = f"{settings.scenario_base_url.rstrip('/')}/simulation/scenario/query/"
        with httpx.Client(timeout=settings.voyager_timeout_seconds, trust_env=False) as client:
            resp = client.post(url, content=content, headers=headers)
            resp.raise_for_status()
            result = resp.json()
        if result.get("msg") != "success":
            raise RuntimeError(f"Scenario API returned error: {_safe_error_payload(result)}")
        return result


def build_source_scenario_index(metadata: dict[str, Any], client: ScenarioClient) -> dict[str, dict[str, Any]]:
    scenario_sets = metadata.get("scenario_sets") or {}
    label_specs = [
        ("positive_auto", True, scenario_sets.get("positive", {}).get("labels") or []),
        ("positive_manual", True, scenario_sets.get("positive", {}).get("manual_labels") or []),
        ("negative_auto", False, scenario_sets.get("negative", {}).get("labels") or []),
        ("negative_manual", False, scenario_sets.get("negative", {}).get("manual_labels") or []),
        ("negative_normal_stop", False, scenario_sets.get("negative", {}).get("normal_stop_labels") or []),
    ]
    index: dict[str, dict[str, Any]] = {}
    for source_group, road_triggered, labels in label_specs:
        if not labels:
            continue
        rows = client.query_label_set([str(label) for label in labels])
        for row in rows:
            scenario_id = _scenario_id(row)
            if not scenario_id:
                continue
            existing = index.get(scenario_id, {})
            source_groups = list(existing.get("source_groups") or [])
            if source_group not in source_groups:
                source_groups.append(source_group)
            source_labels = list(existing.get("source_labels") or [])
            for label in labels:
                if label not in source_labels:
                    source_labels.append(label)
            index[scenario_id] = {
                **existing,
                "scenario_id": scenario_id,
                "scenario_name": _first(row, "name", "scenario_name") or existing.get("scenario_name", ""),
                "issue_id": _first(row, "issue_id", "disengage_info_id") or existing.get("issue_id"),
                "signature": _first(row, "signature") or existing.get("signature", ""),
                "road_triggered": road_triggered if "road_triggered" not in existing else existing["road_triggered"],
                "source_groups": source_groups,
                "source_labels": source_labels,
                "raw_source": row,
            }
    return index


def source_counts_from_index(index: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {
        "auto_trigger_tp": 0,
        "manual_trigger_fn": 0,
        "auto_trigger_fp": 0,
        "manual_trigger_irrelevant": 0,
        "normal_wait_tn_partial": 0,
        "total_scenarios": len(index),
    }
    for item in index.values():
        groups = set(item.get("source_groups") or [])
        if "positive_auto" in groups:
            counts["auto_trigger_tp"] += 1
        if "positive_manual" in groups:
            counts["manual_trigger_fn"] += 1
        if "negative_auto" in groups:
            counts["auto_trigger_fp"] += 1
        if "negative_manual" in groups:
            counts["manual_trigger_irrelevant"] += 1
        if "negative_normal_stop" in groups:
            counts["normal_wait_tn_partial"] += 1
    return counts


def _sign_payload(payload: dict[str, Any], token: str) -> str:
    text = json.dumps(payload) + "&token=" + token
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _sign_text(text: str, token: str) -> str:
    return hashlib.md5((text + "&token=" + token).encode("utf-8")).hexdigest()


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("res", "data", "results", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_total(data: dict[str, Any], fallback: int) -> int:
    for key in ("total", "count"):
        value = data.get(key)
        if value not in {None, ""}:
            return int(value)
    return fallback


def _scenario_id(row: dict[str, Any]) -> str:
    value = _first(row, "id", "scenario_id")
    return str(value).strip() if value not in {None, ""} else ""


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return None


def _safe_error_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.lower() not in {"cookie", "cookies", "authorization", "token"}
    }
