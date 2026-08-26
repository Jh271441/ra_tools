from __future__ import annotations

import re
from pathlib import Path


def safe_filename(name: str, *, max_length: int = 120) -> str:
    """Return a bounded display filename without truncating its extension."""

    result = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload")
    result = result.strip("._") or "upload"
    if len(result) <= max_length:
        return result
    suffix = Path(result).suffix
    if suffix and len(suffix) < 20:
        stem = result[: -len(suffix)].rstrip("._")
        return f"{stem[: max_length - len(suffix)]}{suffix}"
    return result[:max_length]
