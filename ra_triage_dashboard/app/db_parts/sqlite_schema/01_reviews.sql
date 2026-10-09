
                CREATE TABLE IF NOT EXISTS issues (
                    issue_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    scenario TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT '',
                    trail_url TEXT NOT NULL DEFAULT '',
                    gt_label TEXT,
                    gt_source TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    baseline_scope TEXT NOT NULL DEFAULT '',
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    model_run_id TEXT NOT NULL DEFAULT '',
                    work_split_id TEXT NOT NULL DEFAULT '',
                    label TEXT,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    missing_evidence_json TEXT NOT NULL DEFAULT '[]',
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES annotations(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotations_issue_id
                    ON annotations(issue_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_annotations_issue_run_id
                    ON annotations(issue_id, model_run_id, id DESC);

                CREATE TABLE IF NOT EXISTS review_attachments (
                    id TEXT PRIMARY KEY,
                    annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_attachments_annotation
                    ON review_attachments(annotation_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS review_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    message_unique_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(annotation_id, recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_review_notifications_dispatch
                    ON review_notifications(status, next_attempt_at, id);

                CREATE TABLE IF NOT EXISTS review_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    model_run_id TEXT NOT NULL DEFAULT '',
                    discussion_channel TEXT NOT NULL DEFAULT 'legacy'
                        CHECK(discussion_channel IN ('case', 'campaign', 'model_review', 'legacy')),
                    campaign_id TEXT NOT NULL DEFAULT '',
                    baseline_scope TEXT NOT NULL DEFAULT '',
                    evaluation_run_id TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    reply_to_id INTEGER REFERENCES review_comments(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_comments_thread
                    ON review_comments(issue_id, model_run_id, id ASC);

                CREATE TABLE IF NOT EXISTS comment_attachments (
                    id TEXT PRIMARY KEY,
                    comment_id INTEGER NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_comment_attachments_comment
                    ON comment_attachments(comment_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS comment_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    message_unique_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(comment_id, recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_comment_notifications_dispatch
                    ON comment_notifications(status, next_attempt_at, id);
