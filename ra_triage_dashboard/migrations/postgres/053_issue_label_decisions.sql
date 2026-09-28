-- Issue-level adjudication over task and free Case-label sources.

BEGIN;

CREATE TABLE IF NOT EXISTS issue_label_decisions (
    id bigserial PRIMARY KEY,
    baseline_scope text NOT NULL,
    issue_id varchar(128) NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    expected_output text NOT NULL CHECK(expected_output IN (
        '误触发', '正确触发', '无需协助'
    )),
    source_case_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_revision_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_fingerprint char(64) NOT NULL,
    rationale text NOT NULL DEFAULT '',
    supersedes_id bigint REFERENCES issue_label_decisions(id) ON DELETE RESTRICT,
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(id, baseline_scope, issue_id)
);

CREATE INDEX IF NOT EXISTS idx_issue_label_decisions_scope_issue
    ON issue_label_decisions(baseline_scope, issue_id, id DESC);

CREATE OR REPLACE FUNCTION prevent_issue_label_decision_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Issue label decisions are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_issue_label_decisions_no_update ON issue_label_decisions;
CREATE TRIGGER trg_issue_label_decisions_no_update
BEFORE UPDATE ON issue_label_decisions
FOR EACH ROW EXECUTE FUNCTION prevent_issue_label_decision_mutation();

DROP TRIGGER IF EXISTS trg_issue_label_decisions_no_delete ON issue_label_decisions;
CREATE TRIGGER trg_issue_label_decisions_no_delete
BEFORE DELETE ON issue_label_decisions
FOR EACH ROW EXECUTE FUNCTION prevent_issue_label_decision_mutation();

ALTER TABLE label_result_snapshot_items
    ADD COLUMN IF NOT EXISTS decision_id bigint
        REFERENCES issue_label_decisions(id) ON DELETE RESTRICT;

ALTER TABLE label_gt_export_items
    ADD COLUMN IF NOT EXISTS decision_id bigint
        REFERENCES issue_label_decisions(id) ON DELETE RESTRICT;

COMMIT;
