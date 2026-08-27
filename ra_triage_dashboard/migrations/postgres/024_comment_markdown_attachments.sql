-- Markdown comment images plus the missing human display name.

BEGIN;

CREATE TABLE IF NOT EXISTS comment_attachments (
    id uuid PRIMARY KEY,
    comment_id bigint NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
    original_name text NOT NULL DEFAULT '',
    stored_name text NOT NULL UNIQUE,
    media_type varchar(64) NOT NULL,
    size_bytes bigint NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_comment_attachments_comment
    ON comment_attachments(comment_id, created_at ASC);

DROP TRIGGER IF EXISTS trg_comment_attachments_insert_change_revision ON comment_attachments;
CREATE TRIGGER trg_comment_attachments_insert_change_revision
AFTER INSERT ON comment_attachments FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

UPDATE mention_users SET display_name = '梁祥辉' WHERE username = 'liangxianghui';

COMMIT;
