"""Project durable label-publication receipts into the shared immutable audit."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .publication_audit_sync import (
    PUBLICATION_SOURCES,
    _time,
    sync_publication_audit,
)

__all__ = [
    "PUBLICATION_SOURCES",
    "_time",
    "reconcile_publication_history",
    "sync_publication_audit",
]


def reconcile_publication_history(db, directory):
    """Existing receipts enter the same history without replaying any upload."""
    for path in sorted((Path(directory) / "rd_publications").glob("*.json")):
        if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
            continue
        record = json.loads(path.read_text())
        if record["state"] == "running":
            from .rd_results import PublicationStore

            store = PublicationStore(directory)
            store.receipt(record["id"])
            record = store.get(record["id"])
        sync_publication_audit(db, record)
