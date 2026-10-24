BEGIN;
CREATE TABLE IF NOT EXISTS trail_operations (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL,
    actor_source TEXT NOT NULL, actor_verified BOOLEAN NOT NULL,
    source TEXT NOT NULL, parent_id TEXT REFERENCES trail_operations(id),
    reason TEXT NOT NULL, fingerprint TEXT NOT NULL, item_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trail_operation_items (
    operation_id TEXT NOT NULL REFERENCES trail_operations(id), issue_id TEXT NOT NULL,
    field TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
    PRIMARY KEY(operation_id, issue_id)
);
CREATE TABLE IF NOT EXISTS trail_operation_events (
    id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES trail_operations(id),
    created_at TEXT NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL,
    actor_source TEXT NOT NULL, outcomes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trail_operations_time ON trail_operations(created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_trail_operations_actor ON trail_operations(actor, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trail_items_issue ON trail_operation_items(issue_id, operation_id);
CREATE INDEX IF NOT EXISTS idx_trail_events_operation ON trail_operation_events(operation_id, created_at DESC, id);
CREATE FUNCTION reject_trail_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Trail audit is immutable'; END; $$;
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY['trail_operations','trail_operation_items','trail_operation_events'] LOOP
        EXECUTE format('CREATE TRIGGER trail_audit_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION reject_trail_audit_mutation()', t);
        EXECUTE format('CREATE TRIGGER trail_audit_revision AFTER INSERT ON %I FOR EACH STATEMENT EXECUTE FUNCTION bump_dashboard_change_revision()', t);
    END LOOP;
END $$;
COMMIT;
