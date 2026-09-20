-- Immutable GT and local Label result snapshots.
BEGIN;

CREATE TABLE IF NOT EXISTS gt_snapshots (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    gt_mode varchar(16) NOT NULL CHECK(gt_mode IN ('strict', 'sparse')),
    source_name text NOT NULL DEFAULT 'Trail',
    source_view_id integer NOT NULL DEFAULT 0,
    source_field text NOT NULL DEFAULT '',
    source_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    content_sha256 varchar(64) NOT NULL,
    membership_sha256 varchar(64) NOT NULL,
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    valid_label_count integer NOT NULL DEFAULT 0 CHECK(valid_label_count >= 0),
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'system',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(baseline_scope, content_sha256),
    UNIQUE(id, baseline_scope),
    UNIQUE(id, baseline_scope, content_sha256),
    CHECK(valid_label_count <= member_count)
);

CREATE INDEX IF NOT EXISTS idx_gt_snapshots_scope_created
    ON gt_snapshots(baseline_scope, created_at DESC);

CREATE TABLE IF NOT EXISTS gt_snapshot_items (
    snapshot_id text NOT NULL,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    gt_label text NOT NULL DEFAULT ''
        CHECK(gt_label IN ('', '误触发', '正确触发', '无需协助')),
    source_updated_at text NOT NULL DEFAULT '',
    source_updated_by text NOT NULL DEFAULT '',
    PRIMARY KEY(snapshot_id, issue_id),
    UNIQUE(snapshot_id, ordinal),
    FOREIGN KEY(snapshot_id, baseline_scope)
        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_gt_snapshot_items_scope_issue
    ON gt_snapshot_items(baseline_scope, issue_id, snapshot_id);

CREATE TABLE IF NOT EXISTS gt_snapshot_active (
    baseline_scope text PRIMARY KEY,
    snapshot_id text NOT NULL,
    activated_at timestamptz NOT NULL DEFAULT now(),
    activated_by text NOT NULL DEFAULT '',
    activated_by_source text NOT NULL DEFAULT 'system',
    activated_by_verified boolean NOT NULL DEFAULT false,
    activation_reason text NOT NULL DEFAULT '',
    FOREIGN KEY(snapshot_id, baseline_scope)
        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS label_result_snapshots (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    workset_id text NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
    workset_members_sha256 varchar(64) NOT NULL,
    content_sha256 varchar(64) NOT NULL,
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    resolved_count integer NOT NULL DEFAULT 0 CHECK(resolved_count >= 0),
    pending_count integer NOT NULL DEFAULT 0 CHECK(pending_count >= 0),
    conflict_count integer NOT NULL DEFAULT 0 CHECK(conflict_count >= 0),
    stale_count integer NOT NULL DEFAULT 0 CHECK(stale_count >= 0),
    unknown_count integer NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
    coverage_status varchar(16) NOT NULL DEFAULT 'complete'
        CHECK(coverage_status IN ('complete', 'partial')),
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(workset_id, content_sha256),
    UNIQUE(id, baseline_scope),
    CHECK(member_count = resolved_count + pending_count + conflict_count + stale_count + unknown_count)
);

CREATE INDEX IF NOT EXISTS idx_label_result_snapshots_scope_created
    ON label_result_snapshots(baseline_scope, created_at DESC);

CREATE TABLE IF NOT EXISTS label_result_snapshot_items (
    snapshot_id text NOT NULL,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    state varchar(16) NOT NULL CHECK(state IN ('none', 'pending', 'resolved', 'conflict', 'stale')),
    expected_output text
        CHECK(expected_output IS NULL OR expected_output IN ('误触发', '正确触发', '无需协助')),
    method varchar(24) NOT NULL CHECK(method IN ('single', 'consensus', 'adjudication')),
    gt_relation varchar(24) NOT NULL DEFAULT 'unknown'
        CHECK(gt_relation IN ('matches_gt', 'differs_from_gt', 'fills_missing_gt', 'unknown')),
    PRIMARY KEY(snapshot_id, issue_id),
    UNIQUE(snapshot_id, ordinal),
    FOREIGN KEY(snapshot_id, baseline_scope)
        REFERENCES label_result_snapshots(id, baseline_scope) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_items_scope_issue
    ON label_result_snapshot_items(baseline_scope, issue_id, snapshot_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_label_cases_id_issue
    ON label_cases(id, issue_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_label_revisions_id_case
    ON label_revisions(id, label_case_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_label_resolutions_id_case
    ON label_resolutions(id, label_case_id);

CREATE TABLE IF NOT EXISTS label_result_snapshot_sources (
    id bigserial PRIMARY KEY,
    snapshot_id text NOT NULL REFERENCES label_result_snapshots(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    task_id text NOT NULL DEFAULT '',
    resolution_id bigint REFERENCES label_resolutions(id) ON DELETE RESTRICT,
    revision_id bigint REFERENCES label_revisions(id) ON DELETE RESTRICT,
    source_role varchar(24) NOT NULL DEFAULT 'head'
        CHECK(source_role IN ('case', 'head', 'resolution_input', 'resolution_result')),
    source_key text NOT NULL,
    UNIQUE(snapshot_id, source_key),
    FOREIGN KEY(snapshot_id, issue_id)
        REFERENCES label_result_snapshot_items(snapshot_id, issue_id) ON DELETE RESTRICT,
    FOREIGN KEY(label_case_id, issue_id)
        REFERENCES label_cases(id, issue_id) ON DELETE RESTRICT,
    FOREIGN KEY(resolution_id, label_case_id)
        REFERENCES label_resolutions(id, label_case_id) ON DELETE RESTRICT,
    FOREIGN KEY(revision_id, label_case_id)
        REFERENCES label_revisions(id, label_case_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_sources_case
    ON label_result_snapshot_sources(label_case_id, snapshot_id);

ALTER TABLE label_gt_export_batches
    ADD COLUMN IF NOT EXISTS source_gt_snapshot_id text REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS source_gt_snapshot_ids_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_gt_snapshot_sha256 varchar(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS reconcile_status varchar(24) NOT NULL DEFAULT 'not_checked'
        CHECK(reconcile_status IN ('not_checked', 'matched', 'partial', 'not_applied', 'changed_again', 'error')),
    ADD COLUMN IF NOT EXISTS reconcile_error text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS reconciled_at timestamptz,
    ADD COLUMN IF NOT EXISTS reconciled_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS not_applied_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS changed_again_count integer NOT NULL DEFAULT 0;

ALTER TABLE label_gt_export_items
    ADD COLUMN IF NOT EXISTS reconcile_status varchar(24) NOT NULL DEFAULT 'not_checked'
        CHECK(reconcile_status IN ('not_checked', 'matched', 'not_applied', 'changed_again', 'error')),
    ADD COLUMN IF NOT EXISTS reconciled_snapshot_id text REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS reconciled_at timestamptz;

CREATE TABLE IF NOT EXISTS label_gt_export_source_snapshots (
    batch_id text NOT NULL
        REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    snapshot_id text NOT NULL,
    content_sha256 varchar(64) NOT NULL,
    PRIMARY KEY(batch_id, baseline_scope),
    FOREIGN KEY(snapshot_id, baseline_scope, content_sha256)
        REFERENCES gt_snapshots(id, baseline_scope, content_sha256) ON DELETE RESTRICT
);

COMMIT;
