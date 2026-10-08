                CREATE TABLE IF NOT EXISTS trail_issue_exclusion_history (
                    operation_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    actor_source TEXT NOT NULL DEFAULT '',
                    actor_verified INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_count INTEGER NOT NULL DEFAULT 0,
                    synced_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    entries_json TEXT NOT NULL DEFAULT '[]',
                    message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_trail_issue_exclusion_history_created
                    ON trail_issue_exclusion_history(created_at DESC);
