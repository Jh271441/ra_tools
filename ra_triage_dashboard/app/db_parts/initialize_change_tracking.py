"""Initialization phase: change_tracking. Uses the caller-owned lock and connection."""
from __future__ import annotations


def initialize_change_tracking(self, conn) -> None:
    revision_tables = (
        "issues",
        "annotations",
        "review_attachments",
        "model_runs",
        "model_predictions",
        "inference_jobs",
        "batch_prediction_jobs",
        "batch_prediction_items",
        "review_tag_catalog",
        "missing_evidence_catalog",
        "access_users",
        "mention_users",
        "review_comments",
        "comment_attachments",
        "campaign_assignment_audit",
        "campaign_close_snapshots",
        "campaign_close_snapshot_items",
        "campaign_lifecycle_audit",
        "campaign_config_revisions",
        "campaign_config_members",
        "campaign_issue_members",
        "campaign_migration_map",
        "campaign_reference_items",
        "model_review_revisions",
        "model_review_heads",
        "model_review_attachments",
        "issue_work_splits",
        "issue_work_assignments",
        "review_work_assignments",
        "review_work_assignment_changes",
        "review_worksets",
        "review_workset_items",
        "review_workset_scopes",
        "review_task_groups",
        "review_task_group_campaigns",
        "review_task_group_revisions",
        "label_cases",
        "label_revisions",
        "label_attachments",
        "label_resolutions",
        "issue_label_decisions",
        "label_migration_map",
        "label_gt_export_batches",
        "label_gt_export_items",
        "label_gt_export_source_snapshots",
        "label_comment_links",
        "labeling_scope_state",
        "legacy_review_classifications",
        "legacy_read_policies",
        "legacy_shadow_receipts",
        "legacy_exclusion_projection",
        "gt_snapshots",
        "gt_snapshot_items",
        "gt_snapshot_active",
        "label_result_snapshots",
        "label_result_snapshot_items",
        "label_result_snapshot_sources",
        "intent_label_revisions",
        "intent_frame_overrides",
        "intent_label_heads",
        "intent_user_label_heads",
        "intent_label_deletions",
        "intent_case_comments",
        "intent_experiments",
        "intent_experiment_updates",
        "intent_experiment_assignments",
        "trail_issue_exclusion_history",
        "run_collections",
        "run_collection_audit",
        "run_collection_revisions",
        "run_collection_members",
        "run_evaluation_exclusion_snapshots",
        "run_evaluation_exclusion_items",
        "run_evaluation_contexts",
        "run_evaluation_items",
    )
    for table in revision_tables:
        for action in ("insert", "update", "delete"):
            conn.execute(
                f"""
                        CREATE TRIGGER IF NOT EXISTS
                            trg_{table}_{action}_change_revision
                        AFTER {action.upper()} ON {table}
                        BEGIN
                            UPDATE dashboard_change_revision
                            SET revision = revision + 1,
                                updated_at = strftime(
                                    '%Y-%m-%dT%H:%M:%fZ', 'now'
                                )
                            WHERE id = 1;
                        END
                        """
            )
