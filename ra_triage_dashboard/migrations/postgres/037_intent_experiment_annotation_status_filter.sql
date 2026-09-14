-- Record whether an intent experiment sampled all, previously labeled, or
-- never-labeled Cases. Assignment rows remain the immutable exact snapshot.

BEGIN;

ALTER TABLE intent_experiments
    ADD COLUMN IF NOT EXISTS annotation_status_filter varchar(16) NOT NULL DEFAULT 'all';

ALTER TABLE intent_experiments
    DROP CONSTRAINT IF EXISTS intent_experiments_annotation_status_filter_check;

ALTER TABLE intent_experiments
    ADD CONSTRAINT intent_experiments_annotation_status_filter_check
    CHECK (annotation_status_filter IN ('all', 'labeled', 'unlabeled'));

COMMIT;
