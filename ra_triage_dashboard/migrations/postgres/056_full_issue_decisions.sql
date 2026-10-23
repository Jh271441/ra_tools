-- Full Issue decisions; NULL preserves legacy classification-only semantics.
BEGIN;
ALTER TABLE issue_label_decisions ADD COLUMN IF NOT EXISTS full_result_json jsonb;
CREATE TABLE IF NOT EXISTS issue_decision_attachments (
    id text PRIMARY KEY,
    decision_id bigint NOT NULL REFERENCES issue_label_decisions(id) ON DELETE RESTRICT,
    original_name text NOT NULL DEFAULT '', stored_name text NOT NULL,
    media_type text NOT NULL, size_bytes bigint NOT NULL,
    width integer NOT NULL, height integer NOT NULL, sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_decision_attachments_decision ON issue_decision_attachments(decision_id);
COMMIT;
