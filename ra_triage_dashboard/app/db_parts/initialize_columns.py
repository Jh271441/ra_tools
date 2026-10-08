"""Initialization phase: columns. Uses the caller-owned lock and connection."""
from __future__ import annotations
from .shared import utc_now


def initialize_columns(self, conn) -> None:
    self._ensure_column(
        conn, "intent_experiments", "overlap_reviewers",
        "INTEGER NOT NULL DEFAULT 2",
    )
    self._ensure_column(conn, "annotations", "is_excluded", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "annotations", "missing_evidence_json", "TEXT NOT NULL DEFAULT '[]'")
    self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_id", "TEXT")
    self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_ids_json", "TEXT NOT NULL DEFAULT '{}'")
    self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_sha256", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "label_gt_export_batches", "reconcile_status", "TEXT NOT NULL DEFAULT 'not_checked'")
    self._ensure_column(conn, "label_gt_export_batches", "reconcile_error", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "label_gt_export_batches", "reconciled_at", "TEXT")
    self._ensure_column(conn, "label_gt_export_batches", "reconciled_count", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "label_gt_export_batches", "not_applied_count", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "label_gt_export_batches", "changed_again_count", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "label_gt_export_items", "reconcile_status", "TEXT NOT NULL DEFAULT 'not_checked'")
    self._ensure_column(conn, "label_gt_export_items", "reconciled_snapshot_id", "TEXT")
    self._ensure_column(conn, "label_gt_export_items", "reconciled_at", "TEXT")
    self._ensure_column(conn, "label_result_snapshot_sources", "task_id", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "label_result_snapshot_sources", "source_key", "TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "UPDATE label_result_snapshot_sources SET source_key = 'legacy:' || id WHERE source_key = ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_label_result_snapshot_sources_key "
        "ON label_result_snapshot_sources(snapshot_id, source_key)"
    )
    self._ensure_column(conn, "annotations", "author_source", "TEXT NOT NULL DEFAULT 'legacy'")
    self._ensure_column(conn, "annotations", "author_verified", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "annotations", "mentions_json", "TEXT NOT NULL DEFAULT '[]'")
    self._ensure_column(conn, "mention_users", "display_name", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "intent_case_comments", "mentions_json", "TEXT NOT NULL DEFAULT '[]'")
    self._ensure_column(conn, "access_users", "intent_permission", "TEXT NOT NULL DEFAULT 'manage'")
    self._ensure_column(
        conn, "intent_case_comments", "reply_to_id",
        "INTEGER REFERENCES intent_case_comments(id)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_annotations_issue_run_id "
        "ON annotations(issue_id, model_run_id, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_annotations_work_split_author "
        "ON annotations(issue_id, model_run_id, work_split_id, author, id DESC)"
    )
    if self.backend == "sqlite":
        conn.execute(
            """
                    INSERT OR IGNORE INTO review_work_assignments (
                        split_id, issue_id, assignee, assignment_kind, ordinal,
                        assigned_by, assigned_at
                    )
                    SELECT split_id, issue_id, assignee, 'base', 1,
                           assigned_by, assigned_at
                    FROM issue_work_assignments
                    WHERE split_id <> '' AND assignee <> ''
                    """
        )
    self._ensure_column(conn, "missing_evidence_catalog", "active", "INTEGER NOT NULL DEFAULT 1")
    self._ensure_column(conn, "review_tag_catalog", "hint", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(conn, "review_tag_catalog", "section", "TEXT NOT NULL DEFAULT 'scene'")
    self._ensure_column(conn, "review_tag_catalog", "group_key", "TEXT NOT NULL DEFAULT 'environment'")
    self._ensure_column(conn, "review_tag_catalog", "active", "INTEGER NOT NULL DEFAULT 1")
    self._ensure_column(conn, "model_runs", "kind", "TEXT NOT NULL DEFAULT 'upload'")
    self._ensure_column(conn, "model_runs", "is_default", "INTEGER NOT NULL DEFAULT 0")
    self._ensure_column(conn, "model_runs", "created_by", "TEXT NOT NULL DEFAULT ''")
    self._ensure_column(
        conn, "model_runs", "created_by_source", "TEXT NOT NULL DEFAULT 'legacy'"
    )
    self._ensure_column(
        conn, "model_runs", "created_by_verified", "INTEGER NOT NULL DEFAULT 0"
    )
    self._ensure_column(
        conn, "inference_jobs", "requested_by_source", "TEXT NOT NULL DEFAULT 'legacy'"
    )
    self._ensure_column(
        conn, "inference_jobs", "requested_by_verified", "INTEGER NOT NULL DEFAULT 0"
    )
    self._ensure_column(
        conn,
        "intent_experiments",
        "label_scope",
        "TEXT NOT NULL DEFAULT 'all'",
    )
    self._ensure_column(
        conn,
        "intent_experiments",
        "annotation_status_filter",
        "TEXT NOT NULL DEFAULT 'all'",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "provider_id",
        "TEXT NOT NULL DEFAULT 'kylin'",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "requested_model_id",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "resolved_model_id",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "model_source",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "catalog_sha256",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "model_validation_status",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "prompt_template",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "prompt_template_sha256",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "prompt_mode",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "input_profile",
        "TEXT NOT NULL DEFAULT ''",
    )
    self._ensure_column(
        conn,
        "batch_prediction_jobs",
        "input_config_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_baseline ON issues(baseline_scope)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_annotations_author ON annotations(author)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_runs_created_by ON model_runs(created_by)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_model "
        "ON batch_prediction_jobs(requested_model_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt "
        "ON batch_prediction_jobs(prompt_version, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt_revision "
        "ON batch_prediction_jobs("
        "prompt_version, prompt_mode, prompt_template_sha256, created_at DESC"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_input "
        "ON batch_prediction_jobs(input_profile, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_requested_by ON inference_jobs(requested_by)"
    )
    conn.execute(
        """
                UPDATE inference_jobs
                SET status = 'failed',
                    finished_at = ?,
                    error_text = '服务重启前任务未完成；请重新提交。'
                WHERE status IN ('queued', 'running')
                """,
        (utc_now(),),
    )
