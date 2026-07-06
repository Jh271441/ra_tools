from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_METRICS = [
    "dpe_collision",
    "dpe_stuck_detect",
    "dpe_assist_channel_triggered",
]
TRIGGER_METRIC = "dpe_assist_channel_triggered"


class DataSourceUnavailable(RuntimeError):
    """Raised when no configured real API can be used."""


def _sign_payload(payload: dict[str, Any], token: str) -> str:
    text = json.dumps(payload) + "&token=" + token
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class SimResultClient:
    """Reads scenario-level simulation results from mock JSON, Voyager, or Trail."""

    def __init__(self, mock_dir: Path | None = None) -> None:
        self.mock_dir = mock_dir or settings.mock_data_dir

    def query_job(self, sim_job_id: int, baseline_job_id: int | None = None) -> list[dict[str, Any]]:
        mock_rows = self._read_mock(sim_job_id)
        if mock_rows is not None:
            return mock_rows
        return self._query_all_pages(sim_job_id, baseline_job_id)

    def query_eval_jobs(
        self,
        positive_job_id: int,
        negative_job_id: int,
        version_key: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        rows.extend(
            self._with_dataset_role(
                self.query_job(positive_job_id),
                version_key=version_key,
                job_id=positive_job_id,
                dataset_role="positive",
                road_triggered=True,
            )
        )
        rows.extend(
            self._with_dataset_role(
                self.query_job(negative_job_id),
                version_key=version_key,
                job_id=negative_job_id,
                dataset_role="negative",
                road_triggered=False,
            )
        )
        return rows

    def _read_mock(self, sim_job_id: int) -> list[dict[str, Any]] | None:
        path = self.mock_dir / f"sim_job_{sim_job_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            return list(payload.get("rows", []))
        if isinstance(payload, list):
            return payload
        return []

    def _query_all_pages(self, sim_job_id: int, baseline_job_id: int | None) -> list[dict[str, Any]]:
        if settings.voyager_cookie:
            return self._query_all_pages_with_post(
                sim_job_id=sim_job_id,
                baseline_job_id=baseline_job_id,
                mode="voyager_cookie",
            )
        if settings.trail_app_id and settings.trail_app_token:
            return self._query_all_pages_with_post(
                sim_job_id=sim_job_id,
                baseline_job_id=baseline_job_id,
                mode="trail_signed",
            )
        raise DataSourceUnavailable(
            "Real sim API is not configured. Set VOYAGER_COOKIE or TRAIL_APP_ID/TRAIL_APP_TOKEN."
        )

    def _query_all_pages_with_post(
        self,
        sim_job_id: int,
        baseline_job_id: int | None,
        mode: Literal["voyager_cookie", "trail_signed"],
    ) -> list[dict[str, Any]]:
        page_size = max(1, min(int(settings.voyager_query_page_size), 1000))
        page = 1
        rows: list[dict[str, Any]] = []
        while True:
            result = self._query_report_page(
                sim_job_id=sim_job_id,
                baseline_job_id=baseline_job_id,
                page=page,
                page_size=page_size,
                mode=mode,
            )
            page_rows, total = self._parse_report_rows(result)
            rows.extend(page_rows)
            if not page_rows:
                break
            if total is not None and len(rows) >= total:
                break
            if len(page_rows) < page_size:
                break
            page += 1
        return rows

    def _query_report_page(
        self,
        sim_job_id: int,
        baseline_job_id: int | None,
        page: int,
        page_size: int,
        mode: Literal["voyager_cookie", "trail_signed"],
    ) -> dict[str, Any]:
        job_ids = [sim_job_id] + ([baseline_job_id] if baseline_job_id else [])
        body: dict[str, Any] = {
            "orion_job_ids": job_ids,
            "selected_metrics": DEFAULT_METRICS,
            "filters": [],
            "filters_protocol_sql": "",
            "page": page,
            "size": page_size,
            "extra_fields": [],
            "order_by": f"group1__{TRIGGER_METRIC}",
            "order_type": "desc",
        }
        headers = {"content-type": "application/json"}
        cookies: dict[str, str] | None = None
        if mode == "voyager_cookie":
            url = f"{settings.voyager_result_base_url.rstrip('/')}/simulation/sim_test/result/query_report/"
            headers["cookie"] = settings.voyager_cookie
            content: str | None = None
        else:
            url = f"{settings.trail_base_url.rstrip('/')}/simulation/sim_test/result/query_report/"
            content = json.dumps(body)
            headers.update(
                {
                    "appid": settings.trail_app_id,
                    "time": str(int(time.time())),
                    "sign": _sign_text(content, settings.trail_app_token),
                }
            )
        with httpx.Client(
            timeout=settings.voyager_timeout_seconds,
            verify=False,
            cookies=cookies,
            trust_env=False,
        ) as client:
            if content is None:
                resp = client.post(url, json=body, headers=headers)
            else:
                resp = client.post(url, content=content, headers=headers)
            resp.raise_for_status()
            result = resp.json()
        if result.get("msg") != "success":
            raise RuntimeError(f"Sim result API returned error: {_safe_error_payload(result)}")
        return result

    def _parse_report_rows(self, result: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        details = result.get("data", {}).get("details", {})
        total: int | None = None
        if isinstance(details, dict):
            items = details.get("results", details.get("data", []))
            total_value = details.get("count", details.get("total"))
            total = int(total_value) if total_value not in {None, ""} else None
        elif isinstance(details, list):
            items = details
        else:
            items = []
        rows = []
        for item in items or []:
            info = item.get("scenario_info", {})
            row: dict[str, Any] = {
                "scenario_id": info.get("scenario_id"),
                "scenario_name": info.get("scenario_name", ""),
                "issue_id": info.get("issue_id", ""),
                "signature": info.get("signature", ""),
            }
            for metric, groups in item.get("metric_results", {}).items():
                for group, metric_result in groups.items():
                    value = metric_result.get("value", {})
                    row[f"{metric}__{group}"] = value.get("value") if isinstance(value, dict) else value
                    if isinstance(value, dict) and "status" in value:
                        row[f"{metric}__{group}__status"] = value.get("status")
                    if isinstance(metric_result.get("diff"), dict):
                        row[f"{metric}__diff"] = metric_result["diff"].get("value")
            if "dpe_assist_channel_triggered__group1" in row:
                row["dpe_assist_channel_triggered"] = row["dpe_assist_channel_triggered__group1"]
            rows.append(row)
        return rows, total

    def _with_dataset_role(
        self,
        rows: list[dict[str, Any]],
        version_key: str,
        job_id: int,
        dataset_role: Literal["positive", "negative"],
        road_triggered: bool,
    ) -> list[dict[str, Any]]:
        normalized = []
        for row in rows:
            item = dict(row)
            metric_value = _metric_value(item.get(TRIGGER_METRIC))
            item.update(
                {
                    "version_key": version_key,
                    "job_id": job_id,
                    "dataset_role": dataset_role,
                    "road_triggered": road_triggered,
                    "sim_triggered": metric_value is not None and metric_value >= 1,
                }
            )
            normalized.append(item)
        return normalized


def _metric_value(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_error_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.lower() not in {"cookie", "cookies", "authorization", "token"}
    }


def _sign_text(text: str, token: str) -> str:
    return hashlib.md5((text + "&token=" + token).encode("utf-8")).hexdigest()
