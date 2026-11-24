"""Standalone Trail Scenario Platform client (decoupled from cross-repo `ra_api`)."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from app.clients.http_base import sign_trail_payload
from app.infra.settings import settings, ssl_verify_setting

SCENARIO_QUERY_URL = f"{settings.scenario_base_url.rstrip('/')}/query/"
SCENARIO_UPDATE_URL = f"{settings.scenario_base_url.rstrip('/')}/update/"


class ScenarioPlatformClient:
    """Read/append scenario labels against Trail Scenario API without `ra_api` imports."""

    def __init__(self, app_id: str | None = None, app_token: str | None = None) -> None:
        self.app_id = (
            app_id
            or os.getenv("SCENARIO_APP_ID")
            or settings.scenario_app_id
            or os.getenv("TRAIL_APP_ID")
            or "21"
        )
        self.app_token = (
            app_token
            or os.getenv("SCENARIO_APP_TOKEN")
            or settings.scenario_app_token
            or os.getenv("SIM_RESULT_APP_TOKEN")
            or os.getenv("TRAIL_APP_TOKEN")
            or os.getenv("TRAIL_API_TOKEN")
            or ""
        )
        self.query_url = (
            f"{os.getenv('SCENARIO_BASE_URL', settings.scenario_base_url).rstrip('/')}/query/"
        )
        self.update_url = (
            f"{os.getenv('SCENARIO_BASE_URL', settings.scenario_base_url).rstrip('/')}/update/"
        )
        self.session = requests.Session()
        self.session.trust_env = True

    def post(self, url: str, payload: dict[str, Any], read_only: bool = False) -> dict[str, Any]:
        if not self.app_token:
            raise RuntimeError("Scenario API token is not configured")
        headers = {
            "content-type": "application/json",
            "appid": str(self.app_id),
            "time": str(int(time.time())),
            "sign": sign_trail_payload(payload, self.app_token),
        }
        verify = ssl_verify_setting()
        for attempt in range(3 if read_only else 1):
            try:
                response = self.session.post(
                    url, json=payload, headers=headers, timeout=60, verify=verify
                )
                response.raise_for_status()
                value = response.json()
                if value.get("msg") != "success":
                    raise ValueError("scenario_api_failed")
                return value
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                transient = response is None or response.status_code in (502, 503, 504, 596)
                if not read_only or not transient or attempt == 2:
                    raise
                time.sleep(0.25 * (attempt + 1))
        raise ValueError("scenario_api_failed")
