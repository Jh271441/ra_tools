-- One client submission creates one comment and outbox, including lost replies.
BEGIN;
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS client_request_id text NOT NULL DEFAULT '';
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS request_fingerprint text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_comments_client_request
    ON review_comments(issue_id, lower(author), client_request_id)
    WHERE client_request_id <> '';
COMMIT;
