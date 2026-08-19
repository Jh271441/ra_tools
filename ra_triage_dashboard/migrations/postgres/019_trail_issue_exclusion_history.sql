-- Audit batches submitted from the Issue ID shielding workflow.
-- Entries keep the operator comment and the final per-Issue outcome so the
-- dashboard can explain partial failures without querying Trail per row.

BEGIN;

CREATE TABLE IF NOT EXISTS trail_issue_exclusion_history (
    operation_id varchar(128) PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL DEFAULT '',
    actor_source text NOT NULL DEFAULT '',
    actor_verified boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'pending',
    requested_count integer NOT NULL DEFAULT 0 CHECK (requested_count >= 0),
    synced_count integer NOT NULL DEFAULT 0 CHECK (synced_count >= 0),
    failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    entries_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    message text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_trail_issue_exclusion_history_created
    ON trail_issue_exclusion_history(created_at DESC);

COMMIT;
