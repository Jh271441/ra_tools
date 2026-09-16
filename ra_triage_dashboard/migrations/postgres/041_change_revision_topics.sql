-- Scope the shared revision so unrelated clients do not repaint their page.

BEGIN;

CREATE TABLE IF NOT EXISTS dashboard_change_topics (
    topic text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0
);

COMMIT;
