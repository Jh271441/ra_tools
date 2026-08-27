-- DChat mention directory. Deliberately independent from writer/admin access.

BEGIN;

CREATE TABLE IF NOT EXISTS mention_users (
    username text PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT true,
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO mention_users (username, enabled, created_by)
SELECT username, true, 'migration-021'
FROM access_users
ON CONFLICT (username) DO NOTHING;

DROP TRIGGER IF EXISTS trg_mention_users_insert_change_revision ON mention_users;
CREATE TRIGGER trg_mention_users_insert_change_revision
AFTER INSERT ON mention_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_mention_users_update_change_revision ON mention_users;
CREATE TRIGGER trg_mention_users_update_change_revision
AFTER UPDATE ON mention_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_mention_users_delete_change_revision ON mention_users;
CREATE TRIGGER trg_mention_users_delete_change_revision
AFTER DELETE ON mention_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
