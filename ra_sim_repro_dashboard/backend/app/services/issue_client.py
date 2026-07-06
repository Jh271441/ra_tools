from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _sign_payload(payload: dict[str, Any], token: str) -> str:
    text = json.dumps(payload) + "&token=" + token
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class IssueClient:
    """Reads issue metadata from mock JSON or the internal issue API."""

    def __init__(self, mock_dir: Path | None = None) -> None:
        self.mock_dir = mock_dir or settings.mock_data_dir

    def query_issues(self, issue_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized = [str(item) for item in issue_ids if str(item).strip()]
        if not normalized:
            return {}
        mock = self._read_mock()
        result = {issue_id: mock[issue_id] for issue_id in normalized if issue_id in mock}
        missing = [issue_id for issue_id in normalized if issue_id not in result]
        if not missing:
            return result
        if not settings.issue_app_id or not settings.issue_app_token:
            logger.warning("Issue API credentials are not configured; using fallback issue rows.")
            result.update({issue_id: self._fallback_issue(issue_id) for issue_id in missing})
            return result
        result.update(self._query_api(missing))
        return result

    def _read_mock(self) -> dict[str, dict[str, Any]]:
        path = self.mock_dir / "issues.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}

    def _query_api(self, issue_ids: list[str]) -> dict[str, dict[str, Any]]:
        url = f"{settings.issue_base_url.rstrip('/')}/query_by_issue_id_list/"
        fields = ["issue_id", "issue_topic", "issue_time", "poi", "status", "priority"]
        result: dict[str, dict[str, Any]] = {}
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            for start in range(0, len(issue_ids), 200):
                chunk = issue_ids[start : start + 200]
                body = {
                    "source_id": 1,
                    "issue_id_list": chunk,
                    "select_field_list": fields,
                }
                content = json.dumps(body)
                headers = {
                    "content-type": "application/json",
                    "appid": settings.issue_app_id,
                    "time": str(int(time.time())),
                    "sign": _sign_text(content, settings.issue_app_token),
                }
                resp = client.post(url, content=content, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("msg") != "success":
                    raise RuntimeError(f"Issue API returned error: {payload}")
                data = payload.get("data", {})
                for issue_id, issue in data.items():
                    result[str(issue_id)] = issue
        for issue_id in issue_ids:
            result.setdefault(issue_id, self._fallback_issue(issue_id))
        return result

    @staticmethod
    def _fallback_issue(issue_id: str) -> dict[str, Any]:
        return {
            "issue_id": issue_id,
            "issue_topic": "",
            "status": "unknown",
            "priority": "",
            "poi": "",
            "issue_time": "",
        }


def _sign_text(text: str, token: str) -> str:
    return hashlib.md5((text + "&token=" + token).encode("utf-8")).hexdigest()
