-- S5: immutable Run Collection revisions and frozen multi-Run evaluation contexts.
BEGIN;

CREATE TABLE IF NOT EXISTS run_collections (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    current_revision integer NOT NULL DEFAULT 0 CHECK(current_revision >= 0),
    metadata_revision integer NOT NULL DEFAULT 0 CHECK(metadata_revision >= 0),
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collections_idempotency
    ON run_collections(idempotency_key) WHERE idempotency_key <> '';
CREATE TABLE IF NOT EXISTS run_collection_audit (
    id text PRIMARY KEY,
    collection_id text NOT NULL REFERENCES run_collections(id) ON DELETE RESTRICT,
    action text NOT NULL,
    revision_no integer NOT NULL DEFAULT 0,
    context_id text NOT NULL DEFAULT '',
    actor text NOT NULL DEFAULT '',
    actor_source text NOT NULL DEFAULT 'legacy',
    actor_verified boolean NOT NULL DEFAULT false,
    source text NOT NULL DEFAULT 'user',
    detail_json text NOT NULL DEFAULT '{}',
    created_at text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_collection_audit_collection
    ON run_collection_audit(collection_id, created_at DESC);

CREATE OR REPLACE FUNCTION prevent_run_collection_revision_regression()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.current_revision < OLD.current_revision
       OR NEW.metadata_revision < OLD.metadata_revision THEN
        RAISE EXCEPTION 'Run Collection revisions cannot move backwards';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_run_collections_revisions_never_decrease ON run_collections;
CREATE TRIGGER trg_run_collections_revisions_never_decrease
BEFORE UPDATE ON run_collections
FOR EACH ROW EXECUTE FUNCTION prevent_run_collection_revision_regression();

CREATE TABLE IF NOT EXISTS run_collection_revisions (
    collection_id text NOT NULL REFERENCES run_collections(id) ON DELETE RESTRICT,
    revision_no integer NOT NULL CHECK(revision_no > 0),
    content_json text NOT NULL,
    content_sha256 char(64) NOT NULL,
    members_sha256 char(64) NOT NULL,
    member_count integer NOT NULL DEFAULT 0 CHECK(member_count >= 0),
    source text NOT NULL DEFAULT 'user',
    created_by text NOT NULL DEFAULT '',
    created_at text NOT NULL,
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint text NOT NULL DEFAULT '',
    PRIMARY KEY(collection_id, revision_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collection_revision_idempotency
    ON run_collection_revisions(collection_id, idempotency_key)
    WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS run_collection_members (
    collection_id text NOT NULL,
    revision_no integer NOT NULL,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    run_id text NOT NULL,
    role text NOT NULL DEFAULT '',
    is_reference boolean NOT NULL DEFAULT false,
    run_snapshot_json text NOT NULL DEFAULT '{}',
    PRIMARY KEY(collection_id, revision_no, ordinal),
    UNIQUE(collection_id, revision_no, run_id),
    FOREIGN KEY(collection_id, revision_no)
        REFERENCES run_collection_revisions(collection_id, revision_no) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_collection_single_reference
    ON run_collection_members(collection_id, revision_no) WHERE is_reference = true;
CREATE INDEX IF NOT EXISTS idx_run_collection_members_run
    ON run_collection_members(run_id, collection_id);

CREATE TABLE IF NOT EXISTS run_evaluation_exclusion_snapshots (
    content_sha256 char(64) PRIMARY KEY,
    version integer NOT NULL DEFAULT 1 CHECK(version > 0),
    issue_count integer NOT NULL DEFAULT 0 CHECK(issue_count >= 0),
    created_at text NOT NULL
);
CREATE TABLE IF NOT EXISTS run_evaluation_exclusion_items (
    content_sha256 char(64) NOT NULL REFERENCES run_evaluation_exclusion_snapshots(content_sha256)
        ON DELETE RESTRICT,
    issue_id text NOT NULL,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    PRIMARY KEY(content_sha256, issue_id),
    UNIQUE(content_sha256, ordinal)
);

CREATE TABLE IF NOT EXISTS run_evaluation_contexts (
    id text PRIMARY KEY,
    collection_id text NOT NULL,
    collection_revision integer NOT NULL,
    collection_sha256 char(64) NOT NULL,
    workset_id text NOT NULL DEFAULT '',
    workset_json text NOT NULL,
    workset_sha256 char(64) NOT NULL,
    item_count integer NOT NULL DEFAULT 0 CHECK(item_count >= 0),
    reference_type text NOT NULL CHECK(reference_type IN ('gt', 'label_result', 'run')),
    reference_id text NOT NULL DEFAULT '',
    reference_json text NOT NULL,
    reference_sha256 char(64) NOT NULL,
    scoring_policy_json text NOT NULL,
    scoring_policy_version text NOT NULL,
    scoring_policy_sha256 char(64) NOT NULL,
    exclusion_sha256 char(64) NOT NULL REFERENCES run_evaluation_exclusion_snapshots(content_sha256)
        ON DELETE RESTRICT,
    exclusion_version integer NOT NULL DEFAULT 1,
    selection_source_run_id text NOT NULL DEFAULT '',
    comparison_reference_run_id text NOT NULL DEFAULT '',
    context_sha256 char(64) NOT NULL,
    idempotency_key text NOT NULL DEFAULT '',
    idempotency_fingerprint text NOT NULL DEFAULT '',
    created_by text NOT NULL DEFAULT '',
    created_by_source text NOT NULL DEFAULT 'legacy',
    created_by_verified boolean NOT NULL DEFAULT false,
    created_at text NOT NULL,
    FOREIGN KEY(collection_id, collection_revision)
        REFERENCES run_collection_revisions(collection_id, revision_no) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_evaluation_context_idempotency
    ON run_evaluation_contexts(idempotency_key) WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_run_evaluation_context_collection
    ON run_evaluation_contexts(collection_id, collection_revision, created_at DESC);

CREATE TABLE IF NOT EXISTS run_evaluation_items (
    context_id text NOT NULL REFERENCES run_evaluation_contexts(id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    issue_id text NOT NULL,
    baseline_scope text NOT NULL DEFAULT '',
    reference_label text NOT NULL DEFAULT '',
    reference_valid boolean NOT NULL DEFAULT false,
    excluded boolean NOT NULL DEFAULT false,
    predictions_json text NOT NULL DEFAULT '{}',
    model_review_json text NOT NULL DEFAULT '{}',
    PRIMARY KEY(context_id, issue_id),
    UNIQUE(context_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_run_evaluation_items_page
    ON run_evaluation_items(context_id, ordinal);

CREATE OR REPLACE FUNCTION prevent_run_evaluation_snapshot_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Run Collection and evaluation snapshots are immutable';
END;
$$;

CREATE OR REPLACE FUNCTION prevent_extra_run_evaluation_snapshot_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_count integer;
DECLARE actual_count integer;
BEGIN
    IF TG_TABLE_NAME = 'run_collection_members' THEN
        SELECT member_count INTO expected_count FROM run_collection_revisions
        WHERE collection_id = NEW.collection_id AND revision_no = NEW.revision_no;
        SELECT COUNT(*) INTO actual_count FROM run_collection_members
        WHERE collection_id = NEW.collection_id AND revision_no = NEW.revision_no;
    ELSIF TG_TABLE_NAME = 'run_evaluation_exclusion_items' THEN
        SELECT issue_count INTO expected_count FROM run_evaluation_exclusion_snapshots
        WHERE content_sha256 = NEW.content_sha256;
        SELECT COUNT(*) INTO actual_count FROM run_evaluation_exclusion_items
        WHERE content_sha256 = NEW.content_sha256;
    ELSE
        SELECT item_count INTO expected_count FROM run_evaluation_contexts
        WHERE id = NEW.context_id;
        SELECT COUNT(*) INTO actual_count FROM run_evaluation_items
        WHERE context_id = NEW.context_id;
    END IF;
    IF expected_count IS NULL OR NEW.ordinal > expected_count OR actual_count >= expected_count THEN
        RAISE EXCEPTION 'Run Collection or evaluation snapshot item set is complete';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_run_collection_revisions_immutable ON run_collection_revisions;
CREATE TRIGGER trg_run_collection_revisions_immutable
BEFORE UPDATE OR DELETE ON run_collection_revisions
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_collection_audit_immutable ON run_collection_audit;
CREATE TRIGGER trg_run_collection_audit_immutable
BEFORE UPDATE OR DELETE ON run_collection_audit
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_collection_members_immutable ON run_collection_members;
CREATE TRIGGER trg_run_collection_members_immutable
BEFORE UPDATE OR DELETE ON run_collection_members
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_collection_members_no_extra_insert ON run_collection_members;
CREATE TRIGGER trg_run_collection_members_no_extra_insert
BEFORE INSERT ON run_collection_members
FOR EACH ROW EXECUTE FUNCTION prevent_extra_run_evaluation_snapshot_insert();
DROP TRIGGER IF EXISTS trg_run_evaluation_exclusion_snapshots_immutable ON run_evaluation_exclusion_snapshots;
CREATE TRIGGER trg_run_evaluation_exclusion_snapshots_immutable
BEFORE UPDATE OR DELETE ON run_evaluation_exclusion_snapshots
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_evaluation_exclusion_items_immutable ON run_evaluation_exclusion_items;
CREATE TRIGGER trg_run_evaluation_exclusion_items_immutable
BEFORE UPDATE OR DELETE ON run_evaluation_exclusion_items
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_evaluation_exclusion_items_no_extra_insert ON run_evaluation_exclusion_items;
CREATE TRIGGER trg_run_evaluation_exclusion_items_no_extra_insert
BEFORE INSERT ON run_evaluation_exclusion_items
FOR EACH ROW EXECUTE FUNCTION prevent_extra_run_evaluation_snapshot_insert();
DROP TRIGGER IF EXISTS trg_run_evaluation_contexts_immutable ON run_evaluation_contexts;
CREATE TRIGGER trg_run_evaluation_contexts_immutable
BEFORE UPDATE OR DELETE ON run_evaluation_contexts
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_evaluation_items_immutable ON run_evaluation_items;
CREATE TRIGGER trg_run_evaluation_items_immutable
BEFORE UPDATE OR DELETE ON run_evaluation_items
FOR EACH ROW EXECUTE FUNCTION prevent_run_evaluation_snapshot_mutation();
DROP TRIGGER IF EXISTS trg_run_evaluation_items_no_extra_insert ON run_evaluation_items;
CREATE TRIGGER trg_run_evaluation_items_no_extra_insert
BEFORE INSERT ON run_evaluation_items
FOR EACH ROW EXECUTE FUNCTION prevent_extra_run_evaluation_snapshot_insert();

COMMIT;
