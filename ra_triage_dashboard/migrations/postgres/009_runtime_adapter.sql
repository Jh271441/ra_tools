-- Complete the active PostgreSQL runtime contract and concurrency guards.

BEGIN;

ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS provider_id text NOT NULL DEFAULT 'kylin';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS queue_order bigserial;

CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_prediction_jobs_queue_order
    ON batch_prediction_jobs (queue_order);

CREATE UNIQUE INDEX IF NOT EXISTS idx_model_runs_single_default
    ON model_runs (is_default)
    WHERE is_default = true;

COMMIT;
