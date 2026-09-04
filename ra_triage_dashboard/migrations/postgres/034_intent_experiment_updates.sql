-- Audited edits to experiment presentation and labeling scope.

BEGIN;

CREATE TABLE IF NOT EXISTS intent_experiment_updates (
    id bigserial PRIMARY KEY,
    experiment_id varchar(36) NOT NULL
        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
    old_name varchar(160) NOT NULL,
    new_name varchar(160) NOT NULL,
    old_label_scope varchar(16) NOT NULL,
    new_label_scope varchar(16) NOT NULL,
    updated_by varchar(128) NOT NULL,
    updated_by_source varchar(64) NOT NULL DEFAULT 'legacy',
    updated_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_experiment_updates_experiment
    ON intent_experiment_updates(experiment_id, id DESC);

DROP TRIGGER IF EXISTS trg_intent_experiment_updates_insert_change_revision
    ON intent_experiment_updates;
CREATE TRIGGER trg_intent_experiment_updates_insert_change_revision
AFTER INSERT ON intent_experiment_updates FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
