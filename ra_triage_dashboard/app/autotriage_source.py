from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_AUTOTRIAGE_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_AUTOTRIAGE_RESULTS = 10_000
BATCH_ID_RE = re.compile(r"^[1-9][0-9]{0,11}$")


class AutoTriageSourceError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def normalise_batch_id(value: Any) -> str:
    text = str(value or "").strip()
    if BATCH_ID_RE.fullmatch(text):
        return text
    match = re.search(r"/(?:records|batches)/([1-9][0-9]{0,11})(?:[/?#]|$)", text)
    if match:
        return match.group(1)
    raise AutoTriageSourceError("请输入 AutoTriage Batch ID 或 records 链接。")


class AutoTriageSource:
    """Read-only client for immutable AutoTriage batch/result snapshots."""

    def __init__(self, base_url: str):
        parsed = urlsplit(str(base_url or "").strip().rstrip("/"))
        try:
            port = parsed.port
        except ValueError:
            port = -1
        host = (parsed.hostname or "").lower()
        endpoint_allowed = (
            host == "10.190.57.183"
            and parsed.scheme == "http"
            and port == 8000
        ) or (
            host == "auto-triage.intra.xiaojukeji.com"
            and (
                (parsed.scheme == "http" and port in {None, 80})
                or (parsed.scheme == "https" and port in {None, 443})
            )
        )
        if (
            not endpoint_allowed
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise RuntimeError("AutoTriage 只读 API 地址配置非法。")
        self.base_url = parsed.geturl().rstrip("/")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def fetch_batch(self, batch_id: Any) -> dict[str, Any]:
        normalized = normalise_batch_id(batch_id)
        payload = self._get_json(
            f"/api/v1/model_triage/batches/{quote(normalized, safe='')}/"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not payload.get("success") or not isinstance(data, dict):
            raise AutoTriageSourceError("AutoTriage Batch 响应格式非法。")
        if str(data.get("id") or "") != normalized:
            raise AutoTriageSourceError("AutoTriage Batch ID 与响应不一致。")
        return data

    def fetch_results(self, batch_id: Any) -> list[dict[str, Any]]:
        normalized = normalise_batch_id(batch_id)
        payload = self._get_json(
            f"/api/v1/model_triage/batches/{quote(normalized, safe='')}/results/"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not payload.get("success") or not isinstance(data, list):
            raise AutoTriageSourceError("AutoTriage Results 响应格式非法。")
        if len(data) > MAX_AUTOTRIAGE_RESULTS:
            raise AutoTriageSourceError(
                f"AutoTriage Results 超过 {MAX_AUTOTRIAGE_RESULTS} 条上限。"
            )
        return [row for row in data if isinstance(row, dict)]

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise AutoTriageSourceError("AutoTriage 只读请求失败。")
                declared = response.headers.get("Content-Length", "").strip()
                if declared and int(declared) > MAX_AUTOTRIAGE_RESPONSE_BYTES:
                    raise AutoTriageSourceError("AutoTriage 响应过大。")
                raw = response.read(MAX_AUTOTRIAGE_RESPONSE_BYTES + 1)
        except AutoTriageSourceError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise AutoTriageSourceError("AutoTriage 只读接口暂时不可用。")
        if len(raw) > MAX_AUTOTRIAGE_RESPONSE_BYTES:
            raise AutoTriageSourceError("AutoTriage 响应过大。")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError):
            raise AutoTriageSourceError("AutoTriage 响应不是有效 JSON。")
        if not isinstance(payload, dict):
            raise AutoTriageSourceError("AutoTriage 响应格式非法。")
        return payload
