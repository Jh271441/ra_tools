from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "authtoken",
        "bearertoken",
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "privatekey",
        "baseurl",
        "endpoint",
        "modelendpoint",
        "cookie",
        "setcookie",
    }
)
_SENSITIVE_SUFFIXES = (
    "apikey",
    "token",
    "password",
    "passwd",
    "secret",
    "privatekey",
    "baseurl",
    "endpoint",
    "cookie",
)


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _is_sensitive_key(value: Any) -> bool:
    key = _normalise_key(value)
    return key in _SENSITIVE_KEYS or any(
        key.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES
    )


def redact_sensitive_fields(value: Any) -> Any:
    """Recursively redact credential and endpoint fields from shared storage."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                result[text_key] = "[REDACTED]"
            else:
                result[text_key] = redact_sensitive_fields(item)
        return result
    if isinstance(value, list):
        return [redact_sensitive_fields(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_fields(item) for item in value]
    return value
