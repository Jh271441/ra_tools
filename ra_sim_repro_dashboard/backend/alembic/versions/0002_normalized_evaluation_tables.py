"""Create normalized evaluation, timing, CQRS read model, release version, and audit tables.

Revision ID: 0002_normalized_evaluation_tables
Revises: 0001_expand_kv_and_indexes
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_normalized_evaluation_tables"
down_revision = "0001_expand_kv_and_indexes"
branch_labels = None
depends_on = None


def _json_type():
    return JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    jt = _json_type()

    if not _has_table("evaluation_scenario_tags"):
        op.create_table(
            "evaluation_scenario_tags",
            sa.Column("context_hash", sa.String(64), primary_key=True),
            sa.Column("issue_id", sa.String(64), primary_key=True),
            sa.Column("plan_id", sa.String(64), nullable=False),
            sa.Column("revision_key", sa.String(128), nullable=False),
            sa.Column("namespace", sa.String(128), nullable=False),
            sa.Column("checked_at", sa.String(64), nullable=False),
            sa.Column("items", jt, nullable=False),
        )
        op.create_index(
            "ix_eval_scene_tags_plan", "evaluation_scenario_tags", ["context_hash", "plan_id"]
        )

    if not _has_table("evaluation_requests"):
        op.create_table(
            "evaluation_requests",
            sa.Column("request_id", sa.String(64), primary_key=True),
            sa.Column("context_hash", sa.String(64), nullable=False),
            sa.Column("release", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(64), nullable=False),
            sa.Column("source_mode", sa.String(32), nullable=False, server_default="database"),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("revision_key", sa.String(128), nullable=True),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("payload", jt, nullable=False),
            sa.Column("requested_at", sa.String(64), nullable=False),
            sa.Column("finished_at", sa.String(64), nullable=True),
        )
        op.create_index(
            "ix_eval_requests_status_req", "evaluation_requests", ["status", "requested_at"]
        )
        op.create_index(
            "ix_eval_requests_ctx_req", "evaluation_requests", ["context_hash", "requested_at"]
        )
        if is_pg:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_eval_requests_active "
                "ON evaluation_requests (status, requested_at DESC) "
                "WHERE status IN ('queued', 'running')"
            )

    if not _has_table("evaluation_revisions"):
        op.create_table(
            "evaluation_revisions",
            sa.Column("revision_key", sa.String(128), primary_key=True),
            sa.Column("context_hash", sa.String(64), nullable=False),
            sa.Column("release", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(64), nullable=False),
            sa.Column("date_start", sa.String(32), nullable=False, server_default=""),
            sa.Column("date_end", sa.String(32), nullable=False, server_default=""),
            sa.Column("config_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("sample_snapshot_id", sa.String(128), nullable=True),
            sa.Column("inventory_identity", sa.String(64), nullable=False, server_default=""),
            sa.Column("summary_payload", jt, nullable=False),
            sa.Column("generated_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_eval_revisions_ctx_gen", "evaluation_revisions", ["context_hash", "generated_at"]
        )
        op.create_index(
            "ix_eval_revisions_rel_prof", "evaluation_revisions", ["release", "profile_id"]
        )

    if not _has_table("evaluation_revision_blobs"):
        op.create_table(
            "evaluation_revision_blobs",
            sa.Column(
                "revision_key",
                sa.String(128),
                sa.ForeignKey("evaluation_revisions.revision_key", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("rows_payload", jt, nullable=False),
            sa.Column("source_payload", jt, nullable=False),
            sa.Column("payload_blob", jt, nullable=False),
            sa.Column("lineage_payload", jt, nullable=False),
        )

    if not _has_table("evaluation_executions"):
        op.create_table(
            "evaluation_executions",
            sa.Column("execution_id", sa.String(64), primary_key=True),
            sa.Column("release", sa.String(64), nullable=False),
            sa.Column("plan_id", sa.String(64), nullable=True),
            sa.Column("job_id", sa.BigInteger(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("metrics_status", sa.String(32), nullable=True),
            sa.Column("audit_hash", sa.String(64), nullable=True),
            sa.Column("contract_hash", sa.String(64), nullable=True),
            sa.Column("meta_payload", jt, nullable=False),
            sa.Column("heavy_payload", jt, nullable=False),
            sa.Column("created_at", sa.String(64), nullable=False, server_default=""),
            sa.Column("finished_at", sa.String(64), nullable=True),
        )
        op.create_index("ix_eval_exec_rel_status", "evaluation_executions", ["release", "status"])
        op.create_index("ix_eval_exec_status", "evaluation_executions", ["status"])
        if is_pg:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_eval_exec_active "
                "ON evaluation_executions (status) "
                "WHERE status IN ('preparing', 'submitting', 'submission_uncertain', 'running', 'verifying')"
            )

    if not _has_table("reproduction_timing_evidence"):
        op.create_table(
            "reproduction_timing_evidence",
            sa.Column("ledger_key", sa.String(128), primary_key=True),
            sa.Column("release", sa.String(64), nullable=False),
            sa.Column("schema_ver", sa.String(32), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("records_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("payload", jt, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_rtime_release", "reproduction_timing_evidence", ["release"])

    if not _has_table("dashboard_read_models"):
        op.create_table(
            "dashboard_read_models",
            sa.Column("cache_key", sa.String(160), primary_key=True),
            sa.Column("scope_release", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("view_type", sa.String(64), nullable=False),
            sa.Column("source_version", sa.String(128), nullable=False),
            sa.Column("payload", jt, nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_read_models_scope", "dashboard_read_models", ["scope_release", "view_type"]
        )

    if not _has_table("release_data_versions"):
        op.create_table(
            "release_data_versions",
            sa.Column("release", sa.String(64), primary_key=True),
            sa.Column("version_seq", sa.BigInteger(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("admin_audit_logs"):
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("actor", sa.String(128), nullable=False),
            sa.Column("identity_source", sa.String(64), nullable=False),
            sa.Column("client_ip", sa.String(64), nullable=False, server_default=""),
            sa.Column("method", sa.String(16), nullable=False),
            sa.Column("path", sa.String(256), nullable=False),
            sa.Column("target_release", sa.String(64), nullable=False, server_default=""),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("detail", jt, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_audit_logs_created", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    for table in (
        "admin_audit_logs",
        "release_data_versions",
        "dashboard_read_models",
        "reproduction_timing_evidence",
        "evaluation_executions",
        "evaluation_revision_blobs",
        "evaluation_revisions",
        "evaluation_requests",
        "evaluation_scenario_tags",
    ):
        if _has_table(table):
            op.drop_table(table)
