-- Immutable intent and append-only execution receipts. JSON is portable TEXT.
CREATE TABLE IF NOT EXISTS trail_operations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_source TEXT NOT NULL,
    actor_verified BOOLEAN NOT NULL,
    source TEXT NOT NULL,
    parent_id TEXT REFERENCES trail_operations(id),
    reason TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    item_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trail_operation_items (
    operation_id TEXT NOT NULL REFERENCES trail_operations(id),
    issue_id TEXT NOT NULL,
    field TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    PRIMARY KEY(operation_id, issue_id)
);
CREATE TABLE IF NOT EXISTS trail_operation_events (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES trail_operations(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_source TEXT NOT NULL,
    outcomes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trail_operations_time ON trail_operations(created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_trail_operations_actor ON trail_operations(actor, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trail_items_issue ON trail_operation_items(issue_id, operation_id);
CREATE INDEX IF NOT EXISTS idx_trail_events_operation ON trail_operation_events(operation_id, created_at DESC, id);
CREATE TRIGGER IF NOT EXISTS trail_operations_no_update BEFORE UPDATE ON trail_operations BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trail_operations_no_delete BEFORE DELETE ON trail_operations BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trail_items_no_update BEFORE UPDATE ON trail_operation_items BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trail_items_no_delete BEFORE DELETE ON trail_operation_items BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trail_events_no_update BEFORE UPDATE ON trail_operation_events BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trail_events_no_delete BEFORE DELETE ON trail_operation_events BEGIN SELECT RAISE(ABORT, 'Trail audit is immutable'); END;
