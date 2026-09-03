-- Audit intent-label head removals without deleting immutable revisions.

BEGIN;

CREATE TABLE IF NOT EXISTS intent_label_deletions (
    id bigserial PRIMARY KEY,
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    username varchar(128) NOT NULL,
    deleted_revision_id bigint NOT NULL REFERENCES intent_label_revisions(id),
    deleted_by varchar(128) NOT NULL,
    deleted_by_source varchar(64) NOT NULL DEFAULT 'legacy',
    deleted_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_label_deletions_case
    ON intent_label_deletions(dataset_id, case_id, username, id DESC);

DO $$
DECLARE
    operation text;
BEGIN
    FOREACH operation IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON intent_label_deletions',
            'trg_intent_label_deletions_' || lower(operation) || '_change_revision'
        );
        EXECUTE format(
            'CREATE TRIGGER %I AFTER %s ON intent_label_deletions FOR EACH STATEMENT '
            'EXECUTE FUNCTION bump_dashboard_change_revision()',
            'trg_intent_label_deletions_' || lower(operation) || '_change_revision',
            operation
        );
    END LOOP;
END;
$$;

COMMIT;
