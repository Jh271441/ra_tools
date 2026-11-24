BEGIN;

CREATE INDEX IF NOT EXISTS idx_model_review_revisions_issue_id
    ON model_review_revisions (issue_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_model_review_revisions_campaign_id
    ON model_review_revisions (campaign_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_model_review_heads_campaign
    ON model_review_heads (campaign_id, model_run_id, issue_id);

CREATE INDEX IF NOT EXISTS idx_combined_review_progress_lookup
    ON combined_review_progress (campaign_id, issue_id, lower(reviewer));

CREATE INDEX IF NOT EXISTS idx_review_work_assignments_split_lower_assignee
    ON review_work_assignments (split_id, lower(assignee), issue_id);

CREATE INDEX IF NOT EXISTS idx_version_dataset_items_target
    ON version_dataset_items (dataset_id, is_target, issue_id);

CREATE INDEX IF NOT EXISTS idx_version_dataset_items_issue
    ON version_dataset_items (issue_id, dataset_id);

CREATE INDEX IF NOT EXISTS idx_dataset_ingestion_batches_dataset_created
    ON dataset_ingestion_batches (dataset_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_label_revisions_case_lower_author
    ON label_revisions (label_case_id, lower(author), id DESC);

CREATE INDEX IF NOT EXISTS idx_issues_scope_issue
    ON issues (baseline_scope, issue_id);

COMMIT;
