                CREATE TABLE IF NOT EXISTS intent_label_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    routing_default TEXT
                        CHECK(routing_default IS NULL OR routing_default IN (
                            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
                        )),
                    lane_change_default TEXT
                        CHECK(lane_change_default IS NULL OR lane_change_default IN (
                            'lane_change', 'no_lane_change',
                            'left_lane_change', 'right_lane_change'
                        )),
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES intent_label_revisions(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_label_revisions_case
                    ON intent_label_revisions(dataset_id, case_id, id DESC);

                CREATE TABLE IF NOT EXISTS intent_frame_overrides (
                    revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id) ON DELETE CASCADE,
                    timepoint_id TEXT NOT NULL,
                    offset_ms INTEGER NOT NULL,
                    routing_intent TEXT
                        CHECK(routing_intent IS NULL OR routing_intent IN (
                            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
                        )),
                    lane_change_intent TEXT
                        CHECK(lane_change_intent IS NULL OR lane_change_intent IN (
                            'lane_change', 'no_lane_change',
                            'left_lane_change', 'right_lane_change'
                        )),
                    PRIMARY KEY (revision_id, timepoint_id),
                    CHECK(routing_intent IS NOT NULL OR lane_change_intent IS NOT NULL)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_frame_overrides_offset
                    ON intent_frame_overrides(revision_id, offset_ms ASC);

                CREATE TABLE IF NOT EXISTS intent_label_heads (
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    current_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, case_id)
                );
                UPDATE intent_label_revisions
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                UPDATE intent_label_heads
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';

                CREATE TABLE IF NOT EXISTS intent_user_label_heads (
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    current_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, case_id, username)
                );
                UPDATE intent_user_label_heads
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                INSERT OR IGNORE INTO intent_user_label_heads (
                    dataset_id, case_id, username, current_revision_id,
                    version, updated_at
                )
                SELECT head.dataset_id, head.case_id,
                       lower(CASE WHEN revision.author = '' THEN 'legacy' ELSE revision.author END),
                       head.current_revision_id, head.version, head.updated_at
                FROM intent_label_heads head
                JOIN intent_label_revisions revision
                  ON revision.id = head.current_revision_id;

                CREATE TABLE IF NOT EXISTS intent_label_deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    deleted_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    deleted_by TEXT NOT NULL,
                    deleted_by_source TEXT NOT NULL DEFAULT 'legacy',
                    deleted_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_label_deletions_case
                    ON intent_label_deletions(dataset_id, case_id, username, id DESC);

                CREATE TABLE IF NOT EXISTS intent_case_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    reply_to_id INTEGER REFERENCES intent_case_comments(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_case_comments_case
                    ON intent_case_comments(dataset_id, case_id, id ASC);

                CREATE TABLE IF NOT EXISTS intent_comment_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL REFERENCES intent_case_comments(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
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
                CREATE INDEX IF NOT EXISTS idx_intent_comment_notifications_dispatch
                    ON intent_comment_notifications(status, next_attempt_at, id);

                CREATE TABLE IF NOT EXISTS intent_experiments (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    annotation_mode TEXT NOT NULL
                        CHECK(annotation_mode IN ('blind', 'full')),
                    label_scope TEXT NOT NULL DEFAULT 'all'
                        CHECK(label_scope IN ('all', 'routing', 'lane_change')),
                    annotation_status_filter TEXT NOT NULL DEFAULT 'all'
                        CHECK(annotation_status_filter IN ('all', 'labeled', 'unlabeled')),
                    overlap_ratio REAL NOT NULL DEFAULT 0
                        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1),
                    overlap_reviewers INTEGER NOT NULL DEFAULT 2
                        CHECK(overlap_reviewers >= 1),
                    case_count INTEGER NOT NULL DEFAULT 0 CHECK(case_count >= 0),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'closed')),
                    seed INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    closed_by TEXT NOT NULL DEFAULT '',
                    closed_at TEXT,
                    UNIQUE(dataset_id, name)
                );
                UPDATE intent_experiments
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                CREATE INDEX IF NOT EXISTS idx_intent_experiments_dataset
                    ON intent_experiments(dataset_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS intent_experiment_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL
                        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
                    old_name TEXT NOT NULL,
                    new_name TEXT NOT NULL,
                    old_label_scope TEXT NOT NULL,
                    new_label_scope TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_by_source TEXT NOT NULL DEFAULT 'legacy',
                    updated_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_experiment_updates_experiment
                    ON intent_experiment_updates(experiment_id, id DESC);

                CREATE TABLE IF NOT EXISTS intent_experiment_assignments (
                    experiment_id TEXT NOT NULL
                        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
                    username TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    assignment_kind TEXT NOT NULL
                        CHECK(assignment_kind IN ('base', 'cross', 'full')),
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, username, case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_experiment_assignments_user
                    ON intent_experiment_assignments(username, experiment_id, ordinal);
