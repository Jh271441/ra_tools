-- Immutable labeling dimension for intent experiment assignment snapshots.

BEGIN;

ALTER TABLE intent_experiments
    ADD COLUMN IF NOT EXISTS label_scope varchar(16) NOT NULL DEFAULT 'all';

ALTER TABLE intent_experiments
    DROP CONSTRAINT IF EXISTS intent_experiments_label_scope_check;

ALTER TABLE intent_experiments
    ADD CONSTRAINT intent_experiments_label_scope_check
    CHECK (label_scope IN ('all', 'routing', 'lane_change'));

COMMIT;
