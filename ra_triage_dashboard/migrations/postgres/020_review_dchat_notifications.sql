BEGIN;

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS mentions_json jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS review_notifications (
    id bigserial PRIMARY KEY,
    annotation_id bigint NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
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
    UNIQUE(annotation_id, recipient)
);
CREATE INDEX IF NOT EXISTS idx_review_notifications_dispatch
    ON review_notifications(status, next_attempt_at, id);

COMMIT;
