-- Local adoption audit only; does not modify existing annotations or Trail.
BEGIN;
CREATE TABLE IF NOT EXISTS trail_local_imports (
    operation_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    source_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
COMMIT;
