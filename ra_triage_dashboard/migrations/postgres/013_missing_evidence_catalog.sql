-- Shared missing-evidence definitions created from the Review form.

BEGIN;

CREATE TABLE IF NOT EXISTS missing_evidence_catalog (
    key text PRIMARY KEY,
    label text NOT NULL UNIQUE,
    hint text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_missing_evidence_catalog_insert_change_revision
    ON missing_evidence_catalog;
CREATE TRIGGER trg_missing_evidence_catalog_insert_change_revision
AFTER INSERT ON missing_evidence_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_missing_evidence_catalog_update_change_revision
    ON missing_evidence_catalog;
CREATE TRIGGER trg_missing_evidence_catalog_update_change_revision
AFTER UPDATE ON missing_evidence_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

DROP TRIGGER IF EXISTS trg_missing_evidence_catalog_delete_change_revision
    ON missing_evidence_catalog;
CREATE TRIGGER trg_missing_evidence_catalog_delete_change_revision
AFTER DELETE ON missing_evidence_catalog FOR EACH STATEMENT
EXECUTE FUNCTION bump_dashboard_change_revision();

COMMIT;
