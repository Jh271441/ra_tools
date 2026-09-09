-- Multi-review assignment snapshots and split-scoped Review versions.

BEGIN;

ALTER TABLE issue_work_splits
    ADD COLUMN IF NOT EXISTS mode varchar(16) NOT NULL DEFAULT 'single',
    ADD COLUMN IF NOT EXISTS reviewers_per_issue integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS model_run_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS assignment_count integer NOT NULL DEFAULT 0;

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS work_split_id text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_annotations_work_split_author
    ON annotations(issue_id, model_run_id, work_split_id, author, id DESC);

CREATE TABLE IF NOT EXISTS review_work_assignments (
    split_id text NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
    issue_id text NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    assignee varchar(128) NOT NULL,
    assignment_kind varchar(16) NOT NULL DEFAULT 'base'
        CHECK(assignment_kind IN ('base', 'cross', 'full')),
    ordinal integer NOT NULL DEFAULT 1 CHECK(ordinal > 0),
    assigned_by varchar(128) NOT NULL DEFAULT '',
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(split_id, issue_id, assignee)
);

CREATE INDEX IF NOT EXISTS idx_review_work_assignments_assignee
    ON review_work_assignments(assignee, ordinal);
CREATE INDEX IF NOT EXISTS idx_review_work_assignments_issue
    ON review_work_assignments(issue_id, split_id);

INSERT INTO review_work_assignments (
    split_id, issue_id, assignee, assignment_kind, ordinal,
    assigned_by, assigned_at
)
SELECT split_id, issue_id, assignee, 'base', 1, assigned_by, assigned_at
FROM issue_work_assignments
WHERE split_id <> '' AND assignee <> ''
ON CONFLICT DO NOTHING;

UPDATE issue_work_splits split
SET assignment_count = source.assignment_count
FROM (
    SELECT split_id, COUNT(*) AS assignment_count
    FROM review_work_assignments
    GROUP BY split_id
) source
WHERE split.id = source.split_id AND split.assignment_count = 0;

DO $$
DECLARE operation text;
BEGIN
    FOREACH operation IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON review_work_assignments',
            'trg_review_work_assignments_' || lower(operation) || '_change_revision'
        );
        EXECUTE format(
            'CREATE TRIGGER %I AFTER %s ON review_work_assignments FOR EACH STATEMENT '
            'EXECUTE FUNCTION bump_dashboard_change_revision()',
            'trg_review_work_assignments_' || lower(operation) || '_change_revision',
            operation
        );
    END LOOP;
END;
$$;

COMMIT;
