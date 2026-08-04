-- Persist admin Review work-split ownership so gallery filters can select by
-- assignee. Latest assignment per issue wins (issue_id primary key).

BEGIN;

CREATE TABLE IF NOT EXISTS issue_work_splits (
    id text PRIMARY KEY,
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    seed integer,
    total_count integer NOT NULL DEFAULT 0,
    filter_json text NOT NULL DEFAULT '{}',
    assignees_json text NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS issue_work_assignments (
    issue_id text PRIMARY KEY REFERENCES issues(issue_id) ON DELETE CASCADE,
    assignee text NOT NULL DEFAULT '',
    split_id text NOT NULL DEFAULT '',
    assigned_by text NOT NULL DEFAULT '',
    assigned_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_issue_work_assignments_assignee
    ON issue_work_assignments (assignee, assigned_at DESC);

COMMIT;
