from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .security import SecretError, read_secret_file


MAX_RELAY_RESPONSE_BYTES = 256 * 1024


class RelayError(RuntimeError):
    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class RelayClient:
    def __init__(
        self,
        *,
        base_url: str,
        secret_file: Path,
        worker_id: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_file = secret_file
        self.worker_id = worker_id
        self.timeout_seconds = max(0.2, min(float(timeout_seconds), 10.0))
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            urllib.request.HTTPHandler(),
            _NoRedirect(),
        )

    def pull(self) -> dict[str, Any] | None:
        status, payload = self._request("/pull", {"worker_id": self.worker_id})
        if status == 204:
            return None
        if not isinstance(payload, dict):
            raise RelayError("Relay pull 返回了非法数据。", transient=True)
        required = ("event_id", "sender", "question", "lease_token")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
            raise RelayError("Relay pull 缺少必要字段。", transient=True)
        return payload

    def ack(self, item: dict[str, Any], *, delivery_id: str) -> None:
        self._request(
            "/ack",
            {
                "event_id": str(item["event_id"]),
                "lease_token": str(item["lease_token"]),
                "delivery_id": str(delivery_id)[:256],
            },
        )

    def nack(self, item: dict[str, Any], *, error: str, terminal: bool) -> None:
        self._request(
            "/nack",
            {
                "event_id": str(item["event_id"]),
                "lease_token": str(item["lease_token"]),
                "error": str(error)[:500],
                "terminal": bool(terminal),
            },
        )

    def _request(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        try:
            secret = read_secret_file(self.secret_file).decode("utf-8")
        except (SecretError, UnicodeDecodeError) as exc:
            raise RelayError("Relay worker token 不可用。", transient=False) from exc
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json;charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
                content = response.read(MAX_RELAY_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            transient = exc.code in {408, 425, 429} or 500 <= exc.code < 600
            raise RelayError(
                f"Relay HTTP {exc.code}。", transient=transient
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RelayError("Relay 暂时不可达。", transient=True) from exc
        if len(content) > MAX_RELAY_RESPONSE_BYTES:
            raise RelayError("Relay 响应过大。", transient=True)
        if status == 204:
            return status, None
        try:
            decoded = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RelayError("Relay 返回了非法 JSON。", transient=True) from exc
        return status, decoded
