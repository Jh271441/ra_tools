                CREATE TABLE IF NOT EXISTS issue_work_splits (
                    id TEXT PRIMARY KEY,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    seed INTEGER,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    filter_json TEXT NOT NULL DEFAULT '{}',
                    assignees_json TEXT NOT NULL DEFAULT '[]',
                    overlap_ratio REAL NOT NULL DEFAULT 1.0
                        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1),
                    purpose TEXT CHECK(purpose IS NULL OR purpose IN ('labeling', 'model_review')),
                    evaluation_run_id TEXT,
                    reference_type TEXT NOT NULL DEFAULT '',
                    reference_id TEXT NOT NULL DEFAULT '',
                    reference_sha256 TEXT NOT NULL DEFAULT '',
                    lifecycle TEXT NOT NULL DEFAULT 'active'
                        CHECK(lifecycle IN ('draft', 'active', 'closed', 'cancelled', 'superseded')),
                    config_revision INTEGER NOT NULL DEFAULT 1 CHECK(config_revision > 0),
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_by_source TEXT NOT NULL DEFAULT 'legacy',
                    updated_by_verified INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    closed_by TEXT NOT NULL DEFAULT '',
                    closed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    closed_by_verified INTEGER NOT NULL DEFAULT 0,
                    closed_at TEXT,
                    closed_revision INTEGER,
                    legacy_read_only INTEGER NOT NULL DEFAULT 0,
                    legacy_mapping_status TEXT NOT NULL DEFAULT 'not_inventoried',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                    campaign_name TEXT NOT NULL DEFAULT '',
                    task_group_id TEXT,
                    latest_close_snapshot_id TEXT,
                    CHECK((reference_type = '' AND reference_id = '') OR (reference_type <> '' AND reference_id <> '')),
                    CHECK(purpose IS NULL OR
                          (purpose = 'labeling' AND COALESCE(evaluation_run_id, '') = '') OR
                          (purpose = 'model_review' AND COALESCE(TRIM(evaluation_run_id), '') <> ''))
                );

                CREATE TABLE IF NOT EXISTS review_task_groups (
                    id TEXT PRIMARY KEY,
                    purpose TEXT NOT NULL CHECK(purpose IN ('labeling', 'model_review')),
                    name TEXT NOT NULL DEFAULT '',
                    lifecycle TEXT NOT NULL DEFAULT 'draft'
                        CHECK(lifecycle IN ('draft', 'active', 'closed', 'cancelled', 'superseded')),
                    config_revision INTEGER NOT NULL DEFAULT 1 CHECK(config_revision > 0),
                    workset_id TEXT NOT NULL DEFAULT '',
                    source_run_ids_json TEXT NOT NULL DEFAULT '[]',
                    reference_type TEXT NOT NULL DEFAULT '',
                    reference_id TEXT NOT NULL DEFAULT '',
                    reference_sha256 TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_by_source TEXT NOT NULL DEFAULT 'legacy',
                    updated_by_verified INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    closed_by TEXT NOT NULL DEFAULT '',
                    closed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    closed_by_verified INTEGER NOT NULL DEFAULT 0,
                    closed_at TEXT,
                    closed_revision INTEGER,
                    created_at TEXT NOT NULL,
                    CHECK((reference_type = '' AND reference_id = '') OR (reference_type <> '' AND reference_id <> ''))
                );
                CREATE TABLE IF NOT EXISTS review_task_group_campaigns (
                    group_id TEXT NOT NULL REFERENCES review_task_groups(id) ON DELETE RESTRICT,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    evaluation_run_id TEXT NOT NULL DEFAULT '',
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, evaluation_run_id),
                    UNIQUE(campaign_id)
                );
                CREATE TABLE IF NOT EXISTS review_task_group_revisions (
                    group_id TEXT NOT NULL REFERENCES review_task_groups(id) ON DELETE RESTRICT,
                    revision_no INTEGER NOT NULL CHECK(revision_no > 0),
                    config_json TEXT NOT NULL DEFAULT '{}',
                    config_sha256 TEXT NOT NULL,
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    changed_by_verified INTEGER NOT NULL DEFAULT 0,
                    changed_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, revision_no)
                );
                CREATE INDEX IF NOT EXISTS idx_review_task_groups_purpose_lifecycle
                    ON review_task_groups(purpose, lifecycle, created_at DESC);

                CREATE TABLE IF NOT EXISTS review_work_assignments (
                    split_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL,
                    assignment_kind TEXT NOT NULL DEFAULT 'base'
                        CHECK(assignment_kind IN ('base', 'cross', 'full')),
                    ordinal INTEGER NOT NULL DEFAULT 1 CHECK(ordinal > 0),
                    assigned_by TEXT NOT NULL DEFAULT '',
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY(split_id, issue_id, assignee)
                );
                CREATE INDEX IF NOT EXISTS idx_review_work_assignments_assignee
                    ON review_work_assignments(assignee, ordinal);
                CREATE INDEX IF NOT EXISTS idx_review_work_assignments_issue
                    ON review_work_assignments(issue_id, split_id);

                CREATE TABLE IF NOT EXISTS review_work_assignment_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    split_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    from_assignee TEXT NOT NULL,
                    to_assignee TEXT NOT NULL,
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_work_assignment_changes_split
                    ON review_work_assignment_changes(split_id, changed_at DESC);

                CREATE TABLE IF NOT EXISTS review_worksets (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    selection_source_run_id TEXT NOT NULL DEFAULT '',
                    source_filter_json TEXT NOT NULL DEFAULT '{}',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    members_sha256 TEXT NOT NULL,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_worksets_scope_created
                    ON review_worksets(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS review_workset_items (
                    workset_id TEXT NOT NULL
                        REFERENCES review_worksets(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    PRIMARY KEY(workset_id, issue_id),
                    UNIQUE(workset_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_review_workset_items_issue
                    ON review_workset_items(issue_id, workset_id);

                CREATE TABLE IF NOT EXISTS campaign_config_revisions (
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    revision_no INTEGER NOT NULL CHECK(revision_no > 0),
                    purpose TEXT,
                    workset_id TEXT NOT NULL DEFAULT '',
                    evaluation_run_id TEXT,
                    reference_type TEXT NOT NULL DEFAULT '',
                    reference_id TEXT NOT NULL DEFAULT '',
                    lifecycle TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0 CHECK(member_count >= 0),
                    required_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
                    members_sha256 TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    config_sha256 TEXT NOT NULL,
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    changed_by_verified INTEGER NOT NULL DEFAULT 0,
                    change_source TEXT NOT NULL DEFAULT 'user',
                    changed_at TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(campaign_id, revision_no)
                );
                CREATE TABLE IF NOT EXISTS campaign_config_members (
                    campaign_id TEXT NOT NULL,
                    revision_no INTEGER NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    required_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
                    reviewers_per_issue INTEGER NOT NULL DEFAULT 0 CHECK(reviewers_per_issue >= 0),
                    assignment_kinds_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(campaign_id, revision_no, issue_id),
                    UNIQUE(campaign_id, revision_no, ordinal),
                    FOREIGN KEY(campaign_id, revision_no)
                        REFERENCES campaign_config_revisions(campaign_id, revision_no) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_config_members_issue
                    ON campaign_config_members(issue_id, campaign_id, revision_no DESC);
                CREATE TABLE IF NOT EXISTS campaign_issue_members (
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL DEFAULT '',
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    required_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
                    reviewers_per_issue INTEGER NOT NULL DEFAULT 0 CHECK(reviewers_per_issue >= 0),
                    assignment_kinds_json TEXT NOT NULL DEFAULT '[]',
                    config_revision INTEGER NOT NULL DEFAULT 1 CHECK(config_revision > 0),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(campaign_id, issue_id),
                    UNIQUE(campaign_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_issue_members_issue
                    ON campaign_issue_members(issue_id, campaign_id);
                CREATE INDEX IF NOT EXISTS idx_campaign_issue_members_scope
                    ON campaign_issue_members(campaign_id, baseline_scope, ordinal);
                CREATE TABLE IF NOT EXISTS campaign_assignment_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    action TEXT NOT NULL
                        CHECK(action IN ('assigned', 'reassigned', 'unassigned', 'legacy_snapshot')),
                    assignment_kind TEXT NOT NULL DEFAULT 'base',
                    from_assignee TEXT NOT NULL DEFAULT '',
                    to_assignee TEXT NOT NULL DEFAULT '',
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    changed_by_verified INTEGER NOT NULL DEFAULT 0,
                    config_revision INTEGER NOT NULL CHECK(config_revision > 0),
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_close_snapshots (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    config_revision INTEGER NOT NULL CHECK(config_revision > 0),
                    member_count INTEGER NOT NULL DEFAULT 0 CHECK(member_count >= 0),
                    assigned_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(assigned_issue_count >= 0),
                    required_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
                    submitted_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(submitted_submitter_count >= 0),
                    completed_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_issue_count >= 0),
                    pending_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(pending_issue_count >= 0),
                    conflict_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(conflict_issue_count >= 0),
                    adjudicated_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(adjudicated_issue_count >= 0),
                    stale_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(stale_issue_count >= 0),
                    blocked_issue_count INTEGER NOT NULL DEFAULT 0 CHECK(blocked_issue_count >= 0),
                    status_counts_json TEXT NOT NULL DEFAULT '{}',
                    result_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    source_fingerprint TEXT NOT NULL,
                    closed_by TEXT NOT NULL DEFAULT '',
                    closed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    closed_by_verified INTEGER NOT NULL DEFAULT 0,
                    closed_at TEXT NOT NULL,
                    UNIQUE(campaign_id, config_revision)
                );
                CREATE TABLE IF NOT EXISTS campaign_close_snapshot_items (
                    snapshot_id TEXT NOT NULL
                        REFERENCES campaign_close_snapshots(id) ON DELETE RESTRICT,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    required_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
                    submitted_submitter_count INTEGER NOT NULL DEFAULT 0 CHECK(submitted_submitter_count >= 0),
                    result_state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(result_state IN ('pending', 'completed', 'conflict', 'adjudicated', 'stale', 'blocked')),
                    status_counts_json TEXT NOT NULL DEFAULT '{}',
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(snapshot_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_close_snapshot_items_campaign
                    ON campaign_close_snapshot_items(campaign_id, snapshot_id, issue_id);
                CREATE TABLE IF NOT EXISTS campaign_lifecycle_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    action TEXT NOT NULL CHECK(action IN ('closed', 'reopened', 'activated', 'cancelled', 'superseded')),
                    from_lifecycle TEXT NOT NULL,
                    to_lifecycle TEXT NOT NULL,
                    config_revision INTEGER NOT NULL CHECK(config_revision > 0),
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_by_source TEXT NOT NULL DEFAULT 'legacy',
                    changed_by_verified INTEGER NOT NULL DEFAULT 0,
                    snapshot_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_migration_map (
                    source_table TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    purpose TEXT,
                    mapping_status TEXT NOT NULL,
                    mapping_evidence_json TEXT NOT NULL DEFAULT '[]',
                    source_inventory_sha256 TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_table, source_id, policy_version)
                );
                CREATE TABLE IF NOT EXISTS campaign_reference_items (
                    campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    reference_type TEXT NOT NULL
                        CHECK(reference_type IN ('gt_snapshot', 'label_result_snapshot')),
                    reference_id TEXT NOT NULL,
                    reference_sha256 TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(campaign_id, baseline_scope)
                );
