-- Add explicit actor attribution without treating file metadata as trusted SSO.
-- Existing rows remain readable and are marked legacy/unverified.

BEGIN;

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS author_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS author_verified boolean NOT NULL DEFAULT false;

ALTER TABLE model_runs
    ADD COLUMN IF NOT EXISTS created_by text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_by_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS created_by_verified boolean NOT NULL DEFAULT false;

ALTER TABLE inference_jobs
    ADD COLUMN IF NOT EXISTS requested_by_source text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS requested_by_verified boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_annotations_author
    ON annotations(author);
CREATE INDEX IF NOT EXISTS idx_model_runs_created_by
    ON model_runs(created_by);
CREATE INDEX IF NOT EXISTS idx_jobs_requested_by
    ON inference_jobs(requested_by);

COMMIT;
