-- Independent Case labeling records, frozen worksets and explicit adjudications.

BEGIN;

CREATE TABLE IF NOT EXISTS review_worksets (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    name text NOT NULL DEFAULT '',
    selection_source_run_id text NOT NULL DEFAULT '',
    source_filter_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    members_sha256 varchar(64) NOT NULL,
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_worksets_scope_created
    ON review_worksets(baseline_scope, created_at DESC);

CREATE TABLE IF NOT EXISTS review_workset_items (
    workset_id text NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    PRIMARY KEY(workset_id, issue_id),
    UNIQUE(workset_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_review_workset_items_issue
    ON review_workset_items(issue_id, workset_id);

ALTER TABLE issue_work_splits
    ADD COLUMN IF NOT EXISTS task_kind varchar(24) NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS workset_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS selection_source_run_id text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS label_cases (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    task_id text NOT NULL DEFAULT '',
    source_run_id text NOT NULL DEFAULT '',
    seen_gt_label text NOT NULL DEFAULT '',
    seen_gt_source text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(baseline_scope, issue_id, task_id, source_run_id)
);

CREATE INDEX IF NOT EXISTS idx_label_cases_scope_issue
    ON label_cases(baseline_scope, issue_id, task_id);

CREATE TABLE IF NOT EXISTS label_revisions (
    id bigserial PRIMARY KEY,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    expected_output text CHECK(expected_output IS NULL OR expected_output IN (
        '误触发', '正确触发', '无需协助'
    )),
    tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_gaps_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    rationale text NOT NULL DEFAULT '',
    is_excluded boolean NOT NULL DEFAULT false,
    author text NOT NULL DEFAULT '',
    author_source text NOT NULL DEFAULT 'legacy',
    author_verified boolean NOT NULL DEFAULT false,
    revision_kind varchar(24) NOT NULL DEFAULT 'submission'
        CHECK(revision_kind IN ('submission', 'adjudication', 'legacy')),
    supersedes_id bigint REFERENCES label_revisions(id),
    source_annotation_id bigint UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_revisions_case_author
    ON label_revisions(label_case_id, author, id DESC);

CREATE TABLE IF NOT EXISTS label_attachments (
    id uuid PRIMARY KEY,
    revision_id bigint NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
    source_review_attachment_id uuid UNIQUE,
    original_name text NOT NULL DEFAULT '',
    stored_name text NOT NULL,
    media_type varchar(64) NOT NULL,
    size_bytes bigint NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_attachments_revision
    ON label_attachments(revision_id, created_at);

CREATE TABLE IF NOT EXISTS label_resolutions (
    id bigserial PRIMARY KEY,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    method varchar(24) NOT NULL CHECK(method IN ('adjudication')),
    result_revision_id bigint NOT NULL REFERENCES label_revisions(id) ON DELETE RESTRICT,
    source_revision_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_fingerprint varchar(64) NOT NULL,
    supersedes_id bigint REFERENCES label_resolutions(id),
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_resolutions_case
    ON label_resolutions(label_case_id, id DESC);

CREATE TABLE IF NOT EXISTS label_migration_map (
    source_table text NOT NULL,
    source_id text NOT NULL,
    target_table text NOT NULL,
    target_id text NOT NULL,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(source_table, source_id, target_table, policy_version)
);

CREATE TABLE IF NOT EXISTS label_gt_export_batches (
    id text PRIMARY KEY,
    baseline_scopes_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_fingerprint varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'preview'
        CHECK(status IN ('preview', 'exported', 'stale')),
    item_count integer NOT NULL DEFAULT 0 CHECK(item_count >= 0),
    file_sha256 varchar(64) NOT NULL DEFAULT '',
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    exported_at timestamptz
);

CREATE TABLE IF NOT EXISTS label_gt_export_items (
    batch_id text NOT NULL REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    old_gt_label text NOT NULL DEFAULT '',
    expected_output text NOT NULL CHECK(expected_output IN (
        '误触发', '正确触发', '无需协助'
    )),
    source_revision_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_fingerprint varchar(64) NOT NULL,
    PRIMARY KEY(batch_id, issue_id)
);

CREATE TABLE IF NOT EXISTS label_comment_links (
    comment_id bigint PRIMARY KEY REFERENCES review_comments(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    task_id text NOT NULL DEFAULT '',
    source_run_id text NOT NULL DEFAULT '',
    policy_version text NOT NULL,
    linked_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_label_comment_links_scope
    ON label_comment_links(baseline_scope, issue_id, task_id);

COMMIT;
