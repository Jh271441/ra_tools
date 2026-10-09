-- Run-bound model review revisions, heads, and attachment metadata.
BEGIN;

CREATE TABLE IF NOT EXISTS model_review_revisions (
    id bigserial PRIMARY KEY,
    model_run_id text NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    campaign_id text NOT NULL DEFAULT '',
    reference_id text NOT NULL DEFAULT '',
    work_split_id text NOT NULL DEFAULT '',
    status varchar(24) NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_progress', 'completed', 'blocked_by_label')),
    reason text NOT NULL DEFAULT '',
    missing_evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    label_state_fingerprint varchar(64) NOT NULL DEFAULT '',
    label_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    reviewer text NOT NULL,
    reviewer_source text NOT NULL DEFAULT 'legacy',
    reviewer_verified boolean NOT NULL DEFAULT false,
    supersedes_id bigint REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    legacy_base_annotation_id bigint REFERENCES annotations(id) ON DELETE RESTRICT,
    legacy_annotation_id bigint UNIQUE REFERENCES annotations(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_review_revisions_run_issue
    ON model_review_revisions(model_run_id, issue_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_model_review_revisions_scope_filters
    ON model_review_revisions(model_run_id, status, reviewer, id DESC);
CREATE INDEX IF NOT EXISTS idx_model_review_revisions_work_split
    ON model_review_revisions(work_split_id, model_run_id, issue_id, reviewer, id DESC);

CREATE TABLE IF NOT EXISTS model_review_heads (
    model_run_id text NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    campaign_id text NOT NULL DEFAULT '',
    reference_id text NOT NULL DEFAULT '',
    reviewer text NOT NULL,
    revision_id bigint NOT NULL UNIQUE
        REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(model_run_id, issue_id, campaign_id, reference_id, reviewer)
);

CREATE INDEX IF NOT EXISTS idx_model_review_heads_issue_run
    ON model_review_heads(issue_id, model_run_id, revision_id DESC);

CREATE TABLE IF NOT EXISTS model_review_attachments (
    id uuid PRIMARY KEY,
    revision_id bigint NOT NULL
        REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    original_name text NOT NULL DEFAULT '',
    stored_name text NOT NULL UNIQUE,
    media_type varchar(64) NOT NULL,
    size_bytes bigint NOT NULL CHECK(size_bytes >= 0),
    width integer NOT NULL CHECK(width > 0),
    height integer NOT NULL CHECK(height > 0),
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_review_attachments_revision
    ON model_review_attachments(revision_id, created_at);

CREATE VIEW review_records AS
SELECT
    annotation.id::bigint AS id,
    annotation.issue_id,
    annotation.model_run_id,
    annotation.work_split_id,
    annotation.label,
    annotation.review_status,
    annotation.is_excluded,
    annotation.tags_json,
    annotation.missing_evidence_json,
    annotation.mentions_json,
    annotation.note,
    annotation.author,
    annotation.author_source,
    annotation.author_verified,
    annotation.supersedes_id::bigint AS supersedes_id,
    annotation.created_at,
    'legacy'::text AS review_domain,
    ''::text AS model_review_status,
    ''::text AS campaign_id,
    ''::text AS reference_id,
    annotation.id::bigint AS storage_id
FROM annotations annotation
UNION ALL
SELECT
    (4000000000000000::bigint + revision.id) AS id,
    revision.issue_id,
    revision.model_run_id,
    revision.work_split_id,
    NULL::text AS label,
    CASE revision.status
        WHEN 'completed' THEN 'reviewed'
        WHEN 'blocked_by_label' THEN 'needs_gt_review'
        ELSE 'pending'
    END AS review_status,
    false AS is_excluded,
    '[]'::jsonb AS tags_json,
    revision.missing_evidence_json,
    '[]'::jsonb AS mentions_json,
    revision.reason AS note,
    revision.reviewer AS author,
    revision.reviewer_source AS author_source,
    revision.reviewer_verified AS author_verified,
    CASE
        WHEN revision.supersedes_id IS NOT NULL
            THEN 4000000000000000::bigint + revision.supersedes_id
        ELSE revision.legacy_base_annotation_id
    END AS supersedes_id,
    revision.created_at,
    'model_review'::text AS review_domain,
    revision.status AS model_review_status,
    revision.campaign_id,
    revision.reference_id,
    revision.id AS storage_id
FROM model_review_revisions revision;

CREATE VIEW review_record_attachments AS
SELECT
    attachment.id,
    attachment.annotation_id::bigint AS annotation_id,
    attachment.original_name,
    attachment.stored_name,
    attachment.media_type,
    attachment.size_bytes,
    attachment.width,
    attachment.height,
    attachment.sha256,
    attachment.created_at,
    'legacy'::text AS review_domain,
    attachment.annotation_id::bigint AS storage_revision_id
FROM review_attachments attachment
UNION ALL
SELECT
    attachment.id,
    4000000000000000::bigint + attachment.revision_id AS annotation_id,
    attachment.original_name,
    attachment.stored_name,
    attachment.media_type,
    attachment.size_bytes,
    attachment.width,
    attachment.height,
    attachment.sha256,
    attachment.created_at,
    'model_review'::text AS review_domain,
    attachment.revision_id AS storage_revision_id
FROM model_review_attachments attachment;

COMMIT;
