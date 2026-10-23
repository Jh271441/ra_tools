
CREATE TABLE IF NOT EXISTS version_datasets (
 id text PRIMARY KEY, name text NOT NULL, release_family text NOT NULL UNIQUE,
 policy_json text NOT NULL, revision integer NOT NULL DEFAULT 0,
 run_id text NOT NULL DEFAULT '',
 created_at text NOT NULL, updated_at text NOT NULL
);
CREATE TABLE IF NOT EXISTS version_dataset_items (
 dataset_id text NOT NULL REFERENCES version_datasets(id) ON DELETE RESTRICT,
 issue_id text NOT NULL, state text NOT NULL, is_target integer NOT NULL DEFAULT 0,
 is_sample integer NOT NULL DEFAULT 0, is_low integer NOT NULL DEFAULT 0,
 software_version text NOT NULL, source_json text NOT NULL,
 binding_json text NOT NULL DEFAULT '{}', first_seen text NOT NULL, updated_at text NOT NULL,
 PRIMARY KEY(dataset_id,issue_id)
);
CREATE INDEX IF NOT EXISTS idx_version_items_state ON version_dataset_items(dataset_id,state,is_target,issue_id);
CREATE TABLE IF NOT EXISTS dataset_ingestion_batches (
 dataset_id text NOT NULL REFERENCES version_datasets(id) ON DELETE RESTRICT,
 batch_key text NOT NULL, fingerprint text NOT NULL, manifest_json text NOT NULL,
 receipt_json text NOT NULL, created_at text NOT NULL,
 PRIMARY KEY(dataset_id,batch_key)
);
CREATE TABLE IF NOT EXISTS dataset_item_sources (
 dataset_id text NOT NULL, issue_id text NOT NULL, run_id text NOT NULL,
 campaign_id text NOT NULL DEFAULT '', source_json text NOT NULL, created_at text NOT NULL,
 PRIMARY KEY(dataset_id,issue_id,run_id,campaign_id),
 FOREIGN KEY(dataset_id,issue_id) REFERENCES version_dataset_items(dataset_id,issue_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS dataset_task_bindings (
 dataset_id text NOT NULL, issue_id text NOT NULL, workflow text NOT NULL,
 run_id text NOT NULL, campaign_id text NOT NULL, assignee text NOT NULL, created_at text NOT NULL,
 PRIMARY KEY(dataset_id,issue_id,workflow),
 FOREIGN KEY(dataset_id,issue_id) REFERENCES version_dataset_items(dataset_id,issue_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS dataset_audit_events (
 id text PRIMARY KEY, dataset_id text NOT NULL REFERENCES version_datasets(id) ON DELETE RESTRICT,
 batch_key text NOT NULL, issue_id text NOT NULL DEFAULT '', action text NOT NULL,
 detail_json text NOT NULL, actor text NOT NULL, created_at text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dataset_events ON dataset_audit_events(dataset_id,created_at,id);

CREATE TABLE IF NOT EXISTS version_run_archives (
 run_id text PRIMARY KEY, dataset_id text NOT NULL, target_run_id text NOT NULL,
 archive_json text NOT NULL, archive_sha256 text NOT NULL, created_at text NOT NULL
);
