from __future__ import annotations

import hashlib
from typing import Protocol


class AsyncUpload(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class UploadLimitExceeded(ValueError):
    """Raised once an upload exceeds the configured in-memory limit."""


async def read_upload_limited(
    upload: AsyncUpload,
    *,
    max_bytes: int,
    chunk_bytes: int = 1024 * 1024,
) -> tuple[bytes, str]:
    """Read an upload without ever buffering an unbounded request body.

    FastAPI's ``UploadFile`` is spooled, but ``await upload.read()`` still
    copies the complete payload into application memory.  Reading at most one
    byte beyond the limit makes rejection deterministic while bounding the
    application's allocation to ``max_bytes + 1``.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    chunks: list[bytes] = []
    digest = hashlib.sha256()
    total = 0
    while total <= max_bytes:
        remaining_with_sentinel = max_bytes - total + 1
        chunk = await upload.read(min(chunk_bytes, remaining_with_sentinel))
        if not chunk:
            break
        chunks.append(chunk)
        digest.update(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise UploadLimitExceeded
    return b"".join(chunks), digest.hexdigest()
