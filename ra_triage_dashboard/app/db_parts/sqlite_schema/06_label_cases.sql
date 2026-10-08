                CREATE TABLE IF NOT EXISTS label_cases (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    seen_gt_label TEXT NOT NULL DEFAULT '',
                    seen_gt_source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(baseline_scope, issue_id, task_id, source_run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_label_cases_scope_issue
                    ON label_cases(baseline_scope, issue_id, task_id);

                CREATE TABLE IF NOT EXISTS label_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label_case_id TEXT NOT NULL
                        REFERENCES label_cases(id) ON DELETE RESTRICT,
                    expected_output TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    evidence_gaps_json TEXT NOT NULL DEFAULT '[]',
                    rationale TEXT NOT NULL DEFAULT '',
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    revision_kind TEXT NOT NULL DEFAULT 'submission'
                        CHECK(revision_kind IN ('submission', 'adjudication', 'legacy')),
                    supersedes_id INTEGER REFERENCES label_revisions(id),
                    source_annotation_id INTEGER UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_revisions_case_author
                    ON label_revisions(label_case_id, author, id DESC);

                CREATE TABLE IF NOT EXISTS label_attachments (
                    id TEXT PRIMARY KEY,
                    revision_id INTEGER NOT NULL
                        REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_review_attachment_id TEXT UNIQUE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_attachments_revision
                    ON label_attachments(revision_id, created_at);

                CREATE TABLE IF NOT EXISTS label_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label_case_id TEXT NOT NULL
                        REFERENCES label_cases(id) ON DELETE RESTRICT,
                    method TEXT NOT NULL CHECK(method IN ('adjudication')),
                    result_revision_id INTEGER NOT NULL
                        REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    supersedes_id INTEGER REFERENCES label_resolutions(id),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_resolutions_case
                    ON label_resolutions(label_case_id, id DESC);

                CREATE TABLE IF NOT EXISTS issue_label_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    expected_output TEXT NOT NULL CHECK(expected_output IN ('误触发', '正确触发', '无需协助')),
                    source_case_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    supersedes_id INTEGER REFERENCES issue_label_decisions(id) ON DELETE RESTRICT,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(id, baseline_scope, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_issue_label_decisions_scope_issue
                    ON issue_label_decisions(baseline_scope, issue_id, id DESC);
                CREATE TRIGGER IF NOT EXISTS trg_issue_label_decisions_no_update
                    BEFORE UPDATE ON issue_label_decisions
                    BEGIN SELECT RAISE(ABORT, 'Issue label decisions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS trg_issue_label_decisions_no_delete
                    BEFORE DELETE ON issue_label_decisions
                    BEGIN SELECT RAISE(ABORT, 'Issue label decisions are append-only'); END;
