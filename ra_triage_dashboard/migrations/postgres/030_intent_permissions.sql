-- Existing explicitly authorized writers retain labeling and gain allocation.
-- This capability is independent from the existing Dashboard admin role.
ALTER TABLE access_users ADD COLUMN IF NOT EXISTS intent_permission TEXT NOT NULL DEFAULT 'manage'
    CHECK (intent_permission IN ('manage', 'annotate', 'view'));
