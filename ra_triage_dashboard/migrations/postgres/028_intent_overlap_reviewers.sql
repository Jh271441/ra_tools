-- Allow an overlap Case to be independently reviewed by 2..N members.

BEGIN;

ALTER TABLE intent_experiments
    ADD COLUMN IF NOT EXISTS overlap_reviewers integer NOT NULL DEFAULT 2;

ALTER TABLE intent_experiments
    DROP CONSTRAINT IF EXISTS intent_experiments_overlap_reviewers_check;

ALTER TABLE intent_experiments
    ADD CONSTRAINT intent_experiments_overlap_reviewers_check
    CHECK (overlap_reviewers >= 2);

COMMIT;
