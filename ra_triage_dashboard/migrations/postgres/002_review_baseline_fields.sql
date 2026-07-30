-- Upgrade for a PostgreSQL database initialized with the older MVP schema.
-- Safe to apply once; it preserves all existing review/model history.

BEGIN;

ALTER TABLE issues
    ADD COLUMN IF NOT EXISTS baseline_scope text NOT NULL DEFAULT '';

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS review_status varchar(32) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS missing_evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE model_runs
    ADD COLUMN IF NOT EXISTS kind varchar(32) NOT NULL DEFAULT 'upload',
    ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_issues_baseline_scope
    ON issues(baseline_scope);

COMMIT;
