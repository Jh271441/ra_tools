                CREATE TABLE IF NOT EXISTS legacy_review_classifications (
                    source_annotation_id INTEGER NOT NULL,
                    baseline_scope TEXT NOT NULL,
                    classification TEXT NOT NULL CHECK(classification IN (
                        'model_review_mapped', 'label_history_mapped', 'legacy_mixed',
                        'legacy_unbound_history', 'legacy_task_history'
                    )),
                    target_domain_type TEXT NOT NULL DEFAULT '',
                    target_domain_id TEXT NOT NULL DEFAULT '',
                    policy_version TEXT NOT NULL,
                    inventory_sha256 TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_annotation_id, policy_version)
                );
                CREATE INDEX IF NOT EXISTS idx_legacy_review_classifications_scope
                    ON legacy_review_classifications(baseline_scope, classification, source_annotation_id);
                CREATE TABLE IF NOT EXISTS legacy_read_policies (
                    baseline_scope TEXT PRIMARY KEY,
                    policy TEXT NOT NULL CHECK(policy IN ('legacy', 'shadow', 'canonical')),
                    epoch INTEGER NOT NULL DEFAULT 0,
                    policy_version TEXT NOT NULL DEFAULT '',
                    inventory_sha256 TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    last_receipt_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS legacy_shadow_receipts (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    component TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    inventory_sha256 TEXT NOT NULL DEFAULT '',
                    legacy_count INTEGER NOT NULL DEFAULT 0,
                    canonical_count INTEGER NOT NULL DEFAULT 0,
                    diff_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pass' CHECK(status IN ('pass', 'expected_diff', 'fail')),
                    expected_diff_json TEXT NOT NULL DEFAULT '[]',
                    diff_json TEXT NOT NULL DEFAULT '[]',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_legacy_shadow_receipts_scope
                    ON legacy_shadow_receipts(baseline_scope, component, created_at DESC);
                CREATE TABLE IF NOT EXISTS legacy_exclusion_projection (
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    state TEXT NOT NULL CHECK(state IN ('none', 'candidate', 'excluded', 'conflict', 'stale')),
                    source_domain TEXT NOT NULL DEFAULT '',
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    content_sha256 TEXT NOT NULL,
                    policy_version TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(baseline_scope, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_legacy_exclusion_projection_state
                    ON legacy_exclusion_projection(baseline_scope, state, issue_id);

                CREATE TABLE IF NOT EXISTS label_import_batches (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type = 'legacy_model_review'),
                    migration_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('importing', 'imported')),
                    source_inventory_sha256 TEXT NOT NULL,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    imported_by TEXT NOT NULL DEFAULT 'migration',
                    created_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    UNIQUE(baseline_scope, source_type, migration_version)
                );
                CREATE INDEX IF NOT EXISTS idx_label_import_batches_scope
                    ON label_import_batches(baseline_scope, imported_at DESC);
                CREATE TABLE IF NOT EXISTS label_import_votes (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
                    label_case_id TEXT NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
                    label_revision_id INTEGER NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    reviewer TEXT NOT NULL,
                    normalized_reviewer TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('resolved', 'conflict')),
                    expected_output TEXT CHECK(expected_output IS NULL OR expected_output IN ('误触发', '正确触发', '无需协助')),
                    source_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(batch_id, issue_id, normalized_reviewer)
                );
                CREATE INDEX IF NOT EXISTS idx_label_import_votes_case
                    ON label_import_votes(baseline_scope, issue_id, reviewer);
                CREATE TABLE IF NOT EXISTS label_import_sources (
                    batch_id TEXT NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
                    source_annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE RESTRICT,
                    vote_id TEXT REFERENCES label_import_votes(id) ON DELETE RESTRICT,
                    label_case_id TEXT NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
                    source_run_id TEXT NOT NULL DEFAULT '',
                    source_work_split_id TEXT NOT NULL DEFAULT '',
                    source_label TEXT NOT NULL DEFAULT '',
                    source_review_status TEXT NOT NULL DEFAULT '',
                    source_reviewer TEXT NOT NULL DEFAULT '',
                    source_created_at TEXT NOT NULL,
                    migration_version TEXT NOT NULL,
                    PRIMARY KEY(batch_id, source_annotation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_label_import_sources_vote
                    ON label_import_sources(vote_id, source_annotation_id);
                CREATE TABLE IF NOT EXISTS label_import_case_states (
                    batch_id TEXT NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'resolved', 'conflict')),
                    expected_output TEXT CHECK(expected_output IS NULL OR expected_output IN ('误触发', '正确触发', '无需协助')),
                    gt_review_pending INTEGER NOT NULL DEFAULT 0,
                    pending_adjudication INTEGER NOT NULL DEFAULT 0,
                    frozen_gt_snapshot_id TEXT REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
                    frozen_gt_label TEXT NOT NULL DEFAULT '',
                    frozen_gt_source TEXT NOT NULL DEFAULT '',
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    reviewer_vote_count INTEGER NOT NULL DEFAULT 0,
                    source_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(batch_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_label_import_case_states_scope
                    ON label_import_case_states(baseline_scope, state, issue_id);
                CREATE TABLE IF NOT EXISTS label_import_suppressed_revisions (
                    batch_id TEXT NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
                    revision_id INTEGER NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    reason TEXT NOT NULL DEFAULT 'replaced_by_label_only_copy',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(batch_id, revision_id)
                );
                CREATE INDEX IF NOT EXISTS idx_label_import_suppressed_revision
                    ON label_import_suppressed_revisions(revision_id);
                CREATE TRIGGER IF NOT EXISTS trg_legacy_review_classifications_no_update
                BEFORE UPDATE ON legacy_review_classifications
                BEGIN SELECT RAISE(ABORT, 'S6 legacy classifications are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS trg_legacy_review_classifications_no_delete
                BEFORE DELETE ON legacy_review_classifications
                BEGIN SELECT RAISE(ABORT, 'S6 legacy classifications are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS trg_legacy_shadow_receipts_no_update
                BEFORE UPDATE ON legacy_shadow_receipts
                BEGIN SELECT RAISE(ABORT, 'S6 shadow receipts are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS trg_legacy_shadow_receipts_no_delete
                BEFORE DELETE ON legacy_shadow_receipts
                BEGIN SELECT RAISE(ABORT, 'S6 shadow receipts are append-only'); END;
