-- Persist screenshots pasted into append-only human review versions.

BEGIN;

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

COMMIT;
