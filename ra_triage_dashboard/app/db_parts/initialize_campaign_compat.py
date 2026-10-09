"""Initialization phase: campaign_compat. Uses the caller-owned lock and connection."""
from __future__ import annotations


def initialize_campaign_compat(self, conn) -> None:
    self._ensure_column(conn, "issues", "baseline_scope", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "review_worksets", "scope_mode", "TEXT NOT NULL DEFAULT 'single'")
    self._ensure_column(conn, "review_worksets", "scope_count", "INTEGER NOT NULL DEFAULT 1")
    self._ensure_column(conn, "review_worksets", "scopes_sha256", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "review_worksets", "selection_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_state", "TEXT NOT NULL DEFAULT 'none'")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_expected_output", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_gt_relation", "TEXT NOT NULL DEFAULT 'unknown'")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_method", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_source_json", "TEXT NOT NULL DEFAULT '{}'")
    self._ensure_column(conn, "run_evaluation_items", "shared_label_sha256", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "label_result_snapshot_items", "decision_id", "INTEGER REFERENCES issue_label_decisions(id)")
    self._ensure_column(conn, "label_gt_export_items", "decision_id", "INTEGER REFERENCES issue_label_decisions(id)")
    self._ensure_column(conn, "annotations", "review_status", "TEXT NOT NULL DEFAULT 'pending'")
    self._ensure_column(conn, "annotations", "model_run_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "annotations", "work_split_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "mode", "TEXT NOT NULL DEFAULT 'single'")
    self._ensure_column(conn, "issue_work_splits", "reviewers_per_issue", "INTEGER NOT NULL DEFAULT 1")
    self._ensure_column(conn, "issue_work_splits", "model_run_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "assignment_count", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "issue_work_splits", "overlap_ratio", "REAL NOT NULL DEFAULT 1.0")
    self._ensure_column(conn, "issue_work_splits", "task_kind", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "issue_work_splits", "workset_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "selection_source_run_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "purpose", "TEXT")
    self._ensure_column(conn, "issue_work_splits", "evaluation_run_id", "TEXT")
    self._ensure_column(conn, "issue_work_splits", "reference_type", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "reference_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "reference_sha256", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "lifecycle", "TEXT NOT NULL DEFAULT 'active'")
    self._ensure_column(conn, "issue_work_splits", "config_revision", "INTEGER NOT NULL DEFAULT 1")
    self._ensure_column(conn, "issue_work_splits", "created_by_source", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "issue_work_splits", "created_by_verified", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "issue_work_splits", "updated_by", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "updated_by_source", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "issue_work_splits", "updated_by_verified", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "issue_work_splits", "updated_at", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "closed_by", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "closed_by_source", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "issue_work_splits", "closed_by_verified", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "issue_work_splits", "closed_at", "TEXT")
    self._ensure_column(conn, "issue_work_splits", "closed_revision", "INTEGER")
    self._ensure_column(conn, "issue_work_splits", "legacy_read_only", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "issue_work_splits", "legacy_mapping_status", "TEXT NOT NULL DEFAULT 'not_inventoried'")
    self._ensure_column(conn, "issue_work_splits", "idempotency_key", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "idempotency_fingerprint", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "campaign_name", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "issue_work_splits", "workflow_mode", "TEXT NOT NULL DEFAULT 'model_review_only'")
    self._ensure_column(conn, "issue_work_splits", "task_group_id", "TEXT")
    self._ensure_column(conn, "issue_work_splits", "latest_close_snapshot_id", "TEXT")
    self._ensure_column(
        conn, "campaign_assignment_audit", "idempotency_fingerprint",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn, "campaign_close_snapshots", "blocked_issue_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    self._ensure_column(conn, "review_comments", "discussion_channel", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "review_comments", "campaign_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "review_comments", "baseline_scope", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "review_comments", "evaluation_run_id", "TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
                UPDATE review_comments
                SET discussion_channel = 'model_review',
                    evaluation_run_id = model_run_id,
                    baseline_scope = COALESCE((
                        SELECT issue.baseline_scope FROM issues issue
                        WHERE issue.issue_id = review_comments.issue_id
                    ), '')
                WHERE discussion_channel = 'legacy'
                  AND model_run_id <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM label_comment_links link
                      WHERE link.comment_id = review_comments.id
                  )
                """
    )
    conn.execute(
        """
                UPDATE review_comments
                SET discussion_channel = CASE
                        WHEN COALESCE((SELECT link.task_id FROM label_comment_links link
                                       WHERE link.comment_id = review_comments.id), '') <> ''
                        THEN 'campaign' ELSE 'case' END,
                    campaign_id = COALESCE((SELECT link.task_id FROM label_comment_links link
                                            WHERE link.comment_id = review_comments.id), ''),
                    baseline_scope = COALESCE((SELECT link.baseline_scope FROM label_comment_links link
                                               WHERE link.comment_id = review_comments.id), ''),
                    evaluation_run_id = ''
                WHERE discussion_channel = 'legacy'
                  AND EXISTS (
                      SELECT 1 FROM label_comment_links link
                      WHERE link.comment_id = review_comments.id
                  )
                """
    )
    conn.execute(
        """
                UPDATE review_comments
                SET discussion_channel = 'case',
                    baseline_scope = COALESCE((
                        SELECT issue.baseline_scope FROM issues issue
                        WHERE issue.issue_id = review_comments.issue_id
                    ), '')
                WHERE discussion_channel = 'legacy' AND model_run_id = ''
                """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_work_splits_campaign_listing "
        "ON issue_work_splits(purpose, lifecycle, created_at DESC, id DESC)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_issue_work_splits_idempotency "
        "ON issue_work_splits(idempotency_key) WHERE idempotency_key <> ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_review_task_groups_idempotency "
        "ON review_task_groups(idempotency_key) WHERE idempotency_key <> ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_assignment_audit_idempotency "
        "ON campaign_assignment_audit(campaign_id, idempotency_key) WHERE idempotency_key <> ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_lifecycle_audit_idempotency "
        "ON campaign_lifecycle_audit(campaign_id, idempotency_key) WHERE idempotency_key <> ''"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_lifecycle_audit_campaign "
        "ON campaign_lifecycle_audit(campaign_id, changed_at DESC, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_config_revisions_created "
        "ON campaign_config_revisions(campaign_id, revision_no DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_assignment_audit_issue "
        "ON campaign_assignment_audit(campaign_id, issue_id, changed_at DESC, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_close_snapshots_created "
        "ON campaign_close_snapshots(campaign_id, closed_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_migration_map_campaign "
        "ON campaign_migration_map(campaign_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_reference_items_scope "
        "ON campaign_reference_items(baseline_scope, campaign_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_comments_case_channel "
        "ON review_comments(baseline_scope, issue_id, discussion_channel, id ASC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_comments_campaign_channel "
        "ON review_comments(campaign_id, issue_id, id ASC) WHERE discussion_channel = 'campaign'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_comments_run_channel "
        "ON review_comments(evaluation_run_id, issue_id, id ASC) WHERE discussion_channel = 'model_review'"
    )
    for table in (
        "campaign_config_revisions",
        "campaign_config_members",
        "campaign_assignment_audit",
        "campaign_close_snapshots",
        "campaign_close_snapshot_items",
        "campaign_lifecycle_audit",
        "campaign_migration_map",
        "review_task_group_revisions",
    ):
        for action in ("UPDATE", "DELETE"):
            conn.execute(
                f"""
                        CREATE TRIGGER IF NOT EXISTS trg_{table}_{action.lower()}_immutable
                        BEFORE {action} ON {table}
                        BEGIN
                            SELECT RAISE(ABORT, 'campaign audit and close snapshots are append-only');
                        END
                        """
            )
    for action, operation, split_column in (
        ("insert", "INSERT", "NEW.split_id"),
        ("delete", "DELETE", "OLD.split_id"),
    ):
        conn.execute(
            f"""
                    CREATE TRIGGER IF NOT EXISTS trg_review_work_assignments_closed_{action}
                    BEFORE {operation} ON review_work_assignments
                    WHEN EXISTS (
                        SELECT 1 FROM issue_work_splits
                        WHERE id = {split_column} AND lifecycle = 'closed'
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'closed Campaign membership is immutable');
                    END
                    """
        )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_review_work_assignments_closed_update
                BEFORE UPDATE ON review_work_assignments
                WHEN EXISTS (SELECT 1 FROM issue_work_splits WHERE id = OLD.split_id AND lifecycle = 'closed')
                  OR EXISTS (SELECT 1 FROM issue_work_splits WHERE id = NEW.split_id AND lifecycle = 'closed')
                BEGIN
                    SELECT RAISE(ABORT, 'closed Campaign membership is immutable');
                END
                """
    )
    for action, operation, campaign_column in (
        ("insert", "INSERT", "NEW.campaign_id"),
        ("delete", "DELETE", "OLD.campaign_id"),
    ):
        conn.execute(
            f"""
                    CREATE TRIGGER IF NOT EXISTS trg_campaign_issue_members_closed_{action}
                    BEFORE {operation} ON campaign_issue_members
                    WHEN EXISTS (
                        SELECT 1 FROM issue_work_splits
                        WHERE id = {campaign_column} AND lifecycle = 'closed'
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'closed Campaign member snapshot is immutable');
                    END
                    """
        )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_campaign_issue_members_closed_update
                BEFORE UPDATE ON campaign_issue_members
                WHEN EXISTS (SELECT 1 FROM issue_work_splits WHERE id = OLD.campaign_id AND lifecycle = 'closed')
                  OR EXISTS (SELECT 1 FROM issue_work_splits WHERE id = NEW.campaign_id AND lifecycle = 'closed')
                BEGIN
                    SELECT RAISE(ABORT, 'closed Campaign member snapshot is immutable');
                END
                """
    )
    for action, operation in (("insert", "INSERT"), ("update", "UPDATE")):
        conn.execute(
            f"""
                    CREATE TRIGGER IF NOT EXISTS trg_issue_work_splits_campaign_check_{action}
                    BEFORE {operation} ON issue_work_splits
                    WHEN (NEW.purpose IS NOT NULL AND NEW.purpose NOT IN ('labeling', 'model_review'))
                      OR NEW.lifecycle NOT IN ('draft', 'active', 'closed', 'cancelled', 'superseded')
                      OR NEW.config_revision < 1
                      OR (NEW.purpose = 'labeling' AND COALESCE(TRIM(NEW.evaluation_run_id), '') <> '')
                      OR (NEW.purpose = 'model_review' AND COALESCE(TRIM(NEW.evaluation_run_id), '') = '')
                      OR ((NEW.reference_type = '') <> (NEW.reference_id = ''))
                    BEGIN
                        SELECT RAISE(ABORT, 'Campaign purpose, lifecycle, revision, Run or reference is invalid');
                    END
                    """
        )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_issue_work_splits_reopen_revision
                BEFORE UPDATE ON issue_work_splits
                WHEN OLD.lifecycle = 'closed' AND NEW.lifecycle <> 'closed'
                  AND NEW.config_revision <= OLD.config_revision
                BEGIN
                    SELECT RAISE(ABORT, 'reopening a closed Campaign requires a new config revision');
                END
                """
    )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_issue_work_splits_closed_config_guard
                BEFORE UPDATE ON issue_work_splits
                WHEN OLD.lifecycle = 'closed' AND (
                    (NEW.lifecycle = 'closed' AND (
                        NEW.purpose IS NOT OLD.purpose
                        OR NEW.evaluation_run_id IS NOT OLD.evaluation_run_id
                        OR NEW.reference_type IS NOT OLD.reference_type
                        OR NEW.reference_id IS NOT OLD.reference_id
                        OR NEW.reference_sha256 IS NOT OLD.reference_sha256
                        OR NEW.workset_id IS NOT OLD.workset_id
                        OR NEW.selection_source_run_id IS NOT OLD.selection_source_run_id
                        OR NEW.campaign_name IS NOT OLD.campaign_name
                        OR NEW.task_group_id IS NOT OLD.task_group_id
                        OR NEW.mode IS NOT OLD.mode
                        OR NEW.model_run_id IS NOT OLD.model_run_id
                        OR NEW.total_count <> OLD.total_count
                        OR NEW.assignment_count <> OLD.assignment_count
                        OR NEW.reviewers_per_issue <> OLD.reviewers_per_issue
                        OR NEW.overlap_ratio <> OLD.overlap_ratio
                        OR NEW.assignees_json IS NOT OLD.assignees_json
                        OR NEW.closed_by IS NOT OLD.closed_by
                        OR NEW.closed_by_source IS NOT OLD.closed_by_source
                        OR NEW.closed_by_verified <> OLD.closed_by_verified
                        OR NEW.closed_at IS NOT OLD.closed_at
                        OR NEW.closed_revision IS NOT OLD.closed_revision
                        OR NEW.latest_close_snapshot_id IS NOT OLD.latest_close_snapshot_id
                        OR NEW.config_revision <> OLD.config_revision
                    ))
                    OR (NEW.lifecycle <> 'closed' AND (
                        NEW.lifecycle <> 'active'
                        OR NEW.config_revision <= OLD.config_revision
                    ))
                )
                BEGIN
                    SELECT RAISE(ABORT, 'closed Campaign configuration is immutable; reopen with a new revision');
                END
                """
    )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_issue_work_splits_lifecycle_transition
                BEFORE UPDATE OF lifecycle ON issue_work_splits
                WHEN NEW.lifecycle <> OLD.lifecycle
                BEGIN
                    SELECT CASE WHEN NOT (
                        (OLD.lifecycle = 'draft' AND NEW.lifecycle = 'active' AND NEW.config_revision > OLD.config_revision)
                        OR (OLD.lifecycle = 'draft' AND NEW.lifecycle = 'cancelled' AND NEW.config_revision > OLD.config_revision)
                        OR (OLD.lifecycle = 'active' AND NEW.lifecycle = 'cancelled' AND NEW.config_revision > OLD.config_revision)
                        OR (OLD.lifecycle = 'active' AND NEW.lifecycle = 'superseded' AND NEW.config_revision > OLD.config_revision)
                        OR (OLD.lifecycle = 'active' AND NEW.lifecycle = 'closed'
                            AND NEW.config_revision = OLD.config_revision
                            AND NEW.closed_revision = OLD.config_revision
                            AND COALESCE(NEW.latest_close_snapshot_id, '') <> '')
                        OR (OLD.lifecycle = 'closed' AND NEW.lifecycle = 'active' AND NEW.config_revision > OLD.config_revision)
                    ) THEN RAISE(ABORT, 'illegal Campaign lifecycle transition or revision') END;
                    SELECT CASE WHEN NOT EXISTS (
                        SELECT 1 FROM campaign_lifecycle_audit audit
                        WHERE audit.campaign_id = OLD.id
                          AND audit.from_lifecycle = OLD.lifecycle
                          AND audit.to_lifecycle = NEW.lifecycle
                          AND audit.action = CASE
                              WHEN OLD.lifecycle = 'draft' AND NEW.lifecycle = 'active' THEN 'activated'
                              WHEN NEW.lifecycle = 'cancelled' THEN 'cancelled'
                              WHEN NEW.lifecycle = 'superseded' THEN 'superseded'
                              WHEN NEW.lifecycle = 'closed' THEN 'closed'
                              WHEN OLD.lifecycle = 'closed' AND NEW.lifecycle = 'active' THEN 'reopened'
                              ELSE '' END
                          AND audit.config_revision = CASE
                              WHEN NEW.lifecycle = 'closed' THEN OLD.config_revision
                              ELSE NEW.config_revision END
                          AND audit.idempotency_key <> ''
                    ) THEN RAISE(ABORT, 'Campaign lifecycle transition requires a matching audit row') END;
                END
                """
    )
    conn.execute(
        """
                CREATE TRIGGER IF NOT EXISTS trg_issue_work_splits_terminal_lifecycle_guard
                BEFORE UPDATE ON issue_work_splits
                WHEN OLD.lifecycle IN ('cancelled', 'superseded')
                BEGIN
                    SELECT RAISE(ABORT, 'terminal Campaign cannot be modified');
                END
                """
    )
    for table, column in (
        ("review_work_assignments", "split_id"),
        ("campaign_issue_members", "campaign_id"),
    ):
        for action, operation, source_expr, target_expr in (
            ("insert", "INSERT", "", f"NEW.{column}"),
            ("delete", "DELETE", f"OLD.{column}", ""),
            ("update", "UPDATE", f"OLD.{column}", f"NEW.{column}"),
        ):
            checks = []
            if source_expr:
                checks.append(
                    f"EXISTS (SELECT 1 FROM issue_work_splits WHERE id = {source_expr} "
                    "AND lifecycle IN ('closed', 'cancelled', 'superseded'))"
                )
            if target_expr:
                checks.append(
                    f"EXISTS (SELECT 1 FROM issue_work_splits WHERE id = {target_expr} "
                    "AND lifecycle IN ('closed', 'cancelled', 'superseded'))"
                )
            conn.execute(
                f"""
                        CREATE TRIGGER IF NOT EXISTS trg_{table}_terminal_{action}
                        BEFORE {operation} ON {table}
                        WHEN {' OR '.join(checks)}
                        BEGIN
                            SELECT RAISE(ABORT, 'terminal Campaign membership is immutable');
                        END
                        """
            )
    for action, operation in (("insert", "INSERT"), ("update", "UPDATE")):
        conn.execute(
            f"""
                    CREATE TRIGGER IF NOT EXISTS trg_review_comments_discussion_check_{action}
                    BEFORE {operation} ON review_comments
                    WHEN NEW.discussion_channel NOT IN ('case', 'campaign', 'model_review', 'legacy')
                      OR (NEW.discussion_channel = 'campaign' AND NEW.campaign_id = '')
                      OR (NEW.discussion_channel = 'model_review' AND NEW.evaluation_run_id = '')
                      OR (NEW.discussion_channel IN ('case', 'campaign') AND NEW.evaluation_run_id <> '')
                      OR (NEW.discussion_channel IN ('case', 'model_review', 'legacy') AND NEW.campaign_id <> '')
                    BEGIN
                        SELECT RAISE(ABORT, 'discussion channel scope is invalid');
                    END
                    """
        )
