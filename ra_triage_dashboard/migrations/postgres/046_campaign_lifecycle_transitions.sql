-- S4: explicit Campaign lifecycle transitions with immutable audit receipts.
BEGIN;

ALTER TABLE campaign_lifecycle_audit
    DROP CONSTRAINT IF EXISTS campaign_lifecycle_audit_action_check;
ALTER TABLE campaign_lifecycle_audit
    ADD CONSTRAINT campaign_lifecycle_audit_action_check
    CHECK(action IN ('closed', 'reopened', 'activated', 'cancelled', 'superseded'));

CREATE OR REPLACE FUNCTION prevent_closed_campaign_config_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_action text;
DECLARE audit_revision integer;
BEGIN
    IF NEW.config_revision < OLD.config_revision THEN
        RAISE EXCEPTION 'Campaign config revision cannot move backwards';
    END IF;

    IF NEW.lifecycle IS DISTINCT FROM OLD.lifecycle THEN
        expected_action := CASE
            WHEN OLD.lifecycle = 'draft' AND NEW.lifecycle = 'active' THEN 'activated'
            WHEN OLD.lifecycle IN ('draft', 'active') AND NEW.lifecycle = 'cancelled' THEN 'cancelled'
            WHEN OLD.lifecycle = 'active' AND NEW.lifecycle = 'superseded' THEN 'superseded'
            WHEN OLD.lifecycle = 'active' AND NEW.lifecycle = 'closed' THEN 'closed'
            WHEN OLD.lifecycle = 'closed' AND NEW.lifecycle = 'active' THEN 'reopened'
            ELSE NULL
        END;
        IF expected_action IS NULL THEN
            RAISE EXCEPTION 'illegal Campaign lifecycle transition: % -> %', OLD.lifecycle, NEW.lifecycle;
        END IF;

        IF expected_action = 'closed' THEN
            audit_revision := OLD.config_revision;
            IF NEW.config_revision <> OLD.config_revision
               OR NEW.closed_revision IS DISTINCT FROM OLD.config_revision
               OR COALESCE(NEW.latest_close_snapshot_id, '') = '' THEN
                RAISE EXCEPTION 'closing a Campaign requires a current close snapshot';
            END IF;
        ELSE
            audit_revision := NEW.config_revision;
            IF NEW.config_revision <= OLD.config_revision THEN
                RAISE EXCEPTION 'Campaign lifecycle changes require a new config revision';
            END IF;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM campaign_lifecycle_audit audit
            WHERE audit.campaign_id = OLD.id
              AND audit.action = expected_action
              AND audit.from_lifecycle = OLD.lifecycle
              AND audit.to_lifecycle = NEW.lifecycle
              AND audit.config_revision = audit_revision
              AND audit.idempotency_key <> ''
        ) THEN
            RAISE EXCEPTION 'Campaign lifecycle transition requires a matching audit row';
        END IF;
    END IF;

    IF OLD.lifecycle = 'closed' THEN
        IF NEW.lifecycle = 'closed' AND (
            NEW.purpose IS DISTINCT FROM OLD.purpose OR
            NEW.evaluation_run_id IS DISTINCT FROM OLD.evaluation_run_id OR
            NEW.reference_type IS DISTINCT FROM OLD.reference_type OR
            NEW.reference_id IS DISTINCT FROM OLD.reference_id OR
            NEW.reference_sha256 IS DISTINCT FROM OLD.reference_sha256 OR
            NEW.workset_id IS DISTINCT FROM OLD.workset_id OR
            NEW.selection_source_run_id IS DISTINCT FROM OLD.selection_source_run_id OR
            NEW.mode IS DISTINCT FROM OLD.mode OR
            NEW.model_run_id IS DISTINCT FROM OLD.model_run_id OR
            NEW.total_count IS DISTINCT FROM OLD.total_count OR
            NEW.assignment_count IS DISTINCT FROM OLD.assignment_count OR
            NEW.reviewers_per_issue IS DISTINCT FROM OLD.reviewers_per_issue OR
            NEW.overlap_ratio IS DISTINCT FROM OLD.overlap_ratio OR
            NEW.assignees_json IS DISTINCT FROM OLD.assignees_json OR
            NEW.campaign_name IS DISTINCT FROM OLD.campaign_name OR
            NEW.task_group_id IS DISTINCT FROM OLD.task_group_id OR
            NEW.config_revision IS DISTINCT FROM OLD.config_revision OR
            NEW.closed_by IS DISTINCT FROM OLD.closed_by OR
            NEW.closed_by_source IS DISTINCT FROM OLD.closed_by_source OR
            NEW.closed_by_verified IS DISTINCT FROM OLD.closed_by_verified OR
            NEW.closed_at IS DISTINCT FROM OLD.closed_at OR
            NEW.closed_revision IS DISTINCT FROM OLD.closed_revision OR
            NEW.latest_close_snapshot_id IS DISTINCT FROM OLD.latest_close_snapshot_id
        ) THEN
            RAISE EXCEPTION 'closed Campaign configuration is immutable';
        ELSIF NEW.lifecycle = 'active' AND (
            NEW.purpose IS DISTINCT FROM OLD.purpose OR
            NEW.evaluation_run_id IS DISTINCT FROM OLD.evaluation_run_id OR
            NEW.reference_type IS DISTINCT FROM OLD.reference_type OR
            NEW.reference_id IS DISTINCT FROM OLD.reference_id OR
            NEW.reference_sha256 IS DISTINCT FROM OLD.reference_sha256 OR
            NEW.workset_id IS DISTINCT FROM OLD.workset_id OR
            NEW.selection_source_run_id IS DISTINCT FROM OLD.selection_source_run_id OR
            NEW.mode IS DISTINCT FROM OLD.mode OR
            NEW.model_run_id IS DISTINCT FROM OLD.model_run_id OR
            NEW.total_count IS DISTINCT FROM OLD.total_count OR
            NEW.assignment_count IS DISTINCT FROM OLD.assignment_count OR
            NEW.reviewers_per_issue IS DISTINCT FROM OLD.reviewers_per_issue OR
            NEW.overlap_ratio IS DISTINCT FROM OLD.overlap_ratio OR
            NEW.assignees_json IS DISTINCT FROM OLD.assignees_json OR
            NEW.campaign_name IS DISTINCT FROM OLD.campaign_name OR
            NEW.task_group_id IS DISTINCT FROM OLD.task_group_id OR
            NEW.latest_close_snapshot_id IS DISTINCT FROM OLD.latest_close_snapshot_id
        ) THEN
            RAISE EXCEPTION 'reopening cannot change the closed Campaign configuration';
        END IF;
    ELSIF OLD.lifecycle IN ('cancelled', 'superseded') THEN
        RAISE EXCEPTION 'terminal Campaign cannot be modified';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_closed_campaign_assignment_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_lifecycle text;
DECLARE target_lifecycle text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT lifecycle INTO source_lifecycle
        FROM issue_work_splits WHERE id = OLD.split_id;
    ELSE
        SELECT lifecycle INTO target_lifecycle
        FROM issue_work_splits WHERE id = NEW.split_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT lifecycle INTO source_lifecycle
        FROM issue_work_splits WHERE id = OLD.split_id;
    END IF;
    IF target_lifecycle IN ('closed', 'cancelled', 'superseded')
       OR source_lifecycle IN ('closed', 'cancelled', 'superseded') THEN
        RAISE EXCEPTION 'terminal Campaign assignment is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_closed_campaign_member_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_lifecycle text;
DECLARE target_lifecycle text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT lifecycle INTO source_lifecycle
        FROM issue_work_splits WHERE id = OLD.campaign_id;
    ELSE
        SELECT lifecycle INTO target_lifecycle
        FROM issue_work_splits WHERE id = NEW.campaign_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT lifecycle INTO source_lifecycle
        FROM issue_work_splits WHERE id = OLD.campaign_id;
    END IF;
    IF target_lifecycle IN ('closed', 'cancelled', 'superseded')
       OR source_lifecycle IN ('closed', 'cancelled', 'superseded') THEN
        RAISE EXCEPTION 'terminal Campaign member snapshot is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
