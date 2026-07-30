-- Persist the exact model validation tier, prompt, and Camera/RA input
-- configuration used by each dashboard Batch prediction.

BEGIN;

ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS model_validation_status text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS prompt_template text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS prompt_template_sha256 varchar(64) NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS prompt_mode text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS input_profile text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS input_config_json jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_model
    ON batch_prediction_jobs(requested_model_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt
    ON batch_prediction_jobs(prompt_version, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt_revision
    ON batch_prediction_jobs(
        prompt_version, prompt_mode, prompt_template_sha256, created_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_input
    ON batch_prediction_jobs(input_profile, created_at DESC);

COMMIT;
