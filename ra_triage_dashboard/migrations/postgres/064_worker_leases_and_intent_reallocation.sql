-- Phase 4A + Intent Experiment Reallocation (062 convergence) + residual search indexes.
-- Strictly additive and idempotent on both production (8785) and PRE (8786).
BEGIN;

CREATE TABLE IF NOT EXISTS worker_leases (
    lease_key TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    host_name TEXT NOT NULL DEFAULT '',
    pid INTEGER NOT NULL DEFAULT 0,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    renewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_leases_expires_at
    ON worker_leases (expires_at);

ALTER TABLE intent_experiments
    ADD COLUMN IF NOT EXISTS members_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE intent_experiment_updates
    ADD COLUMN IF NOT EXISTS old_allocation_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE intent_experiment_updates
    ADD COLUMN IF NOT EXISTS new_allocation_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_issues_lower_issue_id
    ON issues (lower(issue_id));

CREATE INDEX IF NOT EXISTS idx_review_comments_issue_created
    ON review_comments (issue_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_intent_case_comments_case_desc
    ON intent_case_comments (dataset_id, case_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_issue_work_splits_lower_name
    ON issue_work_splits (lower(campaign_name));

COMMIT;
