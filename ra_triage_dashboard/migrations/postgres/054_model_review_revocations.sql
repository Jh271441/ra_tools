-- Logical Run-review revocation; preserve labels, revisions and submission audit.
BEGIN;
CREATE TABLE IF NOT EXISTS model_review_revocations (
    revision_id bigint PRIMARY KEY REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    actor TEXT NOT NULL,
    actor_source TEXT NOT NULL,
    actor_verified boolean NOT NULL,
    replacement_revision_id bigint REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL
);

CREATE OR REPLACE VIEW review_records AS
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
FROM model_review_revisions revision
WHERE NOT EXISTS (SELECT 1 FROM model_review_revocations revoked WHERE revoked.revision_id=revision.id);

COMMIT;
