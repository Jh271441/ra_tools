"""Kunpeng/SimOne Sim Plan client."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

import requests

from model_release_pipeline.config import BranchSimPlanConfig, SimPlanConfig


TRIGGER_PATH = "/simulation/simone/simrun/trigger_by_kunpeng/"
QUERY_RECORDS_PATH = "/simulation/simone/simrun/query_record_list/"
QUERY_DETAIL_PATH = "/simulation/simone/simrun/get_record_run_detail/"
QUERY_GROUP_PATH = "/simulation/simone/simrun/query_group_record_list/"
CANCEL_PATH = "/simulation/simone/simrun/cancel_sim_by_kunpeng/"
QUERY_SIMPLAN_PATH = "/simulation/simbot/simplan/query/"


class SimPlanClient:
    """Small signed HTTP client for Trail/Kunpeng SimOne endpoints."""

    def __init__(self, config: SimPlanConfig) -> None:
        self.config = config

    def _token(self) -> str:
        token = self.config.token or os.environ.get(self.config.token_env, "")
        if not token and self.config.token_file:
            token_path = Path(self.config.token_file).expanduser()
            if token_path.exists():
                token = token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(
                "Sim Plan Trail token is not configured. Set "
                f"{self.config.token_env}, sim_plan.token, or sim_plan.token_file "
                "in the release config."
            )
        return token

    def _signed_body(self, body: Dict[str, Any]) -> Dict[str, Any]:
        signed = dict(body)
        signed["appid"] = self.config.appid
        signed["time"] = int(time.time())
        return signed

    def _headers(self, signed_body: Dict[str, Any]) -> Dict[str, str]:
        sign_text = f"{json.dumps(signed_body)}&token={self._token()}"
        sign = hashlib.md5(sign_text.encode("utf-8")).hexdigest()
        return {
            "appid": str(signed_body["appid"]),
            "time": str(signed_body["time"]),
            "sign": sign,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = urljoin(self.config.trail_base_url.rstrip("/") + "/", path.lstrip("/"))
        signed_body = self._signed_body(body)
        response = requests.post(
            url,
            data=json.dumps(signed_body),
            headers=self._headers(signed_body),
            timeout=self.config.timeout_sec,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"Trail request failed: HTTP {response.status_code}: {payload}")
        return payload

    @staticmethod
    def _success(payload: Dict[str, Any]) -> bool:
        code = payload.get("errno", payload.get("err_no", payload.get("code", 0)))
        return code in (0, "0", None) and not payload.get("error")

    @staticmethod
    def _data(payload: Dict[str, Any]) -> Any:
        return payload.get("data", payload)

    def resolve_plan_id(self, plan: BranchSimPlanConfig) -> int:
        if plan.plan_id:
            return int(plan.plan_id)
        body = {
            "name__icontains": plan.name,
            "page": 1,
            "size": 20,
            "query_from": self.config.trigger_from,
            "username": self.config.username,
        }
        payload = self._post(QUERY_SIMPLAN_PATH, body)
        data = self._data(payload)
        candidates: Iterable[Any]
        if isinstance(data, dict):
            candidates = data.get("list") or data.get("records") or data.get("data") or []
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = []
        exact = [
            item
            for item in candidates
            if isinstance(item, dict) and str(item.get("name") or "") == plan.name
        ]
        if len(exact) != 1:
            raise RuntimeError(f"Unable to resolve unique Sim Plan id for {plan.name!r}.")
        plan_id = exact[0].get("id")
        if plan_id is None:
            raise RuntimeError(f"Resolved Sim Plan {plan.name!r} has no id.")
        return int(plan_id)

    def build_trigger_payload(
        self,
        *,
        release_id: str,
        branch: str,
        revision_id: int,
        plan: BranchSimPlanConfig,
        plan_id: int,
        priority: Optional[int] = None,
        time_sensitive_hour: Optional[float] = None,
    ) -> Dict[str, Any]:
        plan_payload: Dict[str, Any] = {
            "id": int(plan_id),
            "name": plan.name,
        }
        chosen_priority = priority or plan.priority or self.config.priority
        if chosen_priority:
            plan_payload["priority"] = int(chosen_priority)
        chosen_sensitive = (
            time_sensitive_hour
            if time_sensitive_hour is not None
            else plan.time_sensitive_hour
        )
        if chosen_sensitive:
            plan_payload["time_sensitive_hour"] = chosen_sensitive
        trigger_param = {
            "revision_id": int(revision_id),
            "patchset": "",
            "base_version": self.config.base_version,
            "simplan_list": [plan_payload],
            "priority": int(chosen_priority),
            "platform": self.config.platform,
            "cluster": self.config.cluster,
            "denoise_mode": self.config.denoise_mode,
        }
        return {
            "business_type": self.config.business_type,
            "trigger_param": trigger_param,
            "username": self.config.username,
            "trigger_from": self.config.trigger_from,
            "context_key": (
                f"{self.config.context_prefix}:"
                f"{release_id}:{branch}:{revision_id}:{plan.name}"
            ),
        }

    def trigger(
        self,
        *,
        release_id: str,
        branch: str,
        revision_id: int,
        plan: BranchSimPlanConfig,
        priority: Optional[int] = None,
        time_sensitive_hour: Optional[float] = None,
    ) -> Dict[str, Any]:
        plan_id = self.resolve_plan_id(plan)
        body = self.build_trigger_payload(
            release_id=release_id,
            branch=branch,
            revision_id=revision_id,
            plan=plan,
            plan_id=plan_id,
            priority=priority,
            time_sensitive_hour=time_sensitive_hour,
        )
        payload = self._post(TRIGGER_PATH, body)
        return {
            "returncode": 0 if self._success(payload) else 1,
            "request": body,
            "response": payload,
            "plan_id": plan_id,
            "context_id": (self._data(payload) or {}).get("context_id")
            if isinstance(self._data(payload), dict)
            else None,
        }

    def query_records(
        self,
        *,
        revision_id: Optional[int] = None,
        record_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "business_type": self.config.business_type,
            "username": self.config.username,
            "trigger_from": self.config.trigger_from,
            "page": page,
            "size": size,
            "order_by": "create_time",
            "order_type": "desc",
        }
        if revision_id is not None:
            body["revision_id"] = int(revision_id)
        if record_id:
            body["id"] = record_id
        payload = self._post(QUERY_RECORDS_PATH, body)
        return {"returncode": 0 if self._success(payload) else 1, "request": body, "response": payload}

    def query_group(self, context_id: Any) -> Dict[str, Any]:
        body = {
            "id": context_id,
            "business_type": self.config.business_type,
            "username": self.config.username,
            "need_sim_info": True,
        }
        payload = self._post(QUERY_GROUP_PATH, body)
        return {"returncode": 0 if self._success(payload) else 1, "request": body, "response": payload}

    def detail(self, record_id: str) -> Dict[str, Any]:
        body = {"id": record_id, "username": self.config.username}
        payload = self._post(QUERY_DETAIL_PATH, body)
        return {"returncode": 0 if self._success(payload) else 1, "request": body, "response": payload}

    def cancel(self, record_id: str) -> Dict[str, Any]:
        text = str(record_id).strip()
        if text and text[0].isdigit():
            text = f"o{text}"
        body = {"plan_record_id": text, "username": self.config.username}
        payload = self._post(CANCEL_PATH, body)
        return {"returncode": 0 if self._success(payload) else 1, "request": body, "response": payload}
