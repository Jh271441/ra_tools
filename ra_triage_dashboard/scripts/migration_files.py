"""Bounded file hashing shared by standalone Manual migration tools."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

HASH_CHUNK_BYTES = 4 * 1024 * 1024


def stream_sha256(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(HASH_CHUNK_BYTES), b""):
        digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return stream_sha256(stream)
