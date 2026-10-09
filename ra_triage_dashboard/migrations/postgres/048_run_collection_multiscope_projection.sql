-- S5 follow-up: multi-scope frozen Worksets and shared label projections.
BEGIN;

ALTER TABLE review_worksets
    ADD COLUMN IF NOT EXISTS scope_mode text NOT NULL DEFAULT 'single',
    ADD COLUMN IF NOT EXISTS scope_count integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS scopes_sha256 char(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS selection_metadata_json text NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS review_workset_scopes (
    workset_id text NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    member_count integer NOT NULL DEFAULT 0 CHECK (member_count >= 0),
    members_sha256 char(64) NOT NULL,
    gt_snapshot_id text NOT NULL DEFAULT '',
    gt_snapshot_sha256 char(64) NOT NULL DEFAULT '',
    label_result_snapshot_id text NOT NULL DEFAULT '',
    label_result_sha256 char(64) NOT NULL DEFAULT '',
    PRIMARY KEY(workset_id, baseline_scope),
    UNIQUE(workset_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_review_workset_scopes_scope
    ON review_workset_scopes(baseline_scope, workset_id);
CREATE OR REPLACE FUNCTION prevent_run_workset_scope_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Run Evaluation Workset scope snapshots are immutable';
END;
$$;
DROP TRIGGER IF EXISTS trg_review_workset_scopes_immutable ON review_workset_scopes;
CREATE TRIGGER trg_review_workset_scopes_immutable
BEFORE UPDATE OR DELETE ON review_workset_scopes
FOR EACH ROW EXECUTE FUNCTION prevent_run_workset_scope_mutation();

ALTER TABLE run_evaluation_items
    ADD COLUMN IF NOT EXISTS shared_label_state text NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS shared_label_expected_output text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS shared_label_gt_relation text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS shared_label_method text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS shared_label_source_json text NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS shared_label_sha256 char(64) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_run_evaluation_items_scope
    ON run_evaluation_items(context_id, baseline_scope, ordinal);
CREATE INDEX IF NOT EXISTS idx_run_evaluation_context_sha
    ON run_evaluation_contexts(context_sha256, created_at, id);

COMMIT;
