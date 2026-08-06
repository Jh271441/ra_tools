-- Shared scene tags created from the Review form.  Entries are soft-deleted
-- so historical Review versions can continue to resolve their stable keys.

BEGIN;

ALTER TABLE review_tag_catalog
    ADD COLUMN IF NOT EXISTS hint text NOT NULL DEFAULT '';
ALTER TABLE review_tag_catalog
    ADD COLUMN IF NOT EXISTS section text NOT NULL DEFAULT 'scene';
ALTER TABLE review_tag_catalog
    ADD COLUMN IF NOT EXISTS group_key text NOT NULL DEFAULT 'environment';
ALTER TABLE review_tag_catalog
    ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;

COMMIT;
