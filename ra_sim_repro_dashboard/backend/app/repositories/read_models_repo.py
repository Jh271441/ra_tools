"""CQRS materialized read models and per-release version counters."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.models import DashboardReadModel, ReleaseDataVersion, utcnow

GLOBAL_RELEASE_SCOPE = "__global__"


def bump_release_version(db: Session, release: str | None = None) -> None:
    """Atomically increment per-release version counter inside the active transaction."""
    scope = (release or GLOBAL_RELEASE_SCOPE).strip()[:64] or GLOBAL_RELEASE_SCOPE
    now = utcnow()
    result = db.execute(
        update(ReleaseDataVersion)
        .where(ReleaseDataVersion.release == scope)
        .values(version_seq=ReleaseDataVersion.version_seq + 1, updated_at=now)
    )
    if result.rowcount == 0:
        try:
            db.execute(
                insert(ReleaseDataVersion).values(release=scope, version_seq=1, updated_at=now)
            )
        except Exception:
            # Concurrent insert won the race; retry update once.
            db.execute(
                update(ReleaseDataVersion)
                .where(ReleaseDataVersion.release == scope)
                .values(version_seq=ReleaseDataVersion.version_seq + 1, updated_at=now)
            )


def get_release_versions(db: Session, releases: list[str] | None = None) -> dict[str, int]:
    """Read lightweight monotonic version counters (1 index scan, zero JSON)."""
    stmt = select(ReleaseDataVersion.release, ReleaseDataVersion.version_seq)
    if releases is not None:
        scopes = list({GLOBAL_RELEASE_SCOPE, *(r for r in releases if r)})
        stmt = stmt.where(ReleaseDataVersion.release.in_(scopes))
    rows = db.execute(stmt).all()
    return {str(rel): int(seq) for rel, seq in rows}


def get_version_signature(
    db: Session, releases: list[str] | None = None
) -> tuple[tuple[str, int], ...]:
    versions = get_release_versions(db, releases=releases)
    return tuple(sorted(versions.items()))


def get_read_model(db: Session, cache_key: str) -> DashboardReadModel | None:
    return db.get(DashboardReadModel, cache_key)


def get_read_models_batch(db: Session, cache_keys: list[str]) -> dict[str, DashboardReadModel]:
    if not cache_keys:
        return {}
    rows = db.scalars(
        select(DashboardReadModel).where(DashboardReadModel.cache_key.in_(cache_keys))
    ).all()
    return {row.cache_key: row for row in rows}


def upsert_read_model(
    db: Session,
    *,
    cache_key: str,
    scope_release: str,
    view_type: str,
    source_version: str,
    payload: dict[str, Any],
    profile_id: str = "",
) -> DashboardReadModel:
    now: datetime = utcnow()
    existing = db.get(DashboardReadModel, cache_key)
    if existing is not None:
        existing.scope_release = scope_release[:64]
        existing.profile_id = profile_id[:64]
        existing.view_type = view_type[:64]
        existing.source_version = source_version[:128]
        existing.payload = payload
        existing.computed_at = now
        return existing
    model = DashboardReadModel(
        cache_key=cache_key[:160],
        scope_release=scope_release[:64],
        profile_id=profile_id[:64],
        view_type=view_type[:64],
        source_version=source_version[:128],
        payload=payload,
        computed_at=now,
    )
    db.add(model)
    return model


def count_read_models(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(DashboardReadModel)) or 0)
