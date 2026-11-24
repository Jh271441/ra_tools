"""Repository for metric profile lookup, listing, and draft creation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.hashing import digest
from app.domain.labels import SOURCE_FIELDS
from app.domain.metrics import BUILTIN, BUILTINS, validate_profile
from app.infra.locks import pipeline_lock
from app.models import ReleaseWorkflowState
from app.repositories import state_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_profile(db: Session, version: str | None = None) -> dict[str, Any]:
    resolved = (
        version or state_store.get_routed_state(db, "evprofile:active").get("id") or BUILTIN["id"]
    )
    if resolved in BUILTINS:
        return deepcopy(BUILTINS[resolved])
    value = state_store.get_routed_state(db, "evprofile:" + str(resolved))
    if not value:
        raise ValueError("profile_not_found")
    return value


def list_catalogue(db: Session) -> dict[str, Any]:
    records = [
        *[deepcopy(p) for p in BUILTINS.values()],
        *[
            r.payload
            for r in db.scalars(
                select(ReleaseWorkflowState).where(
                    ReleaseWorkflowState.key.startswith("evprofile:")
                )
            )
            if r.key != "evprofile:active"
        ],
    ]
    return {
        "active": get_profile(db)["id"],
        "versions": sorted(records, key=lambda r: r.get("created_at") or "", reverse=True),
        "label_sources": [
            {"id": name, "field": field, "requires_adapter": field is None}
            for name, field in SOURCE_FIELDS.items()
        ],
    }


def create_draft(
    db: Session, config: dict[str, Any], name: str, description: str, parent: str | None = None
) -> dict[str, Any]:
    with pipeline_lock("profiles"):
        validated = validate_profile(config)
        if not name.strip() or len(name) > 80 or len(description) > 2000:
            raise ValueError("profile_name_invalid")
        parent_id = get_profile(db, parent)["id"]
        value = {
            "name": name.strip(),
            "description": description,
            "config": validated,
            "config_hash": digest(validated),
            "parent": parent_id,
            "created_at": _now_iso(),
            "status": "draft",
        }
        value["id"] = "draft_" + digest(value)[:24]
        state_store.put_routed_state(db, "evprofile:" + value["id"], value, commit=True)
        return value
