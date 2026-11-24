"""Single Trail MD5 payload signer and pooled HTTP client utilities."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from app.infra.settings import ssl_verify_setting


def sign_trail_payload(payload: dict[str, Any], token: str) -> str:
    """Compute Trail JSON MD5 signature matching default json.dumps whitespace."""
    text = json.dumps(payload) + "&token=" + token
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sign_trail_text(serialized_json: str, token: str) -> str:
    return hashlib.md5((serialized_json + "&token=" + token).encode("utf-8")).hexdigest()


def trail_signed_headers(
    payload: dict[str, Any], app_id: str, token: str
) -> tuple[str, dict[str, str]]:
    text = json.dumps(payload)
    headers = {
        "content-type": "application/json",
        "appid": str(app_id),
        "time": str(int(time.time())),
        "sign": sign_trail_text(text, token),
    }
    return text, headers


def create_http_client(
    *, timeout: float = 60.0, trust_env: bool = False, cookies: Any = None, headers: Any = None
) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        trust_env=trust_env,
        verify=ssl_verify_setting(),
        cookies=cookies,
        headers=headers,
    )
