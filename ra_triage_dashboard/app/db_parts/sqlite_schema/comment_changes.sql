CREATE TABLE IF NOT EXISTS comment_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_kind TEXT NOT NULL CHECK (comment_kind IN ('review', 'intent')),
    comment_id INTEGER NOT NULL,
    version_before INTEGER NOT NULL,
    version_after INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('edit', 'delete')),
    body_before TEXT NOT NULL,
    body_after TEXT NOT NULL,
    mentions_before_json TEXT NOT NULL,
    mentions_after_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_source TEXT NOT NULL,
    actor_verified INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (comment_kind, comment_id, version_after)
);
