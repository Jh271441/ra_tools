-- Idempotency keys for case labeling submissions, issue label decisions, and intent label saves.
BEGIN;
ALTER TABLE label_revisions ADD COLUMN IF NOT EXISTS idempotency_key text NOT NULL DEFAULT '';
ALTER TABLE label_revisions ADD COLUMN IF NOT EXISTS idempotency_fingerprint text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_label_revisions_idempotency
    ON label_revisions(label_case_id, lower(author), idempotency_key)
    WHERE idempotency_key <> '';

ALTER TABLE issue_label_decisions ADD COLUMN IF NOT EXISTS idempotency_key text NOT NULL DEFAULT '';
ALTER TABLE issue_label_decisions ADD COLUMN IF NOT EXISTS idempotency_fingerprint text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_issue_label_decisions_idempotency
    ON issue_label_decisions(baseline_scope, issue_id, lower(created_by), idempotency_key)
    WHERE idempotency_key <> '';

ALTER TABLE intent_label_revisions ADD COLUMN IF NOT EXISTS idempotency_key text NOT NULL DEFAULT '';
ALTER TABLE intent_label_revisions ADD COLUMN IF NOT EXISTS idempotency_fingerprint text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_label_revisions_idempotency
    ON intent_label_revisions(dataset_id, case_id, lower(author), idempotency_key)
    WHERE idempotency_key <> '';

ALTER TABLE batch_prediction_jobs ADD COLUMN IF NOT EXISTS publish_queued boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_publish_queue
    ON batch_prediction_jobs(created_at ASC, queue_order ASC)
    WHERE publish_queued = true;
COMMIT;
