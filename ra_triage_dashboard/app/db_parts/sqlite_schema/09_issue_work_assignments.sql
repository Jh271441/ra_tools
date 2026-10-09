                CREATE TABLE IF NOT EXISTS issue_work_assignments (
                    issue_id TEXT PRIMARY KEY REFERENCES issues(issue_id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL DEFAULT '',
                    split_id TEXT NOT NULL DEFAULT '',
                    assigned_by TEXT NOT NULL DEFAULT '',
                    assigned_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_issue_work_assignments_assignee
                    ON issue_work_assignments(assignee, assigned_at DESC);
