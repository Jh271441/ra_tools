-- Immutable administrator-owned allocation snapshots for intent experiments.

BEGIN;

CREATE TABLE IF NOT EXISTS intent_experiments (
    id varchar(36) PRIMARY KEY,
    dataset_id varchar(128) NOT NULL,
    name varchar(160) NOT NULL,
    annotation_mode varchar(16) NOT NULL
        CHECK(annotation_mode IN ('blind', 'full')),
    overlap_ratio double precision NOT NULL DEFAULT 0
        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1),
    case_count integer NOT NULL DEFAULT 0 CHECK(case_count >= 0),
    status varchar(16) NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'closed')),
    seed bigint NOT NULL,
    created_by varchar(128) NOT NULL,
    created_by_source varchar(64) NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_by varchar(128) NOT NULL DEFAULT '',
    closed_at timestamptz,
    UNIQUE(dataset_id, name)
);

CREATE INDEX IF NOT EXISTS idx_intent_experiments_dataset
    ON intent_experiments(dataset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS intent_experiment_assignments (
    experiment_id varchar(36) NOT NULL
        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
    username varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    assignment_kind varchar(16) NOT NULL
        CHECK(assignment_kind IN ('base', 'cross', 'full')),
    ordinal integer NOT NULL CHECK(ordinal > 0),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (experiment_id, username, case_id)
);

CREATE INDEX IF NOT EXISTS idx_intent_experiment_assignments_user
    ON intent_experiment_assignments(username, experiment_id, ordinal);

DO $$
DECLARE
    table_name text;
    operation text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'intent_experiments',
        'intent_experiment_assignments'
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
