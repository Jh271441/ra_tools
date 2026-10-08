
                    CREATE TABLE IF NOT EXISTS run_collections (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        current_revision INTEGER NOT NULL DEFAULT 0 CHECK(current_revision >= 0),
                        metadata_revision INTEGER NOT NULL DEFAULT 0 CHECK(metadata_revision >= 0),
                        created_by TEXT NOT NULL DEFAULT '',
                        created_by_source TEXT NOT NULL DEFAULT 'legacy',
                        created_by_verified INTEGER NOT NULL DEFAULT 0 CHECK(created_by_verified IN (0, 1)),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL DEFAULT '',
                        idempotency_fingerprint TEXT NOT NULL DEFAULT ''
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collections_idempotency
                        ON run_collections(idempotency_key) WHERE idempotency_key <> '';
                    CREATE TABLE IF NOT EXISTS run_collection_audit (
                        id TEXT PRIMARY KEY,
                        collection_id TEXT NOT NULL REFERENCES run_collections(id) ON DELETE RESTRICT,
                        action TEXT NOT NULL,
                        revision_no INTEGER NOT NULL DEFAULT 0,
                        context_id TEXT NOT NULL DEFAULT '',
                        actor TEXT NOT NULL DEFAULT '',
                        actor_source TEXT NOT NULL DEFAULT 'legacy',
                        actor_verified INTEGER NOT NULL DEFAULT 0 CHECK(actor_verified IN (0, 1)),
                        source TEXT NOT NULL DEFAULT 'user',
                        detail_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_run_collection_audit_collection
                        ON run_collection_audit(collection_id, created_at DESC);
                    CREATE TRIGGER IF NOT EXISTS trg_run_collections_revisions_never_decrease
                    BEFORE UPDATE ON run_collections
                    WHEN NEW.current_revision < OLD.current_revision
                      OR NEW.metadata_revision < OLD.metadata_revision
                    BEGIN SELECT RAISE(ABORT, 'Run Collection revisions cannot move backwards'); END;
                    CREATE TABLE IF NOT EXISTS run_collection_revisions (
                        collection_id TEXT NOT NULL REFERENCES run_collections(id) ON DELETE RESTRICT,
                        revision_no INTEGER NOT NULL CHECK(revision_no > 0),
                        content_json TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL,
                        members_sha256 TEXT NOT NULL,
                        member_count INTEGER NOT NULL DEFAULT 0 CHECK(member_count >= 0),
                        source TEXT NOT NULL DEFAULT 'user',
                        created_by TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL DEFAULT '',
                        idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY(collection_id, revision_no)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collection_revision_idempotency
                        ON run_collection_revisions(collection_id, idempotency_key)
                        WHERE idempotency_key <> '';
                    CREATE TABLE IF NOT EXISTS run_collection_members (
                        collection_id TEXT NOT NULL,
                        revision_no INTEGER NOT NULL,
                        ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                        run_id TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT '',
                        is_reference INTEGER NOT NULL DEFAULT 0 CHECK(is_reference IN (0, 1)),
                        run_snapshot_json TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY(collection_id, revision_no, ordinal),
                        UNIQUE(collection_id, revision_no, run_id),
                        FOREIGN KEY(collection_id, revision_no)
                            REFERENCES run_collection_revisions(collection_id, revision_no)
                            ON DELETE RESTRICT
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collection_single_reference
                        ON run_collection_members(collection_id, revision_no)
                        WHERE is_reference = 1;
                    CREATE INDEX IF NOT EXISTS idx_run_collection_members_run
                        ON run_collection_members(run_id, collection_id);
                    CREATE TABLE IF NOT EXISTS run_evaluation_exclusion_snapshots (
                        content_sha256 TEXT PRIMARY KEY,
                        version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                        issue_count INTEGER NOT NULL DEFAULT 0 CHECK(issue_count >= 0),
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS run_evaluation_exclusion_items (
                        content_sha256 TEXT NOT NULL REFERENCES run_evaluation_exclusion_snapshots(content_sha256)
                            ON DELETE RESTRICT,
                        issue_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                        PRIMARY KEY(content_sha256, issue_id),
                        UNIQUE(content_sha256, ordinal)
                    );
                    CREATE TABLE IF NOT EXISTS run_evaluation_contexts (
                        id TEXT PRIMARY KEY,
                        collection_id TEXT NOT NULL,
                        collection_revision INTEGER NOT NULL,
                        collection_sha256 TEXT NOT NULL,
                        workset_id TEXT NOT NULL DEFAULT '',
                        workset_json TEXT NOT NULL,
                        workset_sha256 TEXT NOT NULL,
                        item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count >= 0),
                        reference_type TEXT NOT NULL CHECK(reference_type IN ('gt', 'label_result', 'run')),
                        reference_id TEXT NOT NULL DEFAULT '',
                        reference_json TEXT NOT NULL,
                        reference_sha256 TEXT NOT NULL,
                        scoring_policy_json TEXT NOT NULL,
                        scoring_policy_version TEXT NOT NULL,
                        scoring_policy_sha256 TEXT NOT NULL,
                        exclusion_sha256 TEXT NOT NULL REFERENCES run_evaluation_exclusion_snapshots(content_sha256)
                            ON DELETE RESTRICT,
                        exclusion_version INTEGER NOT NULL DEFAULT 1,
                        selection_source_run_id TEXT NOT NULL DEFAULT '',
                        comparison_reference_run_id TEXT NOT NULL DEFAULT '',
                        context_sha256 TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL DEFAULT '',
                        idempotency_fingerprint TEXT NOT NULL DEFAULT '',
                        created_by TEXT NOT NULL DEFAULT '',
                        created_by_source TEXT NOT NULL DEFAULT 'legacy',
                        created_by_verified INTEGER NOT NULL DEFAULT 0 CHECK(created_by_verified IN (0, 1)),
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(collection_id, collection_revision)
                            REFERENCES run_collection_revisions(collection_id, revision_no)
                            ON DELETE RESTRICT
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_evaluation_context_idempotency
                        ON run_evaluation_contexts(idempotency_key) WHERE idempotency_key <> '';
                    CREATE INDEX IF NOT EXISTS idx_run_evaluation_context_collection
                        ON run_evaluation_contexts(collection_id, collection_revision, created_at DESC);
                    CREATE TABLE IF NOT EXISTS run_evaluation_items (
                        context_id TEXT NOT NULL REFERENCES run_evaluation_contexts(id) ON DELETE RESTRICT,
                        ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                        issue_id TEXT NOT NULL,
                        baseline_scope TEXT NOT NULL DEFAULT '',
                        reference_label TEXT NOT NULL DEFAULT '',
                        reference_valid INTEGER NOT NULL DEFAULT 0 CHECK(reference_valid IN (0, 1)),
                        excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0, 1)),
                        predictions_json TEXT NOT NULL DEFAULT '{}',
                        model_review_json TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY(context_id, issue_id),
                        UNIQUE(context_id, ordinal)
                    );
                    CREATE INDEX IF NOT EXISTS idx_run_evaluation_items_page
                        ON run_evaluation_items(context_id, ordinal);

                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_revisions_no_update
                    BEFORE UPDATE ON run_collection_revisions
                    BEGIN SELECT RAISE(ABORT, 'run collection revisions are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_revisions_no_delete
                    BEFORE DELETE ON run_collection_revisions
                    BEGIN SELECT RAISE(ABORT, 'run collection revisions are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_audit_no_update
                    BEFORE UPDATE ON run_collection_audit
                    BEGIN SELECT RAISE(ABORT, 'run collection audit is immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_audit_no_delete
                    BEFORE DELETE ON run_collection_audit
                    BEGIN SELECT RAISE(ABORT, 'run collection audit is immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_members_no_update
                    BEFORE UPDATE ON run_collection_members
                    BEGIN SELECT RAISE(ABORT, 'run collection members are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_members_no_delete
                    BEFORE DELETE ON run_collection_members
                    BEGIN SELECT RAISE(ABORT, 'run collection members are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_collection_members_no_extra_insert
                    BEFORE INSERT ON run_collection_members
                    WHEN NEW.ordinal > COALESCE((
                        SELECT member_count FROM run_collection_revisions
                        WHERE collection_id = NEW.collection_id AND revision_no = NEW.revision_no
                    ), 0) OR (
                        SELECT COUNT(*) FROM run_collection_members
                        WHERE collection_id = NEW.collection_id AND revision_no = NEW.revision_no
                    ) >= COALESCE((
                        SELECT member_count FROM run_collection_revisions
                        WHERE collection_id = NEW.collection_id AND revision_no = NEW.revision_no
                    ), 0)
                    BEGIN SELECT RAISE(ABORT, 'run collection revision member set is complete'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_exclusion_snapshots_no_update
                    BEFORE UPDATE ON run_evaluation_exclusion_snapshots
                    BEGIN SELECT RAISE(ABORT, 'evaluation exclusion snapshots are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_exclusion_snapshots_no_delete
                    BEFORE DELETE ON run_evaluation_exclusion_snapshots
                    BEGIN SELECT RAISE(ABORT, 'evaluation exclusion snapshots are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_exclusion_items_no_update
                    BEFORE UPDATE ON run_evaluation_exclusion_items
                    BEGIN SELECT RAISE(ABORT, 'evaluation exclusion items are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_exclusion_items_no_delete
                    BEFORE DELETE ON run_evaluation_exclusion_items
                    BEGIN SELECT RAISE(ABORT, 'evaluation exclusion items are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_exclusion_items_no_extra_insert
                    BEFORE INSERT ON run_evaluation_exclusion_items
                    WHEN NEW.ordinal > COALESCE((
                        SELECT issue_count FROM run_evaluation_exclusion_snapshots
                        WHERE content_sha256 = NEW.content_sha256
                    ), 0) OR (
                        SELECT COUNT(*) FROM run_evaluation_exclusion_items
                        WHERE content_sha256 = NEW.content_sha256
                    ) >= COALESCE((
                        SELECT issue_count FROM run_evaluation_exclusion_snapshots
                        WHERE content_sha256 = NEW.content_sha256
                    ), 0)
                    BEGIN SELECT RAISE(ABORT, 'evaluation exclusion snapshot item set is complete'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_contexts_no_update
                    BEFORE UPDATE ON run_evaluation_contexts
                    BEGIN SELECT RAISE(ABORT, 'evaluation contexts are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_contexts_no_delete
                    BEFORE DELETE ON run_evaluation_contexts
                    BEGIN SELECT RAISE(ABORT, 'evaluation contexts are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_items_no_update
                    BEFORE UPDATE ON run_evaluation_items
                    BEGIN SELECT RAISE(ABORT, 'evaluation items are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_items_no_delete
                    BEFORE DELETE ON run_evaluation_items
                    BEGIN SELECT RAISE(ABORT, 'evaluation items are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_run_evaluation_items_no_extra_insert
                    BEFORE INSERT ON run_evaluation_items
                    WHEN NEW.ordinal > COALESCE((
                        SELECT item_count FROM run_evaluation_contexts WHERE id = NEW.context_id
                    ), 0) OR (
                        SELECT COUNT(*) FROM run_evaluation_items WHERE context_id = NEW.context_id
                    ) >= COALESCE((
                        SELECT item_count FROM run_evaluation_contexts WHERE id = NEW.context_id
                    ), 0)
                    BEGIN SELECT RAISE(ABORT, 'evaluation context item set is complete'); END;
                    CREATE TABLE IF NOT EXISTS review_workset_scopes (
                        workset_id TEXT NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
                        baseline_scope TEXT NOT NULL,
                        ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                        member_count INTEGER NOT NULL DEFAULT 0 CHECK(member_count >= 0),
                        members_sha256 TEXT NOT NULL,
                        gt_snapshot_id TEXT NOT NULL DEFAULT '',
                        gt_snapshot_sha256 TEXT NOT NULL DEFAULT '',
                        label_result_snapshot_id TEXT NOT NULL DEFAULT '',
                        label_result_sha256 TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY(workset_id, baseline_scope),
                        UNIQUE(workset_id, ordinal)
                    );
                    CREATE INDEX IF NOT EXISTS idx_review_workset_scopes_scope
                        ON review_workset_scopes(baseline_scope, workset_id);
                    CREATE TRIGGER IF NOT EXISTS trg_review_workset_scopes_no_update
                    BEFORE UPDATE ON review_workset_scopes
                    BEGIN SELECT RAISE(ABORT, 'run workset scope snapshots are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_review_workset_scopes_no_delete
                    BEFORE DELETE ON review_workset_scopes
                    BEGIN SELECT RAISE(ABORT, 'run workset scope snapshots are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS trg_review_workset_scopes_no_extra_insert
                    BEFORE INSERT ON review_workset_scopes
                    WHEN NEW.ordinal > COALESCE((
                        SELECT scope_count FROM review_worksets WHERE id = NEW.workset_id
                    ), 0) OR (
                        SELECT COUNT(*) FROM review_workset_scopes
                        WHERE workset_id = NEW.workset_id
                    ) >= COALESCE((
                        SELECT scope_count FROM review_worksets WHERE id = NEW.workset_id
                    ), 0)
                    BEGIN SELECT RAISE(ABORT, 'run workset scope set is complete'); END;
                    CREATE INDEX IF NOT EXISTS idx_run_evaluation_items_scope
                        ON run_evaluation_items(context_id, baseline_scope, ordinal);
                    CREATE INDEX IF NOT EXISTS idx_run_evaluation_context_sha
                        ON run_evaluation_contexts(context_sha256, created_at, id);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_evaluation_context_sha_unique
                        ON run_evaluation_contexts(context_sha256);
