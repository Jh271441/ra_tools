                CREATE TABLE IF NOT EXISTS inference_jobs (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT 'legacy',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    model_name TEXT NOT NULL DEFAULT '',
                    base_url TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_issue_id
                    ON inference_jobs(issue_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS batch_prediction_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL
                        CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed')),
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT 'legacy',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0 CHECK(total_count >= 0),
                    completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count >= 0),
                    success_count INTEGER NOT NULL DEFAULT 0 CHECK(success_count >= 0),
                    failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
                    provider_id TEXT NOT NULL DEFAULT 'kylin',
                    requested_model_id TEXT NOT NULL DEFAULT '',
                    resolved_model_id TEXT NOT NULL DEFAULT '',
                    model_source TEXT NOT NULL DEFAULT '',
                    catalog_sha256 TEXT NOT NULL DEFAULT '',
                    model_validation_status TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL DEFAULT '',
                    prompt_template TEXT NOT NULL DEFAULT '',
                    prompt_template_sha256 TEXT NOT NULL DEFAULT '',
                    prompt_mode TEXT NOT NULL DEFAULT '',
                    input_profile TEXT NOT NULL DEFAULT '',
                    input_config_json TEXT NOT NULL DEFAULT '{}',
                    experiment_source TEXT NOT NULL DEFAULT '',
                    config_sha256 TEXT NOT NULL DEFAULT '',
                    model_run_id TEXT REFERENCES model_runs(id) ON DELETE SET NULL,
                    publish_status TEXT NOT NULL DEFAULT 'not_requested'
                        CHECK(publish_status IN (
                            'not_requested', 'running', 'succeeded', 'partial', 'failed'
                        )),
                    autotriage_batch_id TEXT NOT NULL DEFAULT '',
                    autotriage_writer TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_created
                    ON batch_prediction_jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_requester
                    ON batch_prediction_jobs(requested_by, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_status
                    ON batch_prediction_jobs(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS batch_prediction_items (
                    job_id TEXT NOT NULL REFERENCES batch_prediction_jobs(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    autotriage_record_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY(job_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_items_issue
                    ON batch_prediction_items(issue_id, job_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_prediction_items_ordinal
                    ON batch_prediction_items(job_id, ordinal);
