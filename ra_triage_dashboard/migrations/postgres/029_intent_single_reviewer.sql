-- A task assignment may contain a single annotator; multi-review remains optional.

BEGIN;

ALTER TABLE intent_experiments
    DROP CONSTRAINT IF EXISTS intent_experiments_overlap_reviewers_check;

ALTER TABLE intent_experiments
    ADD CONSTRAINT intent_experiments_overlap_reviewers_check
    CHECK (overlap_reviewers >= 1);

COMMIT;
