-- Copy only Case/GT label signals from legacy mixed Reviews.
BEGIN;

CREATE TABLE IF NOT EXISTS label_import_batches (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    name text NOT NULL,
    source_type text NOT NULL CHECK(source_type IN ('legacy_model_review')),
    migration_version text NOT NULL,
    status text NOT NULL CHECK(status IN ('importing', 'imported')),
    source_inventory_sha256 char(64) NOT NULL,
    stats_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_by text NOT NULL DEFAULT 'migration',
    created_at timestamptz NOT NULL DEFAULT now(),
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(baseline_scope, source_type, migration_version)
);
CREATE INDEX IF NOT EXISTS idx_label_import_batches_scope
    ON label_import_batches(baseline_scope, imported_at DESC);

CREATE TABLE IF NOT EXISTS label_import_votes (
    id text PRIMARY KEY,
    batch_id text NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    label_revision_id bigint NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    reviewer text NOT NULL,
    normalized_reviewer text NOT NULL,
    state text NOT NULL CHECK(state IN ('resolved', 'conflict')),
    expected_output text CHECK(expected_output IS NULL OR expected_output IN (
        '误触发', '正确触发', '无需协助'
    )),
    source_fingerprint char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(batch_id, issue_id, normalized_reviewer)
);
CREATE INDEX IF NOT EXISTS idx_label_import_votes_case
    ON label_import_votes(baseline_scope, issue_id, reviewer);

CREATE TABLE IF NOT EXISTS label_import_sources (
    batch_id text NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
    source_annotation_id bigint NOT NULL REFERENCES annotations(id) ON DELETE RESTRICT,
    vote_id text REFERENCES label_import_votes(id) ON DELETE RESTRICT,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    source_run_id text NOT NULL DEFAULT '',
    source_work_split_id text NOT NULL DEFAULT '',
    source_label text NOT NULL DEFAULT '',
    source_review_status text NOT NULL DEFAULT '',
    source_reviewer text NOT NULL DEFAULT '',
    source_created_at timestamptz NOT NULL,
    migration_version text NOT NULL,
    PRIMARY KEY(batch_id, source_annotation_id)
);
CREATE INDEX IF NOT EXISTS idx_label_import_sources_vote
    ON label_import_sources(vote_id, source_annotation_id);

CREATE TABLE IF NOT EXISTS label_import_case_states (
    batch_id text NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    state text NOT NULL CHECK(state IN ('pending', 'resolved', 'conflict')),
    expected_output text CHECK(expected_output IS NULL OR expected_output IN (
        '误触发', '正确触发', '无需协助'
    )),
    gt_review_pending boolean NOT NULL DEFAULT false,
    pending_adjudication boolean NOT NULL DEFAULT false,
    frozen_gt_snapshot_id text REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
    frozen_gt_label text NOT NULL DEFAULT '',
    frozen_gt_source text NOT NULL DEFAULT '',
    source_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    reviewer_vote_count integer NOT NULL DEFAULT 0 CHECK(reviewer_vote_count >= 0),
    source_fingerprint char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(batch_id, issue_id)
);
CREATE INDEX IF NOT EXISTS idx_label_import_case_states_scope
    ON label_import_case_states(baseline_scope, state, issue_id);

CREATE TABLE IF NOT EXISTS label_import_suppressed_revisions (
    batch_id text NOT NULL REFERENCES label_import_batches(id) ON DELETE RESTRICT,
    revision_id bigint NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
    reason text NOT NULL DEFAULT 'replaced_by_label_only_copy',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(batch_id, revision_id)
);
CREATE INDEX IF NOT EXISTS idx_label_import_suppressed_revision
    ON label_import_suppressed_revisions(revision_id);

COMMIT;
