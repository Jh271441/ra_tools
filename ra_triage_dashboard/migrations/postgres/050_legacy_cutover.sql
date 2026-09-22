-- S6: append-only legacy classification, scope read policy, shadow receipts,
-- compatibility evidence and canonical exclusion projection.
BEGIN;

CREATE TABLE IF NOT EXISTS legacy_review_classifications (
    source_annotation_id bigint NOT NULL,
    baseline_scope text NOT NULL,
    classification text NOT NULL CHECK(classification IN (
        'model_review_mapped', 'label_history_mapped', 'legacy_mixed',
        'legacy_unbound_history', 'legacy_task_history'
    )),
    target_domain_type text NOT NULL DEFAULT '',
    target_domain_id text NOT NULL DEFAULT '',
    policy_version text NOT NULL,
    inventory_sha256 char(64) NOT NULL DEFAULT '',
    evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(source_annotation_id, policy_version)
);
CREATE INDEX IF NOT EXISTS idx_legacy_review_classifications_scope
    ON legacy_review_classifications(baseline_scope, classification, source_annotation_id);

CREATE TABLE IF NOT EXISTS legacy_read_policies (
    baseline_scope text PRIMARY KEY,
    policy text NOT NULL CHECK(policy IN ('legacy', 'shadow', 'canonical')),
    epoch integer NOT NULL DEFAULT 0 CHECK(epoch >= 0),
    policy_version text NOT NULL DEFAULT '',
    inventory_sha256 char(64) NOT NULL DEFAULT '',
    updated_by text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_receipt_json jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS legacy_shadow_receipts (
    id text PRIMARY KEY,
    baseline_scope text NOT NULL,
    component text NOT NULL,
    policy_version text NOT NULL,
    inventory_sha256 char(64) NOT NULL DEFAULT '',
    legacy_count integer NOT NULL DEFAULT 0,
    canonical_count integer NOT NULL DEFAULT 0,
    diff_count integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pass' CHECK(status IN ('pass', 'expected_diff', 'fail')),
    expected_diff_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    diff_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_legacy_shadow_receipts_scope
    ON legacy_shadow_receipts(baseline_scope, component, created_at DESC);

CREATE TABLE IF NOT EXISTS legacy_exclusion_projection (
    baseline_scope text NOT NULL,
    issue_id text NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
    state text NOT NULL CHECK(state IN ('none', 'candidate', 'excluded', 'conflict', 'stale')),
    source_domain text NOT NULL DEFAULT '',
    source_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_sha256 char(64) NOT NULL,
    policy_version text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(baseline_scope, issue_id)
);
CREATE INDEX IF NOT EXISTS idx_legacy_exclusion_projection_state
    ON legacy_exclusion_projection(baseline_scope, state, issue_id);

CREATE OR REPLACE FUNCTION prevent_legacy_cutover_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'S6 legacy classification/receipt history is append-only';
END;
$$;
DROP TRIGGER IF EXISTS trg_legacy_review_classifications_immutable ON legacy_review_classifications;
CREATE TRIGGER trg_legacy_review_classifications_immutable
BEFORE UPDATE OR DELETE ON legacy_review_classifications
FOR EACH ROW EXECUTE FUNCTION prevent_legacy_cutover_append_only();
DROP TRIGGER IF EXISTS trg_legacy_shadow_receipts_immutable ON legacy_shadow_receipts;
CREATE TRIGGER trg_legacy_shadow_receipts_immutable
BEFORE UPDATE OR DELETE ON legacy_shadow_receipts
FOR EACH ROW EXECUTE FUNCTION prevent_legacy_cutover_append_only();

COMMIT;
