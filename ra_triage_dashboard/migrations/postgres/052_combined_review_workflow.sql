-- Atomic combined model Review + shared Case label workflow.
BEGIN;

ALTER TABLE issue_work_splits
    ADD COLUMN IF NOT EXISTS workflow_mode text NOT NULL DEFAULT 'model_review_only';
ALTER TABLE issue_work_splits
    DROP CONSTRAINT IF EXISTS issue_work_splits_workflow_mode_check;
ALTER TABLE issue_work_splits
    ADD CONSTRAINT issue_work_splits_workflow_mode_check CHECK(
        workflow_mode IN ('model_review_only', 'model_review_and_case_label')
    );

CREATE TABLE IF NOT EXISTS combined_review_submissions (
    id uuid PRIMARY KEY,
    campaign_id text NOT NULL DEFAULT '',
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    reviewer text NOT NULL,
    model_run_id text NOT NULL REFERENCES model_runs(id) ON DELETE RESTRICT,
    model_review_revision_id bigint NOT NULL
        REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    label_case_id text NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
    label_revision_id bigint REFERENCES label_revisions(id) ON DELETE RESTRICT,
    acknowledged_label_revision_id bigint
        REFERENCES label_revisions(id) ON DELETE RESTRICT,
    case_action text NOT NULL CHECK(case_action IN ('submitted', 'acknowledged')),
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint char(64) NOT NULL,
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(campaign_id, issue_id, reviewer, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_combined_review_submissions_campaign
    ON combined_review_submissions(campaign_id, reviewer, issue_id, created_at DESC);

CREATE TABLE IF NOT EXISTS combined_review_progress (
    campaign_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    reviewer text NOT NULL,
    model_review_submitted boolean NOT NULL DEFAULT false,
    case_label_acknowledged boolean NOT NULL DEFAULT false,
    model_review_revision_id bigint REFERENCES model_review_revisions(id) ON DELETE RESTRICT,
    case_label_revision_id bigint REFERENCES label_revisions(id) ON DELETE RESTRICT,
    submission_group_id uuid REFERENCES combined_review_submissions(id) ON DELETE RESTRICT,
    model_review_submitted_at timestamptz,
    case_label_acknowledged_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(campaign_id, issue_id, reviewer)
);
CREATE INDEX IF NOT EXISTS idx_combined_review_progress_campaign
    ON combined_review_progress(campaign_id, reviewer, model_review_submitted, case_label_acknowledged);

COMMIT;
