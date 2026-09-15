-- Keep an auditable history for administrator task reassignments.

BEGIN;

CREATE TABLE IF NOT EXISTS review_work_assignment_changes (
    id bigserial PRIMARY KEY,
    split_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id text NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    from_assignee varchar(128) NOT NULL,
    to_assignee varchar(128) NOT NULL,
    changed_by varchar(128) NOT NULL DEFAULT '',
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_work_assignment_changes_split
    ON review_work_assignment_changes(split_id, changed_at DESC);

COMMIT;
