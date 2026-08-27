-- Append-only Dashboard comments and their independent DChat outbox.

BEGIN;

CREATE TABLE IF NOT EXISTS review_comments (
    id bigserial PRIMARY KEY,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    model_run_id text NOT NULL DEFAULT '',
    body text NOT NULL,
    author text NOT NULL,
    author_source text NOT NULL DEFAULT 'legacy',
    author_verified boolean NOT NULL DEFAULT false,
    mentions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    reply_to_id bigint REFERENCES review_comments(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_review_comments_thread
    ON review_comments(issue_id, model_run_id, id ASC);

CREATE TABLE IF NOT EXISTS comment_notifications (
    id bigserial PRIMARY KEY,
    comment_id bigint NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
    issue_id varchar(128) NOT NULL,
    recipient varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error text NOT NULL DEFAULT '',
    trace_id varchar(128) NOT NULL DEFAULT '',
    message_unique_id varchar(256) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    UNIQUE(comment_id, recipient)
);
CREATE INDEX IF NOT EXISTS idx_comment_notifications_dispatch
    ON comment_notifications(status, next_attempt_at, id);

DROP TRIGGER IF EXISTS trg_review_comments_insert_change_revision ON review_comments;
CREATE TRIGGER trg_review_comments_insert_change_revision
AFTER INSERT ON review_comments FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
