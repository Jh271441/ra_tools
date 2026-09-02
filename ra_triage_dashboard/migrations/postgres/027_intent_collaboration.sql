-- Per-annotator intent heads and dataset-scoped discussion.

BEGIN;

UPDATE intent_label_revisions
SET dataset_id = '0206-1335-v1'
WHERE dataset_id = '0206-full2804-v1';

UPDATE intent_label_heads
SET dataset_id = '0206-1335-v1'
WHERE dataset_id = '0206-full2804-v1';

UPDATE intent_experiments
SET dataset_id = '0206-1335-v1'
WHERE dataset_id = '0206-full2804-v1';

CREATE TABLE IF NOT EXISTS intent_user_label_heads (
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    username varchar(128) NOT NULL,
    current_revision_id bigint NOT NULL REFERENCES intent_label_revisions(id),
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, case_id, username)
);

INSERT INTO intent_user_label_heads (
    dataset_id, case_id, username, current_revision_id, version, updated_at
)
SELECT head.dataset_id, head.case_id,
       lower(CASE WHEN revision.author = '' THEN 'legacy' ELSE revision.author END),
       head.current_revision_id, head.version, head.updated_at
FROM intent_label_heads head
JOIN intent_label_revisions revision ON revision.id = head.current_revision_id
ON CONFLICT (dataset_id, case_id, username) DO NOTHING;

CREATE TABLE IF NOT EXISTS intent_case_comments (
    id bigserial PRIMARY KEY,
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    body text NOT NULL,
    author varchar(128) NOT NULL,
    author_source varchar(64) NOT NULL DEFAULT 'legacy',
    author_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_case_comments_case
    ON intent_case_comments(dataset_id, case_id, id ASC);

DO $$
DECLARE
    table_name text;
    operation text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'intent_user_label_heads',
        'intent_case_comments'
    ]
    LOOP
        FOREACH operation IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE']
        LOOP
            EXECUTE format(
                'DROP TRIGGER IF EXISTS %I ON %I',
                'trg_' || table_name || '_' || lower(operation) || '_change_revision',
                table_name
            );
            EXECUTE format(
                'CREATE TRIGGER %I AFTER %s ON %I FOR EACH STATEMENT '
                'EXECUTE FUNCTION bump_dashboard_change_revision()',
                'trg_' || table_name || '_' || lower(operation) || '_change_revision',
                operation,
                table_name
            );
        END LOOP;
    END LOOP;
END;
$$;

COMMIT;
