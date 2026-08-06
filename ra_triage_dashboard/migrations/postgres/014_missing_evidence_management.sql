-- Shared missing-evidence entries are retired instead of physically deleted
-- so historical Review versions can continue to resolve their stable keys.

BEGIN;

ALTER TABLE missing_evidence_catalog
    ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;

COMMIT;
