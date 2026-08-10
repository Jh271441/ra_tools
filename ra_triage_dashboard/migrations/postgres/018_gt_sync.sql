-- Persist an authoritative Trail GT overlay without mutating Trail itself.

BEGIN;

CREATE TABLE IF NOT EXISTS gt_sync_state (
    baseline_scope text PRIMARY KEY,
    status varchar(32) NOT NULL DEFAULT 'not_started',
    source_name text NOT NULL DEFAULT 'Trail',
    source_view_id integer NOT NULL DEFAULT 1000,
    source_field text NOT NULL DEFAULT 'ra_merge_result',
    source_sha256 varchar(64) NOT NULL DEFAULT '',
    source_row_count integer NOT NULL DEFAULT 0 CHECK (source_row_count >= 0),
    source_updated_at timestamptz,
    source_updated_by text NOT NULL DEFAULT '',
    last_checked_at timestamptz,
    last_applied_at timestamptz,
    last_check_change_count integer NOT NULL DEFAULT 0
        CHECK (last_check_change_count >= 0),
    last_applied_change_count integer NOT NULL DEFAULT 0
        CHECK (last_applied_change_count >= 0),
    last_trigger text NOT NULL DEFAULT '',
    requested_by text NOT NULL DEFAULT '',
    requested_by_source text NOT NULL DEFAULT '',
    requested_by_verified boolean NOT NULL DEFAULT false,
    message text NOT NULL DEFAULT '',
    error_text text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS gt_sync_labels (
    baseline_scope text NOT NULL REFERENCES gt_sync_state(baseline_scope)
        ON DELETE CASCADE,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    gt_label varchar(32) NOT NULL,
    source_updated_at timestamptz,
    source_updated_by text NOT NULL DEFAULT '',
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (baseline_scope, issue_id),
    CONSTRAINT gt_sync_labels_label_check
        CHECK (gt_label IN ('误触发', '正确触发', '无需协助'))
);
CREATE INDEX IF NOT EXISTS idx_gt_sync_labels_issue
    ON gt_sync_labels(issue_id, baseline_scope);

COMMIT;
