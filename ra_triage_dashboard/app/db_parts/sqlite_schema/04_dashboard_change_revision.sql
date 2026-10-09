                CREATE TABLE IF NOT EXISTS dashboard_change_revision (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO dashboard_change_revision (
                    id, revision, updated_at
                ) VALUES (1, 0, '');

                CREATE TABLE IF NOT EXISTS dashboard_change_topics (
                    topic TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS gt_sync_state (
                    baseline_scope TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'not_started',
                    source_name TEXT NOT NULL DEFAULT 'Trail',
                    source_view_id INTEGER NOT NULL DEFAULT 1000,
                    source_field TEXT NOT NULL DEFAULT 'ra_merge_result',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    source_row_count INTEGER NOT NULL DEFAULT 0,
                    source_updated_at TEXT,
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT,
                    last_applied_at TEXT,
                    last_check_change_count INTEGER NOT NULL DEFAULT 0,
                    last_applied_change_count INTEGER NOT NULL DEFAULT 0,
                    last_trigger TEXT NOT NULL DEFAULT '',
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT '',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS gt_sync_labels (
                    baseline_scope TEXT NOT NULL REFERENCES gt_sync_state(baseline_scope)
                        ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    gt_label TEXT NOT NULL CHECK(gt_label IN ('误触发', '正确触发', '无需协助')),
                    source_updated_at TEXT,
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (baseline_scope, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_gt_sync_labels_issue
                    ON gt_sync_labels(issue_id, baseline_scope);

                CREATE TABLE IF NOT EXISTS gt_snapshots (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    gt_mode TEXT NOT NULL CHECK(gt_mode IN ('strict', 'sparse')),
                    source_name TEXT NOT NULL DEFAULT 'Trail',
                    source_view_id INTEGER NOT NULL DEFAULT 0,
                    source_field TEXT NOT NULL DEFAULT '',
                    source_metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_sha256 TEXT NOT NULL,
                    membership_sha256 TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    valid_label_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'system',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(baseline_scope, content_sha256),
                    UNIQUE(id, baseline_scope),
                    UNIQUE(id, baseline_scope, content_sha256),
                    CHECK(valid_label_count <= member_count)
                );
                CREATE INDEX IF NOT EXISTS idx_gt_snapshots_scope_created
                    ON gt_snapshots(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS gt_snapshot_items (
                    snapshot_id TEXT NOT NULL,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    gt_label TEXT NOT NULL DEFAULT '' CHECK(gt_label IN ('', '误触发', '正确触发', '无需协助')),
                    source_updated_at TEXT NOT NULL DEFAULT '',
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(snapshot_id, issue_id),
                    UNIQUE(snapshot_id, ordinal),
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_gt_snapshot_items_scope_issue
                    ON gt_snapshot_items(baseline_scope, issue_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS gt_snapshot_active (
                    baseline_scope TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    activated_by TEXT NOT NULL DEFAULT '',
                    activated_by_source TEXT NOT NULL DEFAULT 'system',
                    activated_by_verified INTEGER NOT NULL DEFAULT 0,
                    activation_reason TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS review_tag_catalog (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    hint TEXT NOT NULL DEFAULT '',
                    section TEXT NOT NULL DEFAULT 'scene',
                    group_key TEXT NOT NULL DEFAULT 'environment',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS missing_evidence_catalog (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    hint TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS access_users (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('writer', 'admin')),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mention_users (
                    username TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
