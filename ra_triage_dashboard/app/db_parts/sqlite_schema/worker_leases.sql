CREATE TABLE IF NOT EXISTS worker_leases (
    lease_key TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    host_name TEXT NOT NULL DEFAULT '',
    pid INTEGER NOT NULL DEFAULT 0,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_leases_expires_at
    ON worker_leases (expires_at);

CREATE INDEX IF NOT EXISTS idx_issues_lower_issue_id
    ON issues (lower(issue_id));

CREATE INDEX IF NOT EXISTS idx_review_comments_issue_created
    ON review_comments (issue_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_intent_case_comments_case_desc
    ON intent_case_comments (dataset_id, case_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_issue_work_splits_lower_name
    ON issue_work_splits (lower(campaign_name));
