-- Additive, versioned comment edits and tombstones. Original content stays in audit.
BEGIN;
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS edited_at timestamptz;
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS updated_by text NOT NULL DEFAULT '';
ALTER TABLE intent_case_comments ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE intent_case_comments ADD COLUMN IF NOT EXISTS edited_at timestamptz;
ALTER TABLE intent_case_comments ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE intent_case_comments ADD COLUMN IF NOT EXISTS updated_by text NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS comment_changes (
    id bigserial PRIMARY KEY,
    comment_kind text NOT NULL CHECK (comment_kind IN ('review', 'intent')),
    comment_id bigint NOT NULL,
    version_before integer NOT NULL,
    version_after integer NOT NULL,
    action text NOT NULL CHECK (action IN ('edit', 'delete')),
    body_before text NOT NULL,
    body_after text NOT NULL,
    mentions_before_json jsonb NOT NULL,
    mentions_after_json jsonb NOT NULL,
    actor text NOT NULL,
    actor_source text NOT NULL,
    actor_verified boolean NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (comment_kind, comment_id, version_after)
);
COMMIT;
