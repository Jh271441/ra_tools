-- Record the requested and resolved server-side model selection without
-- persisting gateway endpoints or credentials.

BEGIN;

ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS requested_model_id text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS resolved_model_id text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS model_source text NOT NULL DEFAULT '';
ALTER TABLE batch_prediction_jobs
    ADD COLUMN IF NOT EXISTS catalog_sha256 varchar(64) NOT NULL DEFAULT '';

COMMIT;
