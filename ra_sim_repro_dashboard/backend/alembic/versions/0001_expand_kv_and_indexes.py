"""Expand KV key length to VARCHAR(128), convert JSON to JSONB on PG, and index snapshots/batches.

Revision ID: 0001_expand_kv_and_indexes
Revises:
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_expand_kv_and_indexes"
down_revision = None
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


_LEGACY_TABLES = (
    "versions",
    "scenarios",
    "issues",
    "scenario_version_results",
    "dashboard_snapshots",
    "refresh_jobs",
    "release_issue_snapshots",
    "release_simulation_batches",
    "release_workflow_state",
)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)

    # Bootstrap legacy baseline tables on brand-new empty databases; no-op on existing DBs.
    missing_legacy = [t for t in _LEGACY_TABLES if not inspector.has_table(t)]
    if missing_legacy:
        from app.database import Base
        import app.models  # noqa: F401

        tables_to_create = [
            Base.metadata.tables[name] for name in missing_legacy if name in Base.metadata.tables
        ]
        Base.metadata.create_all(bind=bind, tables=tables_to_create, checkfirst=True)

    # 1. Widen release_workflow_state.key (64 -> 128) and convert payload to JSONB on PG
    if _existing_columns("release_workflow_state"):
        if is_pg:
            op.alter_column(
                "release_workflow_state",
                "key",
                existing_type=sa.String(length=64),
                type_=sa.String(length=128),
                existing_nullable=False,
            )
            op.execute(
                "ALTER TABLE release_workflow_state "
                "ALTER COLUMN payload TYPE jsonb USING payload::jsonb"
            )
        else:
            with op.batch_alter_table("release_workflow_state") as batch_op:
                batch_op.alter_column(
                    "key",
                    existing_type=sa.String(length=64),
                    type_=sa.String(length=128),
                    existing_nullable=False,
                )

    # 2. release_issue_snapshots: add population_hash + indexes + JSONB on PG
    snap_cols = _existing_columns("release_issue_snapshots")
    if snap_cols:
        if "population_hash" not in snap_cols:
            op.add_column(
                "release_issue_snapshots",
                sa.Column("population_hash", sa.String(length=64), nullable=True),
            )
        snap_idx = _existing_indexes("release_issue_snapshots")
        if "ix_release_snapshots_rel_pophash" not in snap_idx:
            op.create_index(
                "ix_release_snapshots_rel_pophash",
                "release_issue_snapshots",
                ["release", "population_hash"],
            )
        if "ix_release_snapshots_rel_id" not in snap_idx:
            op.create_index(
                "ix_release_snapshots_rel_id",
                "release_issue_snapshots",
                ["release", "id"],
            )
        if is_pg:
            op.execute(
                "ALTER TABLE release_issue_snapshots "
                "ALTER COLUMN payload TYPE jsonb USING payload::jsonb"
            )

    # 3. release_simulation_batches: add population_hash, is_backfill, is_primary, job_id + indexes
    batch_cols = _existing_columns("release_simulation_batches")
    if batch_cols:
        if "population_hash" not in batch_cols:
            op.add_column(
                "release_simulation_batches",
                sa.Column("population_hash", sa.String(length=64), nullable=True),
            )
        if "is_backfill" not in batch_cols:
            op.add_column(
                "release_simulation_batches",
                sa.Column("is_backfill", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if "is_primary" not in batch_cols:
            op.add_column(
                "release_simulation_batches",
                sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if "job_id" not in batch_cols:
            op.add_column(
                "release_simulation_batches",
                sa.Column("job_id", sa.BigInteger(), nullable=True),
            )
        batch_idx = _existing_indexes("release_simulation_batches")
        if "ix_release_batches_rel_status" not in batch_idx:
            op.create_index(
                "ix_release_batches_rel_status",
                "release_simulation_batches",
                ["release", "status"],
            )
        if "ix_release_batches_rel_pophash" not in batch_idx:
            op.create_index(
                "ix_release_batches_rel_pophash",
                "release_simulation_batches",
                ["release", "population_hash"],
            )
        if "ix_release_simulation_batches_job_id" not in batch_idx:
            op.create_index(
                "ix_release_simulation_batches_job_id",
                "release_simulation_batches",
                ["job_id"],
            )
        if is_pg:
            op.execute(
                "ALTER TABLE release_simulation_batches "
                "ALTER COLUMN payload TYPE jsonb USING payload::jsonb"
            )

    # 4. dashboard_snapshots JSONB on PG
    if is_pg and _existing_columns("dashboard_snapshots"):
        op.execute(
            "ALTER TABLE dashboard_snapshots "
            "ALTER COLUMN snapshot TYPE jsonb USING snapshot::jsonb"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    batch_idx = _existing_indexes("release_simulation_batches")
    for idx in (
        "ix_release_simulation_batches_job_id",
        "ix_release_batches_rel_pophash",
        "ix_release_batches_rel_status",
    ):
        if idx in batch_idx:
            op.drop_index(idx, table_name="release_simulation_batches")

    batch_cols = _existing_columns("release_simulation_batches")
    if batch_cols:
        with op.batch_alter_table("release_simulation_batches") as batch_op:
            for col in ("job_id", "is_primary", "is_backfill", "population_hash"):
                if col in batch_cols:
                    batch_op.drop_column(col)

    snap_idx = _existing_indexes("release_issue_snapshots")
    for idx in ("ix_release_snapshots_rel_id", "ix_release_snapshots_rel_pophash"):
        if idx in snap_idx:
            op.drop_index(idx, table_name="release_issue_snapshots")

    snap_cols = _existing_columns("release_issue_snapshots")
    if "population_hash" in snap_cols:
        with op.batch_alter_table("release_issue_snapshots") as batch_op:
            batch_op.drop_column("population_hash")

    if is_pg and _existing_columns("release_workflow_state"):
        op.execute(
            "ALTER TABLE release_workflow_state "
            "ALTER COLUMN payload TYPE json USING payload::json"
        )
        op.alter_column(
            "release_workflow_state",
            "key",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
    elif _existing_columns("release_workflow_state"):
        with op.batch_alter_table("release_workflow_state") as batch_op:
            batch_op.alter_column(
                "key",
                existing_type=sa.String(length=128),
                type_=sa.String(length=64),
                existing_nullable=False,
            )
    _ = JSONB
