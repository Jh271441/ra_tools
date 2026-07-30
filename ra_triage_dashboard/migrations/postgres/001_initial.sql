-- RA Triage Workbench: PostgreSQL initial schema.
-- This mirrors the SQLite MVP tables while using JSONB and timestamptz.
-- Apply in an empty dedicated database before switching the storage adapter.

BEGIN;

CREATE TABLE IF NOT EXISTS issues (
    issue_id varchar(128) PRIMARY KEY,
    trip_id text NOT NULL DEFAULT '',
    title text NOT NULL DEFAULT '',
    scenario text NOT NULL DEFAULT '',
    summary text NOT NULL DEFAULT '',
    review_note text NOT NULL DEFAULT '',
    trail_url text NOT NULL DEFAULT '',
    gt_label varchar(32),
    gt_source text NOT NULL DEFAULT '',
    source text NOT NULL DEFAULT '',
    baseline_scope text NOT NULL DEFAULT '',
    extra_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT issues_gt_label_check
      CHECK (gt_label IS NULL OR gt_label IN ('误触发', '正确触发', '无需协助'))
);

CREATE TABLE IF NOT EXISTS annotations (
    id bigserial PRIMARY KEY,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    label varchar(32),
    review_status varchar(32) NOT NULL DEFAULT 'pending',
    tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    note text NOT NULL DEFAULT '',
    author text NOT NULL DEFAULT '',
    author_source text NOT NULL DEFAULT 'legacy',
    author_verified boolean NOT NULL DEFAULT false,
    supersedes_id bigint REFERENCES annotations(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT annotations_label_check
      CHECK (label IS NULL OR label IN ('误触发', '正确触发', '无需协助'))
);
CREATE INDEX IF NOT EXISTS idx_annotations_issue_created
    ON annotations(issue_id, id DESC);

CREATE TABLE IF NOT EXISTS review_attachments (
    id uuid PRIMARY KEY,
    annotation_id bigint NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
    original_name text NOT NULL DEFAULT '',
    stored_name text NOT NULL UNIQUE,
    media_type varchar(64) NOT NULL,
    size_bytes bigint NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_review_attachments_annotation
    ON review_attachments(annotation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS model_runs (
    id varchar(36) PRIMARY KEY,
    name text NOT NULL,
    source_name text NOT NULL DEFAULT '',
    source_sha256 varchar(64) NOT NULL UNIQUE,
    schema_version varchar(32) NOT NULL DEFAULT 'v1',
    kind varchar(32) NOT NULL DEFAULT 'upload',
    is_default boolean NOT NULL DEFAULT false,
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id bigserial PRIMARY KEY,
    model_run_id varchar(36) NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    trip_id text NOT NULL DEFAULT '',
    model_label text NOT NULL DEFAULT '',
    model_reason text NOT NULL DEFAULT '',
    model_confidence double precision,
    model_extra_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(model_run_id, issue_id)
);
CREATE INDEX IF NOT EXISTS idx_predictions_issue_run
    ON model_predictions(issue_id, model_run_id);
CREATE INDEX IF NOT EXISTS idx_issues_baseline_scope
    ON issues(baseline_scope);

CREATE TABLE IF NOT EXISTS inference_jobs (
    id varchar(36) PRIMARY KEY,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    status varchar(16) NOT NULL,
    requested_by text NOT NULL DEFAULT '',
    requested_by_source text NOT NULL DEFAULT 'legacy',
    requested_by_verified boolean NOT NULL DEFAULT false,
    model_name text NOT NULL DEFAULT '',
    base_url text NOT NULL DEFAULT '',
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_text text NOT NULL DEFAULT '',
    log_path text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT inference_jobs_status_check
      CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_issue_created
    ON inference_jobs(issue_id, created_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_annotations_author
    ON annotations(author);
CREATE INDEX IF NOT EXISTS idx_model_runs_created_by
    ON model_runs(created_by);
CREATE INDEX IF NOT EXISTS idx_jobs_requested_by
    ON inference_jobs(requested_by);

COMMIT;
