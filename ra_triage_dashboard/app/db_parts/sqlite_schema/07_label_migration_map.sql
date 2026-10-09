                CREATE TABLE IF NOT EXISTS label_migration_map (
                    source_table TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_table TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_table, source_id, target_table, policy_version)
                );

                CREATE TABLE IF NOT EXISTS label_gt_export_batches (
                    id TEXT PRIMARY KEY,
                    baseline_scopes_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'preview'
                        CHECK(status IN ('preview', 'exported', 'stale')),
                    item_count INTEGER NOT NULL DEFAULT 0,
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    exported_at TEXT,
                    source_gt_snapshot_id TEXT REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
                    source_gt_snapshot_ids_json TEXT NOT NULL DEFAULT '{}',
                    source_gt_snapshot_sha256 TEXT NOT NULL DEFAULT '',
                    reconcile_status TEXT NOT NULL DEFAULT 'not_checked'
                        CHECK(reconcile_status IN ('not_checked', 'matched', 'partial', 'not_applied', 'changed_again', 'error')),
                    reconcile_error TEXT NOT NULL DEFAULT '',
                    reconciled_at TEXT,
                    reconciled_count INTEGER NOT NULL DEFAULT 0,
                    not_applied_count INTEGER NOT NULL DEFAULT 0,
                    changed_again_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS label_gt_export_items (
                    batch_id TEXT NOT NULL
                        REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    old_gt_label TEXT NOT NULL DEFAULT '',
                    expected_output TEXT NOT NULL,
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    decision_id INTEGER REFERENCES issue_label_decisions(id) ON DELETE RESTRICT,
                    reconcile_status TEXT NOT NULL DEFAULT 'not_checked'
                        CHECK(reconcile_status IN ('not_checked', 'matched', 'not_applied', 'changed_again', 'error')),
                    reconciled_snapshot_id TEXT REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
                    reconciled_at TEXT,
                    PRIMARY KEY(batch_id, issue_id)
                );

                CREATE TABLE IF NOT EXISTS label_result_snapshots (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    workset_id TEXT NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
                    workset_members_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    resolved_count INTEGER NOT NULL DEFAULT 0,
                    pending_count INTEGER NOT NULL DEFAULT 0,
                    conflict_count INTEGER NOT NULL DEFAULT 0,
                    stale_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    coverage_status TEXT NOT NULL DEFAULT 'complete'
                        CHECK(coverage_status IN ('complete', 'partial')),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(workset_id, content_sha256),
                    UNIQUE(id, baseline_scope),
                    CHECK(member_count = resolved_count + pending_count + conflict_count + stale_count + unknown_count)
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshots_scope_created
                    ON label_result_snapshots(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS label_result_snapshot_items (
                    snapshot_id TEXT NOT NULL,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    state TEXT NOT NULL CHECK(state IN ('none', 'pending', 'resolved', 'conflict', 'stale')),
                    expected_output TEXT CHECK(expected_output IS NULL OR expected_output IN ('误触发', '正确触发', '无需协助')),
                    method TEXT NOT NULL CHECK(method IN ('single', 'consensus', 'adjudication')),
                    gt_relation TEXT NOT NULL DEFAULT 'unknown'
                        CHECK(gt_relation IN ('matches_gt', 'differs_from_gt', 'fills_missing_gt', 'unknown')),
                    decision_id INTEGER REFERENCES issue_label_decisions(id) ON DELETE RESTRICT,
                    PRIMARY KEY(snapshot_id, issue_id),
                    UNIQUE(snapshot_id, ordinal),
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES label_result_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_items_scope_issue
                    ON label_result_snapshot_items(baseline_scope, issue_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS label_result_snapshot_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL REFERENCES label_result_snapshots(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    label_case_id TEXT NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    resolution_id INTEGER REFERENCES label_resolutions(id) ON DELETE RESTRICT,
                    revision_id INTEGER REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_role TEXT NOT NULL DEFAULT 'head'
                        CHECK(source_role IN ('case', 'head', 'resolution_input', 'resolution_result')),
                    source_key TEXT NOT NULL,
                    UNIQUE(snapshot_id, source_key),
                    FOREIGN KEY(snapshot_id, issue_id)
                        REFERENCES label_result_snapshot_items(snapshot_id, issue_id) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_sources_case
                    ON label_result_snapshot_sources(label_case_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS label_gt_export_source_snapshots (
                    batch_id TEXT NOT NULL
                        REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    PRIMARY KEY(batch_id, baseline_scope),
                    FOREIGN KEY(snapshot_id, baseline_scope, content_sha256)
                        REFERENCES gt_snapshots(id, baseline_scope, content_sha256) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS label_comment_links (
                    comment_id INTEGER PRIMARY KEY
                        REFERENCES review_comments(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    policy_version TEXT NOT NULL,
                    linked_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_comment_links_scope
                    ON label_comment_links(baseline_scope, issue_id, task_id);

                CREATE TABLE IF NOT EXISTS labeling_scope_state (
                    baseline_scope TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'shadow'
                        CHECK(status IN ('shadow', 'active', 'paused')),
                    policy_version TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 0,
                    source_inventory_sha256 TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
