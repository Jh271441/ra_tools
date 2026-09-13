-- Add directory-backed @ mentions and durable DChat delivery for intent discussion.
BEGIN;

ALTER TABLE intent_case_comments
    ADD COLUMN IF NOT EXISTS mentions_json jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS intent_comment_notifications (
    id bigserial PRIMARY KEY,
    comment_id bigint NOT NULL REFERENCES intent_case_comments(id) ON DELETE CASCADE,
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    recipient varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error text NOT NULL DEFAULT '',
    trace_id varchar(128) NOT NULL DEFAULT '',
    message_unique_id varchar(256) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    UNIQUE(comment_id, recipient)
);

CREATE INDEX IF NOT EXISTS idx_intent_comment_notifications_dispatch
    ON intent_comment_notifications(status, next_attempt_at, id);

COMMIT;
