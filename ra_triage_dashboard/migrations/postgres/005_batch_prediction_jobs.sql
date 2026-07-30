-- Add auditable manual Batch prediction jobs without changing legacy
-- single-case inference history.

BEGIN;

CREATE TABLE IF NOT EXISTS batch_prediction_jobs (
    id varchar(36) PRIMARY KEY,
    name text NOT NULL DEFAULT '',
    status varchar(16) NOT NULL,
    requested_by text NOT NULL DEFAULT '',
    requested_by_source text NOT NULL DEFAULT 'legacy',
    requested_by_verified boolean NOT NULL DEFAULT false,
    total_count integer NOT NULL DEFAULT 0 CHECK (total_count >= 0),
    completed_count integer NOT NULL DEFAULT 0 CHECK (completed_count >= 0),
    success_count integer NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    model_name text NOT NULL DEFAULT '',
    prompt_version text NOT NULL DEFAULT '',
    experiment_source text NOT NULL DEFAULT '',
    config_sha256 varchar(64) NOT NULL DEFAULT '',
    model_run_id varchar(36) REFERENCES model_runs(id) ON DELETE SET NULL,
    publish_status varchar(16) NOT NULL DEFAULT 'not_requested',
    autotriage_batch_id text NOT NULL DEFAULT '',
    autotriage_writer text NOT NULL DEFAULT '',
    summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_text text NOT NULL DEFAULT '',
    log_path text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT batch_prediction_jobs_status_check
      CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed')),
    CONSTRAINT batch_prediction_jobs_publish_status_check
      CHECK (
        publish_status IN (
          'not_requested', 'running', 'succeeded', 'partial', 'failed'
        )
      )
);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_created
    ON batch_prediction_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_requester
    ON batch_prediction_jobs(requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_status
    ON batch_prediction_jobs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS batch_prediction_items (
    job_id varchar(36) NOT NULL
      REFERENCES batch_prediction_jobs(id) ON DELETE CASCADE,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    status varchar(16) NOT NULL DEFAULT 'queued',
    result_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_text text NOT NULL DEFAULT '',
    autotriage_record_id text NOT NULL DEFAULT '',
    started_at timestamptz,
    finished_at timestamptz,
    PRIMARY KEY (job_id, issue_id),
    CONSTRAINT batch_prediction_items_job_ordinal_unique
      UNIQUE (job_id, ordinal),
    CONSTRAINT batch_prediction_items_status_check
      CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_batch_prediction_items_issue
    ON batch_prediction_items(issue_id, job_id);

COMMIT;
