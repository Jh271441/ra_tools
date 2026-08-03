-- Persistent application write/admin ACL, initially seeded from environment.

BEGIN;

CREATE TABLE IF NOT EXISTS access_users (
    username text PRIMARY KEY,
    role text NOT NULL CHECK (role IN ('writer', 'admin')),
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_access_users_insert_change_revision ON access_users;
CREATE TRIGGER trg_access_users_insert_change_revision
AFTER INSERT ON access_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_access_users_update_change_revision ON access_users;
CREATE TRIGGER trg_access_users_update_change_revision
AFTER UPDATE ON access_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_access_users_delete_change_revision ON access_users;
CREATE TRIGGER trg_access_users_delete_change_revision
AFTER DELETE ON access_users FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
