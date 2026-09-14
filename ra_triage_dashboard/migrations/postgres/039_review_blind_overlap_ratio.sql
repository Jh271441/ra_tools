-- Persist the fraction of Issues that receive cross-reviewers.

BEGIN;

ALTER TABLE issue_work_splits
    ADD COLUMN IF NOT EXISTS overlap_ratio double precision NOT NULL DEFAULT 1.0
        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1);

COMMIT;
