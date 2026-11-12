CREATE TABLE IF NOT EXISTS human_user_roles (
    username TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('rd','te')),
    updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_role_audit (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, old_role TEXT, new_role TEXT NOT NULL,
    actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_vote_roles (
    revision_id BIGINT PRIMARY KEY REFERENCES label_revisions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('rd','te')), captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_assignment_roles (
    campaign_id TEXT NOT NULL, issue_id TEXT NOT NULL, username TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('rd','te')), captured_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id,issue_id,username)
);
CREATE TABLE IF NOT EXISTS human_label_scopes (
    issue_id TEXT PRIMARY KEY REFERENCES issues(issue_id), baseline_scope TEXT NOT NULL,
    dataset_id TEXT NOT NULL, campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id),
    active INTEGER NOT NULL DEFAULT 1, publication_armed INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_label_dirty (
    issue_id TEXT PRIMARY KEY, generation BIGINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS human_publications (
    issue_id TEXT NOT NULL, lane TEXT NOT NULL CHECK(lane IN ('rd','te','arbitrated')),
    generation BIGINT NOT NULL, fingerprint TEXT NOT NULL, desired TEXT,
    conclusion TEXT NOT NULL, source_json TEXT NOT NULL, objection_count INTEGER NOT NULL DEFAULT 0,
    sync_state TEXT NOT NULL, owned INTEGER NOT NULL DEFAULT 0, owned_value TEXT,
    observed_json TEXT NOT NULL DEFAULT '{}', published_generation BIGINT,
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, checked_at TEXT,
    PRIMARY KEY(issue_id,lane)
);
CREATE INDEX IF NOT EXISTS idx_human_publications_due ON human_publications(sync_state,next_attempt);
CREATE TABLE IF NOT EXISTS human_publication_attempts (
    id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, lane TEXT NOT NULL,
    generation BIGINT NOT NULL, action TEXT NOT NULL, before_json TEXT NOT NULL,
    desired TEXT, state TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',
    recovery_attempts INTEGER NOT NULL DEFAULT 0, next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_human_attempt_issue ON human_publication_attempts(issue_id,created_at);
CREATE TABLE IF NOT EXISTS human_version_tasks (
    dataset_id TEXT NOT NULL, cohort TEXT NOT NULL CHECK(cohort IN ('sampling','low')),
    campaign_id TEXT NOT NULL UNIQUE REFERENCES issue_work_splits(id), seed TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(dataset_id,cohort)
);

CREATE TABLE IF NOT EXISTS human_publication_requests (
 id TEXT PRIMARY KEY, actor TEXT NOT NULL, lane TEXT NOT NULL,
 items_json TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at DOUBLE PRECISION NOT NULL, committed_at TEXT
);

CREATE TABLE IF NOT EXISTS human_campaign_redirects (
 campaign_id TEXT NOT NULL, issue_id TEXT NOT NULL, target_campaign_id TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(campaign_id,issue_id)
);
