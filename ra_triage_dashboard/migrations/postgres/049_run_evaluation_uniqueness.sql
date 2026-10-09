-- S5 follow-up: database-level Evaluation content idempotency and frozen
-- multi-scope Workset scope-set completeness.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_run_evaluation_context_sha_unique
    ON run_evaluation_contexts(context_sha256);

CREATE OR REPLACE FUNCTION prevent_extra_run_workset_scope_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_count integer;
DECLARE actual_count integer;
BEGIN
    SELECT scope_count INTO expected_count
    FROM review_worksets WHERE id = NEW.workset_id;
    SELECT COUNT(*) INTO actual_count
    FROM review_workset_scopes WHERE workset_id = NEW.workset_id;
    IF expected_count IS NULL OR NEW.ordinal > expected_count OR actual_count >= expected_count THEN
        RAISE EXCEPTION 'Run Workset scope set is complete';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_review_workset_scopes_no_extra_insert ON review_workset_scopes;
CREATE TRIGGER trg_review_workset_scopes_no_extra_insert
BEFORE INSERT ON review_workset_scopes
FOR EACH ROW EXECUTE FUNCTION prevent_extra_run_workset_scope_insert();

COMMIT;
