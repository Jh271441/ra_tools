-- S4: make task purpose, lifecycle, frozen requirements, audit and discussion
-- scope explicit while preserving legacy split IDs and routes.
BEGIN;

CREATE TABLE IF NOT EXISTS review_task_groups (
    id text PRIMARY KEY,
    purpose varchar(24) NOT NULL
        CHECK(purpose IN ('labeling', 'model_review')),
    name text NOT NULL DEFAULT '',
    lifecycle varchar(24) NOT NULL DEFAULT 'draft'
        CHECK(lifecycle IN ('draft', 'active', 'closed', 'cancelled', 'superseded')),
    config_revision integer NOT NULL DEFAULT 1 CHECK(config_revision > 0),
    workset_id text NOT NULL DEFAULT '',
    source_run_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    reference_type varchar(32) NOT NULL DEFAULT '',
    reference_id text NOT NULL DEFAULT '',
    reference_sha256 char(64) NOT NULL DEFAULT '',
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint char(64) NOT NULL DEFAULT '',
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    updated_by text NOT NULL DEFAULT '',
    updated_by_source text NOT NULL DEFAULT 'legacy',
    updated_by_verified boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    closed_by text NOT NULL DEFAULT '',
    closed_by_source text NOT NULL DEFAULT 'legacy',
    closed_by_verified boolean NOT NULL DEFAULT false,
    closed_at timestamptz,
    closed_revision integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK((reference_type = '' AND reference_id = '') OR (reference_type <> '' AND reference_id <> ''))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_task_groups_idempotency
    ON review_task_groups(idempotency_key) WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_review_task_groups_purpose_lifecycle
    ON review_task_groups(purpose, lifecycle, created_at DESC);

CREATE TABLE IF NOT EXISTS review_task_group_campaigns (
    group_id text NOT NULL REFERENCES review_task_groups(id) ON DELETE RESTRICT,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    evaluation_run_id text NOT NULL DEFAULT '',
    ordinal integer NOT NULL CHECK(ordinal > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(group_id, evaluation_run_id),
    UNIQUE(campaign_id)
);

CREATE TABLE IF NOT EXISTS review_task_group_revisions (
    group_id text NOT NULL REFERENCES review_task_groups(id) ON DELETE RESTRICT,
    revision_no integer NOT NULL CHECK(revision_no > 0),
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_sha256 char(64) NOT NULL,
    changed_by text NOT NULL DEFAULT '',
    changed_by_source text NOT NULL DEFAULT 'legacy',
    changed_by_verified boolean NOT NULL DEFAULT false,
    changed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(group_id, revision_no)
);

ALTER TABLE issue_work_splits
    ADD COLUMN IF NOT EXISTS purpose varchar(24),
    ADD COLUMN IF NOT EXISTS evaluation_run_id text,
    ADD COLUMN IF NOT EXISTS reference_type varchar(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS reference_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS reference_sha256 char(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS lifecycle varchar(24) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS config_revision integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS created_by_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS created_by_verified boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS updated_by text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS updated_by_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS updated_by_verified boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS closed_by text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS closed_by_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS closed_by_verified boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS closed_at timestamptz,
    ADD COLUMN IF NOT EXISTS closed_revision integer,
    ADD COLUMN IF NOT EXISTS legacy_read_only boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS legacy_mapping_status varchar(40) NOT NULL DEFAULT 'not_inventoried',
    ADD COLUMN IF NOT EXISTS idempotency_key text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS idempotency_fingerprint char(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS campaign_name text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS task_group_id text REFERENCES review_task_groups(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS latest_close_snapshot_id text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'issue_work_splits_purpose_check') THEN
        ALTER TABLE issue_work_splits ADD CONSTRAINT issue_work_splits_purpose_check
            CHECK(purpose IS NULL OR purpose IN ('labeling', 'model_review'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'issue_work_splits_lifecycle_check') THEN
        ALTER TABLE issue_work_splits ADD CONSTRAINT issue_work_splits_lifecycle_check
            CHECK(lifecycle IN ('draft', 'active', 'closed', 'cancelled', 'superseded'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'issue_work_splits_config_revision_check') THEN
        ALTER TABLE issue_work_splits ADD CONSTRAINT issue_work_splits_config_revision_check
            CHECK(config_revision > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'issue_work_splits_reference_check') THEN
        ALTER TABLE issue_work_splits ADD CONSTRAINT issue_work_splits_reference_check
            CHECK((reference_type = '' AND reference_id = '') OR (reference_type <> '' AND reference_id <> ''));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'issue_work_splits_purpose_run_check') THEN
        ALTER TABLE issue_work_splits ADD CONSTRAINT issue_work_splits_purpose_run_check
            CHECK(purpose IS NULL OR
                  (purpose = 'labeling' AND COALESCE(evaluation_run_id, '') = '') OR
                  (purpose = 'model_review' AND COALESCE(TRIM(evaluation_run_id), '') <> ''));
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_issue_work_splits_idempotency
    ON issue_work_splits(idempotency_key) WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_issue_work_splits_campaign_listing
    ON issue_work_splits(purpose, lifecycle, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_issue_work_splits_group
    ON issue_work_splits(task_group_id, evaluation_run_id);

CREATE TABLE IF NOT EXISTS campaign_config_revisions (
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    revision_no integer NOT NULL CHECK(revision_no > 0),
    purpose varchar(24),
    workset_id text NOT NULL DEFAULT '',
    evaluation_run_id text,
    reference_type varchar(32) NOT NULL DEFAULT '',
    reference_id text NOT NULL DEFAULT '',
    lifecycle varchar(24) NOT NULL,
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    required_submitter_count integer NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
    members_sha256 char(64) NOT NULL DEFAULT '',
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_sha256 char(64) NOT NULL,
    changed_by text NOT NULL DEFAULT '',
    changed_by_source text NOT NULL DEFAULT 'legacy',
    changed_by_verified boolean NOT NULL DEFAULT false,
    change_source varchar(32) NOT NULL DEFAULT 'user',
    changed_at timestamptz NOT NULL DEFAULT now(),
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint char(64) NOT NULL DEFAULT '',
    PRIMARY KEY(campaign_id, revision_no)
);
CREATE INDEX IF NOT EXISTS idx_campaign_config_revisions_created
    ON campaign_config_revisions(campaign_id, revision_no DESC);

CREATE TABLE IF NOT EXISTS campaign_config_members (
    campaign_id text NOT NULL,
    revision_no integer NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    required_submitter_count integer NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
    reviewers_per_issue integer NOT NULL DEFAULT 0 CHECK(reviewers_per_issue >= 0),
    assignment_kinds_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(campaign_id, revision_no, issue_id),
    UNIQUE(campaign_id, revision_no, ordinal),
    FOREIGN KEY(campaign_id, revision_no)
        REFERENCES campaign_config_revisions(campaign_id, revision_no) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_campaign_config_members_issue
    ON campaign_config_members(issue_id, campaign_id, revision_no DESC);

CREATE TABLE IF NOT EXISTS campaign_issue_members (
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL DEFAULT '',
    ordinal integer NOT NULL CHECK(ordinal > 0),
    required_submitter_count integer NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
    reviewers_per_issue integer NOT NULL DEFAULT 0 CHECK(reviewers_per_issue >= 0),
    assignment_kinds_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    config_revision integer NOT NULL DEFAULT 1 CHECK(config_revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(campaign_id, issue_id),
    UNIQUE(campaign_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_campaign_issue_members_issue
    ON campaign_issue_members(issue_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_issue_members_scope
    ON campaign_issue_members(campaign_id, baseline_scope, ordinal);

CREATE TABLE IF NOT EXISTS campaign_assignment_audit (
    id bigserial PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    action varchar(24) NOT NULL
        CHECK(action IN ('assigned', 'reassigned', 'unassigned', 'legacy_snapshot')),
    assignment_kind varchar(16) NOT NULL DEFAULT 'base',
    from_assignee varchar(128) NOT NULL DEFAULT '',
    to_assignee varchar(128) NOT NULL DEFAULT '',
    changed_by varchar(128) NOT NULL DEFAULT '',
    changed_by_source text NOT NULL DEFAULT 'legacy',
    changed_by_verified boolean NOT NULL DEFAULT false,
    config_revision integer NOT NULL CHECK(config_revision > 0),
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint char(64) NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_assignment_audit_idempotency
    ON campaign_assignment_audit(campaign_id, idempotency_key)
    WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_campaign_assignment_audit_issue
    ON campaign_assignment_audit(campaign_id, issue_id, changed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS campaign_close_snapshots (
    id text PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    config_revision integer NOT NULL CHECK(config_revision > 0),
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    assigned_issue_count integer NOT NULL DEFAULT 0 CHECK(assigned_issue_count >= 0),
    required_submitter_count integer NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
    submitted_submitter_count integer NOT NULL DEFAULT 0 CHECK(submitted_submitter_count >= 0),
    completed_issue_count integer NOT NULL DEFAULT 0 CHECK(completed_issue_count >= 0),
    pending_issue_count integer NOT NULL DEFAULT 0 CHECK(pending_issue_count >= 0),
    conflict_issue_count integer NOT NULL DEFAULT 0 CHECK(conflict_issue_count >= 0),
    adjudicated_issue_count integer NOT NULL DEFAULT 0 CHECK(adjudicated_issue_count >= 0),
    stale_issue_count integer NOT NULL DEFAULT 0 CHECK(stale_issue_count >= 0),
    blocked_issue_count integer NOT NULL DEFAULT 0 CHECK(blocked_issue_count >= 0),
    status_counts_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_fingerprint char(64) NOT NULL,
    closed_by text NOT NULL DEFAULT '',
    closed_by_source text NOT NULL DEFAULT 'legacy',
    closed_by_verified boolean NOT NULL DEFAULT false,
    closed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(campaign_id, config_revision)
);
CREATE INDEX IF NOT EXISTS idx_campaign_close_snapshots_created
    ON campaign_close_snapshots(campaign_id, closed_at DESC);

CREATE TABLE IF NOT EXISTS campaign_close_snapshot_items (
    snapshot_id text NOT NULL REFERENCES campaign_close_snapshots(id) ON DELETE RESTRICT,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    required_submitter_count integer NOT NULL DEFAULT 0 CHECK(required_submitter_count >= 0),
    submitted_submitter_count integer NOT NULL DEFAULT 0 CHECK(submitted_submitter_count >= 0),
    result_state varchar(24) NOT NULL DEFAULT 'pending'
        CHECK(result_state IN ('pending', 'completed', 'conflict', 'adjudicated', 'stale', 'blocked')),
    status_counts_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_revision_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(snapshot_id, issue_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_close_snapshot_items_campaign
    ON campaign_close_snapshot_items(campaign_id, snapshot_id, issue_id);

CREATE TABLE IF NOT EXISTS campaign_lifecycle_audit (
    id bigserial PRIMARY KEY,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    action varchar(24) NOT NULL CHECK(action IN ('closed', 'reopened', 'cancelled')),
    from_lifecycle varchar(24) NOT NULL,
    to_lifecycle varchar(24) NOT NULL,
    config_revision integer NOT NULL CHECK(config_revision > 0),
    changed_by text NOT NULL DEFAULT '',
    changed_by_source text NOT NULL DEFAULT 'legacy',
    changed_by_verified boolean NOT NULL DEFAULT false,
    snapshot_id text NOT NULL DEFAULT '',
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint char(64) NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_lifecycle_audit_idempotency
    ON campaign_lifecycle_audit(campaign_id, idempotency_key)
    WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_campaign_lifecycle_audit_campaign
    ON campaign_lifecycle_audit(campaign_id, changed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS campaign_migration_map (
    source_table text NOT NULL,
    source_id text NOT NULL,
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    purpose varchar(24),
    mapping_status varchar(40) NOT NULL,
    mapping_evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_inventory_sha256 char(64) NOT NULL,
    policy_version varchar(40) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(source_table, source_id, policy_version)
);
CREATE INDEX IF NOT EXISTS idx_campaign_migration_map_campaign
    ON campaign_migration_map(campaign_id, created_at DESC);

CREATE TABLE IF NOT EXISTS campaign_reference_items (
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    baseline_scope text NOT NULL,
    reference_type varchar(32) NOT NULL
        CHECK(reference_type IN ('gt_snapshot', 'label_result_snapshot')),
    reference_id text NOT NULL,
    reference_sha256 char(64) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(campaign_id, baseline_scope)
);
CREATE INDEX IF NOT EXISTS idx_campaign_reference_items_scope
    ON campaign_reference_items(baseline_scope, campaign_id);

ALTER TABLE review_comments
    ADD COLUMN IF NOT EXISTS discussion_channel varchar(24) NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS campaign_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS baseline_scope text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS evaluation_run_id text NOT NULL DEFAULT '';

-- Preserve legacy discussion provenance without re-sending notifications.
UPDATE review_comments comment
SET discussion_channel = 'model_review',
    evaluation_run_id = comment.model_run_id,
    baseline_scope = COALESCE(issue.baseline_scope, '')
FROM issues issue
WHERE comment.issue_id = issue.issue_id
  AND comment.model_run_id <> ''
  AND NOT EXISTS (
      SELECT 1 FROM label_comment_links link WHERE link.comment_id = comment.id
  );

UPDATE review_comments comment
SET discussion_channel = CASE WHEN link.task_id <> '' THEN 'campaign' ELSE 'case' END,
    campaign_id = COALESCE(link.task_id, ''),
    baseline_scope = link.baseline_scope,
    evaluation_run_id = ''
FROM label_comment_links link
WHERE link.comment_id = comment.id;

UPDATE review_comments comment
SET discussion_channel = 'case',
    baseline_scope = COALESCE(issue.baseline_scope, '')
FROM issues issue
WHERE comment.issue_id = issue.issue_id
  AND comment.model_run_id = ''
  AND comment.discussion_channel = 'legacy'
  AND NOT EXISTS (
      SELECT 1 FROM label_comment_links link WHERE link.comment_id = comment.id
  );

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'review_comments_discussion_channel_check') THEN
        ALTER TABLE review_comments ADD CONSTRAINT review_comments_discussion_channel_check
            CHECK(discussion_channel IN ('case', 'campaign', 'model_review', 'legacy'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'review_comments_discussion_scope_check') THEN
        ALTER TABLE review_comments ADD CONSTRAINT review_comments_discussion_scope_check
            CHECK(
                discussion_channel = 'legacy'
                OR (discussion_channel = 'case' AND campaign_id = '' AND evaluation_run_id = '')
                OR (discussion_channel = 'campaign' AND campaign_id <> '' AND evaluation_run_id = '')
                OR (discussion_channel = 'model_review' AND evaluation_run_id <> '' AND campaign_id = '')
            );
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_review_comments_case_channel
    ON review_comments(baseline_scope, issue_id, discussion_channel, id ASC);
CREATE INDEX IF NOT EXISTS idx_review_comments_campaign_channel
    ON review_comments(campaign_id, issue_id, id ASC)
    WHERE discussion_channel = 'campaign';
CREATE INDEX IF NOT EXISTS idx_review_comments_run_channel
    ON review_comments(evaluation_run_id, issue_id, id ASC)
    WHERE discussion_channel = 'model_review';

CREATE OR REPLACE FUNCTION prevent_campaign_append_only_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'campaign audit and close snapshots are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_campaign_config_revisions_immutable ON campaign_config_revisions;
CREATE TRIGGER trg_campaign_config_revisions_immutable
BEFORE UPDATE OR DELETE ON campaign_config_revisions
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_config_members_immutable ON campaign_config_members;
CREATE TRIGGER trg_campaign_config_members_immutable
BEFORE UPDATE OR DELETE ON campaign_config_members
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_assignment_audit_immutable ON campaign_assignment_audit;
CREATE TRIGGER trg_campaign_assignment_audit_immutable
BEFORE UPDATE OR DELETE ON campaign_assignment_audit
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_close_snapshots_immutable ON campaign_close_snapshots;
CREATE TRIGGER trg_campaign_close_snapshots_immutable
BEFORE UPDATE OR DELETE ON campaign_close_snapshots
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_close_snapshot_items_immutable ON campaign_close_snapshot_items;
CREATE TRIGGER trg_campaign_close_snapshot_items_immutable
BEFORE UPDATE OR DELETE ON campaign_close_snapshot_items
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_lifecycle_audit_immutable ON campaign_lifecycle_audit;
CREATE TRIGGER trg_campaign_lifecycle_audit_immutable
BEFORE UPDATE OR DELETE ON campaign_lifecycle_audit
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_campaign_migration_map_immutable ON campaign_migration_map;
CREATE TRIGGER trg_campaign_migration_map_immutable
BEFORE UPDATE OR DELETE ON campaign_migration_map
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();
DROP TRIGGER IF EXISTS trg_review_task_group_revisions_immutable ON review_task_group_revisions;
CREATE TRIGGER trg_review_task_group_revisions_immutable
BEFORE UPDATE OR DELETE ON review_task_group_revisions
FOR EACH ROW EXECUTE FUNCTION prevent_campaign_append_only_mutation();

CREATE OR REPLACE FUNCTION prevent_closed_campaign_config_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.config_revision < OLD.config_revision THEN
        RAISE EXCEPTION 'Campaign config revision cannot move backwards';
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
        ELSIF NEW.lifecycle <> 'closed' AND (
            NEW.lifecycle <> 'active' OR NEW.config_revision <= OLD.config_revision
        ) THEN
            RAISE EXCEPTION 'reopening a closed Campaign requires a new active revision';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_issue_work_splits_closed_config_guard ON issue_work_splits;
CREATE TRIGGER trg_issue_work_splits_closed_config_guard
BEFORE UPDATE ON issue_work_splits
FOR EACH ROW EXECUTE FUNCTION prevent_closed_campaign_config_mutation();

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
    IF target_lifecycle = 'closed' OR source_lifecycle = 'closed' THEN
        RAISE EXCEPTION 'closed Campaign membership is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_review_work_assignments_closed_campaign ON review_work_assignments;
CREATE TRIGGER trg_review_work_assignments_closed_campaign
BEFORE INSERT OR UPDATE OR DELETE ON review_work_assignments
FOR EACH ROW EXECUTE FUNCTION prevent_closed_campaign_assignment_mutation();

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
    IF target_lifecycle = 'closed' OR source_lifecycle = 'closed' THEN
        RAISE EXCEPTION 'closed Campaign member snapshot is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_campaign_issue_members_closed_campaign ON campaign_issue_members;
CREATE TRIGGER trg_campaign_issue_members_closed_campaign
BEFORE INSERT OR UPDATE OR DELETE ON campaign_issue_members
FOR EACH ROW EXECUTE FUNCTION prevent_closed_campaign_member_mutation();

COMMIT;
