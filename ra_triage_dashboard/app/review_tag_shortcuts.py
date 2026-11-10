"""Shared keyboard slots keyed by catalog ID, independent of labels and order."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable


SHORTCUT_SLOTS = 24
MAX_BINDINGS_BYTES = 1_048_576


class ReviewTagShortcutStore:
    """Small persistent UI metadata; no label, Review or database mutation."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict[str, dict[str, int]]:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(MAX_BINDINGS_BYTES + 1)
        if len(raw) > MAX_BINDINGS_BYTES:
            raise ValueError("Shortcut bindings exceed size limit")
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("schema") != 1:
            raise ValueError("Invalid shortcut bindings")
        groups = record.get("groups")
        if not isinstance(groups, dict):
            raise ValueError("Invalid shortcut groups")
        for group, bindings in groups.items():
            if not isinstance(group, str) or not isinstance(bindings, dict):
                raise ValueError("Invalid shortcut group")
            slots = list(bindings.values())
            if any(not isinstance(key, str) or not key for key in bindings) or any(
                type(slot) is not int or not 0 <= slot < SHORTCUT_SLOTS for slot in slots
            ) or len(set(slots)) != len(slots):
                raise ValueError("Invalid shortcut slots")
        return groups

    def _write(self, groups: dict[str, dict[str, int]]) -> None:
        payload = json.dumps({"schema": 1, "groups": groups}, ensure_ascii=False).encode()
        if len(payload) > MAX_BINDINGS_BYTES:
            raise ValueError("Shortcut bindings exceed size limit")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".shortcuts-", delete=False) as stream:
                temporary = stream.name
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def apply(
        self, namespace: str, read_catalog: Callable[[], Iterable[dict[str, Any]]]
    ) -> tuple[dict[str, Any], ...]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            # Read after taking the lock so an older request cannot restore
            # a removed binding or erase a newly allocated one.
            catalog = tuple(read_catalog())
            prefix = namespace + ":"
            active: dict[str, list[str]] = {}
            for item in catalog:
                if not item.get("deleted") and item.get("visible") is not False:
                    name = prefix + str(item.get("group") or "")
                    active.setdefault(name, []).append(str(item["key"]))
            groups = self._read()
            updated = {name: bindings for name, bindings in groups.items() if not name.startswith(prefix)}
            slots: dict[str, int] = {}
            for name, keys in active.items():
                bindings = {key: slot for key, slot in groups.get(name, {}).items() if key in keys}
                free = iter(sorted(set(range(SHORTCUT_SLOTS)) - set(bindings.values())))
                for key in keys:
                    if key not in bindings:
                        slot = next(free, None)
                        if slot is None:
                            break
                        bindings[key] = slot
                updated[name] = bindings
                slots.update(bindings)
            if updated != groups:
                self._write(updated)
            return tuple({**item, "shortcut_slot": slots.get(str(item["key"]))} for item in catalog)
