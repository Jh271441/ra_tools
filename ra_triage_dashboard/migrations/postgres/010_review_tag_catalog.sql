-- Shared administrator-managed custom Scenario Tags.

BEGIN;

CREATE TABLE IF NOT EXISTS review_tag_catalog (
    key text PRIMARY KEY,
    label text NOT NULL UNIQUE,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_review_tag_catalog_insert_change_revision
    ON review_tag_catalog;
CREATE TRIGGER trg_review_tag_catalog_insert_change_revision
AFTER INSERT ON review_tag_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_review_tag_catalog_update_change_revision
    ON review_tag_catalog;
CREATE TRIGGER trg_review_tag_catalog_update_change_revision
AFTER UPDATE ON review_tag_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_review_tag_catalog_delete_change_revision
    ON review_tag_catalog;
CREATE TRIGGER trg_review_tag_catalog_delete_change_revision
AFTER DELETE ON review_tag_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
