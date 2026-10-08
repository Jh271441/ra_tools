                CREATE TABLE IF NOT EXISTS model_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL DEFAULT 'v1',
                    kind TEXT NOT NULL DEFAULT 'upload',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    trip_id TEXT NOT NULL DEFAULT '',
                    model_label TEXT NOT NULL DEFAULT '',
                    model_reason TEXT NOT NULL DEFAULT '',
                    model_confidence REAL,
                    model_extra_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(model_run_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_issue_id
                    ON model_predictions(issue_id, model_run_id);

                CREATE TABLE IF NOT EXISTS model_review_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    campaign_id TEXT NOT NULL DEFAULT '',
                    reference_id TEXT NOT NULL DEFAULT '',
                    work_split_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'in_progress', 'completed', 'blocked_by_label')),
                    reason TEXT NOT NULL DEFAULT '',
                    missing_evidence_json TEXT NOT NULL DEFAULT '[]',
                    label_state_fingerprint TEXT NOT NULL DEFAULT '',
                    label_state_json TEXT NOT NULL DEFAULT '{}',
                    reviewer TEXT NOT NULL,
                    reviewer_source TEXT NOT NULL DEFAULT 'legacy',
                    reviewer_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
                    legacy_base_annotation_id INTEGER REFERENCES annotations(id) ON DELETE RESTRICT,
                    legacy_annotation_id INTEGER UNIQUE REFERENCES annotations(id) ON DELETE RESTRICT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_review_revisions_run_issue
                    ON model_review_revisions(model_run_id, issue_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_model_review_revisions_scope_filters
                    ON model_review_revisions(model_run_id, status, reviewer, id DESC);
                CREATE INDEX IF NOT EXISTS idx_model_review_revisions_work_split
                    ON model_review_revisions(work_split_id, model_run_id, issue_id, reviewer, id DESC);

                CREATE TABLE IF NOT EXISTS model_review_heads (
                    model_run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    campaign_id TEXT NOT NULL DEFAULT '',
                    reference_id TEXT NOT NULL DEFAULT '',
                    reviewer TEXT NOT NULL,
                    revision_id INTEGER NOT NULL UNIQUE
                        REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(model_run_id, issue_id, campaign_id, reference_id, reviewer)
                );
                CREATE INDEX IF NOT EXISTS idx_model_review_heads_issue_run
                    ON model_review_heads(issue_id, model_run_id, revision_id DESC);

                CREATE TABLE IF NOT EXISTS model_review_attachments (
                    id TEXT PRIMARY KEY,
                    revision_id INTEGER NOT NULL
                        REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    width INTEGER NOT NULL CHECK(width > 0),
                    height INTEGER NOT NULL CHECK(height > 0),
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_review_attachments_revision
                    ON model_review_attachments(revision_id, created_at);

                CREATE TABLE IF NOT EXISTS combined_review_submissions (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL DEFAULT '',
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    reviewer TEXT NOT NULL,
                    model_run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
                    model_review_revision_id INTEGER NOT NULL REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
                    label_case_id TEXT NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
                    label_revision_id INTEGER REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    acknowledged_label_revision_id INTEGER REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    case_action TEXT NOT NULL CHECK(case_action IN ('submitted', 'acknowledged')),
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL,
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_at TEXT NOT NULL,
                    UNIQUE(campaign_id, issue_id, reviewer, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_combined_review_submissions_campaign
                    ON combined_review_submissions(campaign_id, reviewer, issue_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS combined_review_progress (
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    reviewer TEXT NOT NULL,
                    model_review_submitted INTEGER NOT NULL DEFAULT 0,
                    case_label_acknowledged INTEGER NOT NULL DEFAULT 0,
                    model_review_revision_id INTEGER REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
                    case_label_revision_id INTEGER REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    submission_group_id TEXT REFERENCES combined_review_submissions(id) ON DELETE RESTRICT,
                    model_review_submitted_at TEXT,
                    case_label_acknowledged_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(campaign_id, issue_id, reviewer)
                );
                CREATE INDEX IF NOT EXISTS idx_combined_review_progress_campaign
                    ON combined_review_progress(campaign_id, reviewer, model_review_submitted, case_label_acknowledged);

                CREATE VIEW IF NOT EXISTS review_records AS
                SELECT
                    annotation.id AS id,
                    annotation.issue_id,
                    annotation.model_run_id,
                    annotation.work_split_id,
                    annotation.label,
                    annotation.review_status,
                    annotation.is_excluded,
                    annotation.tags_json,
                    annotation.missing_evidence_json,
                    annotation.mentions_json,
                    annotation.note,
                    annotation.author,
                    annotation.author_source,
                    annotation.author_verified,
                    annotation.supersedes_id,
                    annotation.created_at,
                    'legacy' AS review_domain,
                    '' AS model_review_status,
                    '' AS campaign_id,
                    '' AS reference_id,
                    annotation.id AS storage_id
                FROM annotations annotation
                UNION ALL
                SELECT
                    4000000000000000 + revision.id AS id,
                    revision.issue_id,
                    revision.model_run_id,
                    revision.work_split_id,
                    NULL AS label,
                    CASE revision.status
                        WHEN 'completed' THEN 'reviewed'
                        WHEN 'blocked_by_label' THEN 'needs_gt_review'
                        ELSE 'pending'
                    END AS review_status,
                    0 AS is_excluded,
                    '[]' AS tags_json,
                    revision.missing_evidence_json,
                    '[]' AS mentions_json,
                    revision.reason AS note,
                    revision.reviewer AS author,
                    revision.reviewer_source AS author_source,
                    revision.reviewer_verified AS author_verified,
                    CASE
                        WHEN revision.supersedes_id IS NOT NULL
                            THEN 4000000000000000 + revision.supersedes_id
                        ELSE revision.legacy_base_annotation_id
                    END AS supersedes_id,
                    revision.created_at,
                    'model_review' AS review_domain,
                    revision.status AS model_review_status,
                    revision.campaign_id,
                    revision.reference_id,
                    revision.id AS storage_id
                FROM model_review_revisions revision;

                CREATE VIEW IF NOT EXISTS review_record_attachments AS
                SELECT
                    attachment.id,
                    attachment.annotation_id,
                    attachment.original_name,
                    attachment.stored_name,
                    attachment.media_type,
                    attachment.size_bytes,
                    attachment.width,
                    attachment.height,
                    attachment.sha256,
                    attachment.created_at,
                    'legacy' AS review_domain,
                    attachment.annotation_id AS storage_revision_id
                FROM review_attachments attachment
                UNION ALL
                SELECT
                    attachment.id,
                    4000000000000000 + attachment.revision_id AS annotation_id,
                    attachment.original_name,
                    attachment.stored_name,
                    attachment.media_type,
                    attachment.size_bytes,
                    attachment.width,
                    attachment.height,
                    attachment.sha256,
                    attachment.created_at,
                    'model_review' AS review_domain,
                    attachment.revision_id AS storage_revision_id
                FROM model_review_attachments attachment;
