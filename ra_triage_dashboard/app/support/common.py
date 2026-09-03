"""Common HTTP helpers."""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException


def _detail(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)

def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()
