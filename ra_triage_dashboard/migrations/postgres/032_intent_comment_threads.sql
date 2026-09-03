-- Reuse the Review discussion interaction for intent-labeling Cases.
-- The column is additive so existing intent comments remain unchanged.
BEGIN;

ALTER TABLE intent_case_comments
    ADD COLUMN IF NOT EXISTS reply_to_id bigint
    REFERENCES intent_case_comments(id);

CREATE INDEX IF NOT EXISTS idx_intent_case_comments_reply
    ON intent_case_comments(dataset_id, case_id, reply_to_id, id ASC);

COMMIT;
