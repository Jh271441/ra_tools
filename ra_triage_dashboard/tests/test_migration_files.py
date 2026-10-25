"""Large migration payloads must be hashed with bounded reads."""

import hashlib
import io

import pytest

from ra_triage_dashboard.scripts.migration_files import (
    HASH_CHUNK_BYTES,
    file_sha256,
    stream_sha256,
)


class BoundedStream(io.BytesIO):
    def read(self, size=-1):
        assert 0 < size <= HASH_CHUNK_BYTES
        return super().read(size)


@pytest.mark.parametrize("size", [0, 31, HASH_CHUNK_BYTES * 2 + 17])
def test_hash_matches_content_across_chunk_boundaries(tmp_path, size):
    payload = b"x" * size
    expected = hashlib.sha256(payload).hexdigest()
    stream = BoundedStream(payload)
    assert stream_sha256(stream) == expected
    assert not stream.closed
    path = tmp_path / "backup.dump"
    path.write_bytes(payload)
    assert file_sha256(path) == expected


def test_missing_file_does_not_produce_a_digest(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing")
