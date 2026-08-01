-- Cross-client change revision used by lightweight dashboard synchronization.

BEGIN;

CREATE TABLE IF NOT EXISTS dashboard_change_revision (
    id smallint PRIMARY KEY CHECK (id = 1),
    revision bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO dashboard_change_revision (id, revision)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION bump_dashboard_change_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE dashboard_change_revision
    SET revision = revision + 1,
        updated_at = now()
    WHERE id = 1;
    RETURN NULL;
END;
$$;

DO $$
DECLARE
    table_name text;
    operation text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'issues',
        'annotations',
        'review_attachments',
        'model_runs',
        'model_predictions',
        'inference_jobs',
        'batch_prediction_jobs',
        'batch_prediction_items'
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
