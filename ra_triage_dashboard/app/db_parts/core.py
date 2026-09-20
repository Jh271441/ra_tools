from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..sanitization import redact_sensitive_fields
from .shared import (
    LABELS,
    MODEL_LABELS,
    REVIEW_STATUSES,
    _PostgresConnection,
    _json,
    _json_load,
    model_label_matches_gt,
    model_prediction_match_sql,
    model_prediction_mismatch_sql,
    model_prediction_no_gt_sql,
    model_prediction_none_sql,
    utc_now,
)


class DatabaseCoreMixin:
    def __init__(
        self,
        path_or_url: Path | str,
        *,
        postgres_migrations_dir: Path | None = None,
        pool_size: int = 10,
    ):
        if isinstance(path_or_url, Path):
            self.database_url = f"sqlite:///{path_or_url.expanduser().resolve()}"
        else:
            self.database_url = str(path_or_url).strip()
        if self.database_url.startswith("postgres://"):
            self.database_url = "postgresql://" + self.database_url[len("postgres://") :]
        self.backend = (
            "postgresql"
            if self.database_url.startswith("postgresql://")
            else "sqlite"
        )
        if self.backend == "sqlite":
            prefix = "sqlite:///"
            if not self.database_url.startswith(prefix):
                raise RuntimeError("Unsupported database URL")
            self.path = Path(self.database_url[len(prefix) :]).expanduser().resolve()
        else:
            self.path = None
        self.postgres_migrations_dir = postgres_migrations_dir
        self.pool_size = max(2, min(int(pool_size), 32))
        self._pool: Any = None
        self._write_lock = threading.RLock()

    @property
    def storage_label(self) -> str:
        return "postgresql" if self.backend == "postgresql" else "sqlite-mvp"

    @contextmanager
    def connect(self) -> Any:
        if self.backend == "sqlite":
            assert self.path is not None
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        self._ensure_postgres_pool()
        with self._pool.connection() as connection:
            with connection.transaction():
                yield _PostgresConnection(connection)

    def _postgres_dependencies(self) -> tuple[Any, Any, Any]:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL 运行时需要 psycopg[binary] 与 psycopg_pool。"
            ) from exc
        return psycopg, dict_row, ConnectionPool

    def _ensure_postgres_pool(self) -> None:
        if self._pool is not None:
            return
        _, dict_row, connection_pool = self._postgres_dependencies()
        self._pool = connection_pool(
            conninfo=self.database_url,
            min_size=1,
            max_size=self.pool_size,
            timeout=30,
            kwargs={"autocommit": False, "row_factory": dict_row},
            open=True,
        )

    def _apply_postgres_migrations(self) -> None:
        if self.postgres_migrations_dir is None:
            raise RuntimeError("PostgreSQL migrations directory is required")
        migration_files = sorted(self.postgres_migrations_dir.glob("*.sql"))
        if not migration_files:
            raise RuntimeError("No PostgreSQL migrations found")
        psycopg, dict_row, _ = self._postgres_dependencies()
        with psycopg.connect(
            self.database_url, autocommit=True, row_factory=dict_row
        ) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_schema_migrations (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM dashboard_schema_migrations"
                ).fetchall()
            }
            for migration in migration_files:
                if migration.name in applied:
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO dashboard_schema_migrations (version) VALUES (%s)",
                    (migration.name,),
                )

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def change_revision(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT revision FROM dashboard_change_revision WHERE id = 1"
            ).fetchone()
        return int(row["revision"] if row else 0)

    def change_revision_state(self, since_revision: int = 0) -> dict[str, Any]:
        """Return the global revision plus domains changed since a client cursor."""

        since = max(0, int(since_revision or 0))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT revision FROM dashboard_change_revision WHERE id = 1"
            ).fetchone()
            topic_rows = conn.execute(
                "SELECT topic FROM dashboard_change_topics "
                "WHERE revision > ? ORDER BY topic",
                (since,),
            ).fetchall()
        return {
            "revision": int(row["revision"] if row else 0),
            "topics": [str(item["topic"] or "shared") for item in topic_rows],
        }

    @staticmethod
    def _mark_change_topic(conn: Any, topic: str) -> None:
        conn.execute(
            """
            INSERT INTO dashboard_change_topics (topic, revision)
            SELECT ?, revision FROM dashboard_change_revision WHERE id = 1
            ON CONFLICT(topic) DO UPDATE SET revision = excluded.revision
            """,
            (str(topic or "shared"),),
        )

    def upsert_trail_issue_exclusion_history(
        self,
        *,
        operation_id: str,
        actor: str = "",
        actor_source: str = "",
        actor_verified: bool = False,
        status: str = "pending",
        requested_count: int = 0,
        synced_count: int = 0,
        failed_count: int = 0,
        entries: Sequence[dict[str, Any]] = (),
        message: str = "",
    ) -> dict[str, Any]:
        """Persist one Issue-ID shielding batch and per-Issue outcomes.

        The preview digest is used as the operation id, so retries of the
        same immutable payload update one audit row instead of duplicating
        history.  Entry JSON keeps the operator note beside its final state
        for the expandable history view.
        """

        normalized_operation_id = str(operation_id or "").strip()
        if not normalized_operation_id:
            raise ValueError("Trail Issue 屏蔽历史缺少 operation_id。")
        normalized_status = str(status or "pending").strip() or "pending"
        normalized_entries: list[dict[str, Any]] = []
        for entry in entries or ():
            if not isinstance(entry, dict):
                continue
            normalized_entry: dict[str, Any] = {
                "issue_id": str(entry.get("issue_id") or "").strip(),
                "comment": str(entry.get("comment") or "").strip()[:4000],
                "status": str(entry.get("status") or "pending").strip() or "pending",
                "detail": str(entry.get("detail") or "").strip()[:1000],
            }
            # The API only supplies this object after it has been matched to a
            # loaded workbook.  Keep a bounded copy in the durable history so
            # a later reviewer can see the original Excel source rather than
            # inferring it from a free-text comment.
            source = entry.get("source")
            if isinstance(source, dict):
                text_fields = (
                    "kind",
                    "source_id",
                    "label",
                    "baseline_id",
                    "filename",
                    "sha256",
                    "issue_id",
                    "column",
                    "value",
                )
                normalized_source = {
                    key: str(source.get(key) or "").strip()[:512]
                    for key in text_fields
                    if str(source.get(key) or "").strip()
                }
                try:
                    row_number = int(source.get("row_number"))
                except (TypeError, ValueError):
                    row_number = 0
                if row_number > 0:
                    normalized_source["row_number"] = row_number
                if normalized_source:
                    normalized_entry["source"] = normalized_source
            normalized_entries.append(normalized_entry)
        now = utc_now()
        values = (
            normalized_operation_id,
            now,
            now,
            str(actor or "").strip(),
            str(actor_source or "").strip(),
            # PostgreSQL's ``actor_verified`` column is a native boolean,
            # while SQLite accepts Python bool values as its legacy integer
            # representation.  Do not bind 0/1 here: psycopg correctly
            # rejects a smallint for a boolean column and would otherwise
            # make the best-effort audit write disappear after a successful
            # Trail submission.
            bool(actor_verified),
            normalized_status,
            max(0, int(requested_count)),
            max(0, int(synced_count)),
            max(0, int(failed_count)),
            _json(normalized_entries),
            str(message or "").strip()[:4000],
        )
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT created_at FROM trail_issue_exclusion_history WHERE operation_id = ?",
                (normalized_operation_id,),
            ).fetchone()
            if current is None:
                conn.execute(
                    """
                    INSERT INTO trail_issue_exclusion_history (
                        operation_id, created_at, updated_at, actor, actor_source,
                        actor_verified, status, requested_count, synced_count,
                        failed_count, entries_json, message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                conn.execute(
                    """
                    UPDATE trail_issue_exclusion_history
                    SET updated_at = ?, actor = ?, actor_source = ?, actor_verified = ?,
                        status = ?, requested_count = ?, synced_count = ?,
                        failed_count = ?, entries_json = ?, message = ?
                    WHERE operation_id = ?
                    """,
                    (
                        now,
                        values[3],
                        values[4],
                        values[5],
                        values[6],
                        values[7],
                        values[8],
                        values[9],
                        values[10],
                        values[11],
                        normalized_operation_id,
                    ),
                )
            row = conn.execute(
                """
                SELECT operation_id, created_at, updated_at, actor, actor_source,
                       actor_verified, status, requested_count, synced_count,
                       failed_count, entries_json, message
                FROM trail_issue_exclusion_history
                WHERE operation_id = ?
                """,
                (normalized_operation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Trail Issue 屏蔽历史写入后无法读取。")
        return self._trail_issue_exclusion_history_row(row)

    def list_trail_issue_exclusion_history(
        self, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Return recent shielding batches with per-Issue outcomes."""

        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        with self.connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS total FROM trail_issue_exclusion_history"
            ).fetchone()
            rows = conn.execute(
                """
                SELECT operation_id, created_at, updated_at, actor, actor_source,
                       actor_verified, status, requested_count, synced_count,
                       failed_count, entries_json, message
                FROM trail_issue_exclusion_history
                ORDER BY created_at DESC, operation_id DESC
                LIMIT ? OFFSET ?
                """,
                (normalized_limit, normalized_offset),
            ).fetchall()
        return {
            "items": [self._trail_issue_exclusion_history_row(row) for row in rows],
            "total": int(total_row["total"] if total_row else 0),
            "limit": normalized_limit,
            "offset": normalized_offset,
        }

    @staticmethod
    def _trail_issue_exclusion_history_row(row: Any) -> dict[str, Any]:
        entries = _json_load(row["entries_json"], [])
        if not isinstance(entries, list):
            entries = []
        return {
            "operation_id": str(row["operation_id"] or ""),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "actor": str(row["actor"] or ""),
            "actor_source": str(row["actor_source"] or ""),
            "actor_verified": bool(row["actor_verified"]),
            "status": str(row["status"] or "pending"),
            "requested_count": int(row["requested_count"] or 0),
            "synced_count": int(row["synced_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "entries": entries,
            "message": str(row["message"] or ""),
        }

    def runtime_status(self, *, persistent_data: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        with self.connect() as conn:
            if self.backend == "postgresql":
                row = conn.execute(
                    """
                    SELECT current_setting('server_version') AS server_version,
                           (SELECT revision FROM dashboard_change_revision WHERE id = 1)
                               AS revision,
                           (SELECT COUNT(*) FROM dashboard_schema_migrations)
                               AS migration_count
                    """
                ).fetchone()
                result = {
                    "ok": True,
                    "backend": "postgresql",
                    "server_version": str(row["server_version"] or ""),
                    "persistent_data": persistent_data,
                    "revision": int(row["revision"] or 0),
                    "migration_count": int(row["migration_count"] or 0),
                    "pool_max_size": self.pool_size,
                }
            else:
                row = conn.execute(
                    "SELECT revision FROM dashboard_change_revision WHERE id = 1"
                ).fetchone()
                sqlite_version = conn.execute(
                    "SELECT sqlite_version() AS version"
                ).fetchone()
                result = {
                    "ok": True,
                    "backend": "sqlite",
                    "server_version": str(sqlite_version["version"] or ""),
                    "persistent_data": False,
                    "revision": int(row["revision"] if row else 0),
                    "migration_count": 0,
                    "pool_max_size": 0,
                }
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result

    def init(self) -> None:
        if self.backend == "postgresql":
            self._apply_postgres_migrations()
        with self._write_lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS issues (
                    issue_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    scenario TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT '',
                    trail_url TEXT NOT NULL DEFAULT '',
                    gt_label TEXT,
                    gt_source TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    baseline_scope TEXT NOT NULL DEFAULT '',
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    model_run_id TEXT NOT NULL DEFAULT '',
                    work_split_id TEXT NOT NULL DEFAULT '',
                    label TEXT,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    missing_evidence_json TEXT NOT NULL DEFAULT '[]',
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES annotations(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotations_issue_id
                    ON annotations(issue_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_annotations_issue_run_id
                    ON annotations(issue_id, model_run_id, id DESC);

                CREATE TABLE IF NOT EXISTS review_attachments (
                    id TEXT PRIMARY KEY,
                    annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_attachments_annotation
                    ON review_attachments(annotation_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS review_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    annotation_id INTEGER NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    message_unique_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(annotation_id, recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_review_notifications_dispatch
                    ON review_notifications(status, next_attempt_at, id);

                CREATE TABLE IF NOT EXISTS review_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    model_run_id TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    reply_to_id INTEGER REFERENCES review_comments(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_comments_thread
                    ON review_comments(issue_id, model_run_id, id ASC);

                CREATE TABLE IF NOT EXISTS comment_attachments (
                    id TEXT PRIMARY KEY,
                    comment_id INTEGER NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_comment_attachments_comment
                    ON comment_attachments(comment_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS comment_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    message_unique_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(comment_id, recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_comment_notifications_dispatch
                    ON comment_notifications(status, next_attempt_at, id);

                CREATE TABLE IF NOT EXISTS model_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL DEFAULT 'v1',
                    kind TEXT NOT NULL DEFAULT 'upload',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    trip_id TEXT NOT NULL DEFAULT '',
                    model_label TEXT NOT NULL DEFAULT '',
                    model_reason TEXT NOT NULL DEFAULT '',
                    model_confidence REAL,
                    model_extra_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(model_run_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_issue_id
                    ON model_predictions(issue_id, model_run_id);

                CREATE TABLE IF NOT EXISTS inference_jobs (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT 'legacy',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    model_name TEXT NOT NULL DEFAULT '',
                    base_url TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_issue_id
                    ON inference_jobs(issue_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS batch_prediction_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL
                        CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed')),
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT 'legacy',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0 CHECK(total_count >= 0),
                    completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count >= 0),
                    success_count INTEGER NOT NULL DEFAULT 0 CHECK(success_count >= 0),
                    failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
                    provider_id TEXT NOT NULL DEFAULT 'kylin',
                    requested_model_id TEXT NOT NULL DEFAULT '',
                    resolved_model_id TEXT NOT NULL DEFAULT '',
                    model_source TEXT NOT NULL DEFAULT '',
                    catalog_sha256 TEXT NOT NULL DEFAULT '',
                    model_validation_status TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL DEFAULT '',
                    prompt_template TEXT NOT NULL DEFAULT '',
                    prompt_template_sha256 TEXT NOT NULL DEFAULT '',
                    prompt_mode TEXT NOT NULL DEFAULT '',
                    input_profile TEXT NOT NULL DEFAULT '',
                    input_config_json TEXT NOT NULL DEFAULT '{}',
                    experiment_source TEXT NOT NULL DEFAULT '',
                    config_sha256 TEXT NOT NULL DEFAULT '',
                    model_run_id TEXT REFERENCES model_runs(id) ON DELETE SET NULL,
                    publish_status TEXT NOT NULL DEFAULT 'not_requested'
                        CHECK(publish_status IN (
                            'not_requested', 'running', 'succeeded', 'partial', 'failed'
                        )),
                    autotriage_batch_id TEXT NOT NULL DEFAULT '',
                    autotriage_writer TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_created
                    ON batch_prediction_jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_requester
                    ON batch_prediction_jobs(requested_by, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_status
                    ON batch_prediction_jobs(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS batch_prediction_items (
                    job_id TEXT NOT NULL REFERENCES batch_prediction_jobs(id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    autotriage_record_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY(job_id, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_batch_prediction_items_issue
                    ON batch_prediction_items(issue_id, job_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_prediction_items_ordinal
                    ON batch_prediction_items(job_id, ordinal);

                CREATE TABLE IF NOT EXISTS dashboard_change_revision (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO dashboard_change_revision (
                    id, revision, updated_at
                ) VALUES (1, 0, '');

                CREATE TABLE IF NOT EXISTS dashboard_change_topics (
                    topic TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS gt_sync_state (
                    baseline_scope TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'not_started',
                    source_name TEXT NOT NULL DEFAULT 'Trail',
                    source_view_id INTEGER NOT NULL DEFAULT 1000,
                    source_field TEXT NOT NULL DEFAULT 'ra_merge_result',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    source_row_count INTEGER NOT NULL DEFAULT 0,
                    source_updated_at TEXT,
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT,
                    last_applied_at TEXT,
                    last_check_change_count INTEGER NOT NULL DEFAULT 0,
                    last_applied_change_count INTEGER NOT NULL DEFAULT 0,
                    last_trigger TEXT NOT NULL DEFAULT '',
                    requested_by TEXT NOT NULL DEFAULT '',
                    requested_by_source TEXT NOT NULL DEFAULT '',
                    requested_by_verified INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS gt_sync_labels (
                    baseline_scope TEXT NOT NULL REFERENCES gt_sync_state(baseline_scope)
                        ON DELETE CASCADE,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    gt_label TEXT NOT NULL CHECK(gt_label IN ('误触发', '正确触发', '无需协助')),
                    source_updated_at TEXT,
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (baseline_scope, issue_id)
                );
                CREATE INDEX IF NOT EXISTS idx_gt_sync_labels_issue
                    ON gt_sync_labels(issue_id, baseline_scope);

                CREATE TABLE IF NOT EXISTS gt_snapshots (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    gt_mode TEXT NOT NULL CHECK(gt_mode IN ('strict', 'sparse')),
                    source_name TEXT NOT NULL DEFAULT 'Trail',
                    source_view_id INTEGER NOT NULL DEFAULT 0,
                    source_field TEXT NOT NULL DEFAULT '',
                    source_metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_sha256 TEXT NOT NULL,
                    membership_sha256 TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    valid_label_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'system',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(baseline_scope, content_sha256),
                    UNIQUE(id, baseline_scope),
                    UNIQUE(id, baseline_scope, content_sha256),
                    CHECK(valid_label_count <= member_count)
                );
                CREATE INDEX IF NOT EXISTS idx_gt_snapshots_scope_created
                    ON gt_snapshots(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS gt_snapshot_items (
                    snapshot_id TEXT NOT NULL,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    gt_label TEXT NOT NULL DEFAULT '' CHECK(gt_label IN ('', '误触发', '正确触发', '无需协助')),
                    source_updated_at TEXT NOT NULL DEFAULT '',
                    source_updated_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(snapshot_id, issue_id),
                    UNIQUE(snapshot_id, ordinal),
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_gt_snapshot_items_scope_issue
                    ON gt_snapshot_items(baseline_scope, issue_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS gt_snapshot_active (
                    baseline_scope TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    activated_by TEXT NOT NULL DEFAULT '',
                    activated_by_source TEXT NOT NULL DEFAULT 'system',
                    activated_by_verified INTEGER NOT NULL DEFAULT 0,
                    activation_reason TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES gt_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS review_tag_catalog (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    hint TEXT NOT NULL DEFAULT '',
                    section TEXT NOT NULL DEFAULT 'scene',
                    group_key TEXT NOT NULL DEFAULT 'environment',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS missing_evidence_catalog (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    hint TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS access_users (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('writer', 'admin')),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mention_users (
                    username TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS issue_work_splits (
                    id TEXT PRIMARY KEY,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    seed INTEGER,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    filter_json TEXT NOT NULL DEFAULT '{}',
                    assignees_json TEXT NOT NULL DEFAULT '[]',
                    overlap_ratio REAL NOT NULL DEFAULT 1.0
                        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1)
                );

                CREATE TABLE IF NOT EXISTS review_work_assignments (
                    split_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL,
                    assignment_kind TEXT NOT NULL DEFAULT 'base'
                        CHECK(assignment_kind IN ('base', 'cross', 'full')),
                    ordinal INTEGER NOT NULL DEFAULT 1 CHECK(ordinal > 0),
                    assigned_by TEXT NOT NULL DEFAULT '',
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY(split_id, issue_id, assignee)
                );
                CREATE INDEX IF NOT EXISTS idx_review_work_assignments_assignee
                    ON review_work_assignments(assignee, ordinal);
                CREATE INDEX IF NOT EXISTS idx_review_work_assignments_issue
                    ON review_work_assignments(issue_id, split_id);

                CREATE TABLE IF NOT EXISTS review_work_assignment_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    split_id TEXT NOT NULL REFERENCES issue_work_splits(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
                    from_assignee TEXT NOT NULL,
                    to_assignee TEXT NOT NULL,
                    changed_by TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_work_assignment_changes_split
                    ON review_work_assignment_changes(split_id, changed_at DESC);

                CREATE TABLE IF NOT EXISTS review_worksets (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    selection_source_run_id TEXT NOT NULL DEFAULT '',
                    source_filter_json TEXT NOT NULL DEFAULT '{}',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    members_sha256 TEXT NOT NULL,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_worksets_scope_created
                    ON review_worksets(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS review_workset_items (
                    workset_id TEXT NOT NULL
                        REFERENCES review_worksets(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    PRIMARY KEY(workset_id, issue_id),
                    UNIQUE(workset_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_review_workset_items_issue
                    ON review_workset_items(issue_id, workset_id);

                CREATE TABLE IF NOT EXISTS label_cases (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    seen_gt_label TEXT NOT NULL DEFAULT '',
                    seen_gt_source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(baseline_scope, issue_id, task_id, source_run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_label_cases_scope_issue
                    ON label_cases(baseline_scope, issue_id, task_id);

                CREATE TABLE IF NOT EXISTS label_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label_case_id TEXT NOT NULL
                        REFERENCES label_cases(id) ON DELETE RESTRICT,
                    expected_output TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    evidence_gaps_json TEXT NOT NULL DEFAULT '[]',
                    rationale TEXT NOT NULL DEFAULT '',
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    revision_kind TEXT NOT NULL DEFAULT 'submission'
                        CHECK(revision_kind IN ('submission', 'adjudication', 'legacy')),
                    supersedes_id INTEGER REFERENCES label_revisions(id),
                    source_annotation_id INTEGER UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_revisions_case_author
                    ON label_revisions(label_case_id, author, id DESC);

                CREATE TABLE IF NOT EXISTS label_attachments (
                    id TEXT PRIMARY KEY,
                    revision_id INTEGER NOT NULL
                        REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_review_attachment_id TEXT UNIQUE,
                    original_name TEXT NOT NULL DEFAULT '',
                    stored_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_attachments_revision
                    ON label_attachments(revision_id, created_at);

                CREATE TABLE IF NOT EXISTS label_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label_case_id TEXT NOT NULL
                        REFERENCES label_cases(id) ON DELETE RESTRICT,
                    method TEXT NOT NULL CHECK(method IN ('adjudication')),
                    result_revision_id INTEGER NOT NULL
                        REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    supersedes_id INTEGER REFERENCES label_resolutions(id),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_resolutions_case
                    ON label_resolutions(label_case_id, id DESC);

                CREATE TABLE IF NOT EXISTS label_migration_map (
                    source_table TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_table TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_table, source_id, target_table, policy_version)
                );

                CREATE TABLE IF NOT EXISTS label_gt_export_batches (
                    id TEXT PRIMARY KEY,
                    baseline_scopes_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'preview'
                        CHECK(status IN ('preview', 'exported', 'stale')),
                    item_count INTEGER NOT NULL DEFAULT 0,
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    exported_at TEXT,
                    source_gt_snapshot_id TEXT REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
                    source_gt_snapshot_ids_json TEXT NOT NULL DEFAULT '{}',
                    source_gt_snapshot_sha256 TEXT NOT NULL DEFAULT '',
                    reconcile_status TEXT NOT NULL DEFAULT 'not_checked'
                        CHECK(reconcile_status IN ('not_checked', 'matched', 'partial', 'not_applied', 'changed_again', 'error')),
                    reconcile_error TEXT NOT NULL DEFAULT '',
                    reconciled_at TEXT,
                    reconciled_count INTEGER NOT NULL DEFAULT 0,
                    not_applied_count INTEGER NOT NULL DEFAULT 0,
                    changed_again_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS label_gt_export_items (
                    batch_id TEXT NOT NULL
                        REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    old_gt_label TEXT NOT NULL DEFAULT '',
                    expected_output TEXT NOT NULL,
                    source_revision_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_fingerprint TEXT NOT NULL,
                    reconcile_status TEXT NOT NULL DEFAULT 'not_checked'
                        CHECK(reconcile_status IN ('not_checked', 'matched', 'not_applied', 'changed_again', 'error')),
                    reconciled_snapshot_id TEXT REFERENCES gt_snapshots(id) ON DELETE RESTRICT,
                    reconciled_at TEXT,
                    PRIMARY KEY(batch_id, issue_id)
                );

                CREATE TABLE IF NOT EXISTS label_result_snapshots (
                    id TEXT PRIMARY KEY,
                    baseline_scope TEXT NOT NULL,
                    workset_id TEXT NOT NULL REFERENCES review_worksets(id) ON DELETE RESTRICT,
                    workset_members_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    resolved_count INTEGER NOT NULL DEFAULT 0,
                    pending_count INTEGER NOT NULL DEFAULT 0,
                    conflict_count INTEGER NOT NULL DEFAULT 0,
                    stale_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    coverage_status TEXT NOT NULL DEFAULT 'complete'
                        CHECK(coverage_status IN ('complete', 'partial')),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(workset_id, content_sha256),
                    UNIQUE(id, baseline_scope),
                    CHECK(member_count = resolved_count + pending_count + conflict_count + stale_count + unknown_count)
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshots_scope_created
                    ON label_result_snapshots(baseline_scope, created_at DESC);

                CREATE TABLE IF NOT EXISTS label_result_snapshot_items (
                    snapshot_id TEXT NOT NULL,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    state TEXT NOT NULL CHECK(state IN ('none', 'pending', 'resolved', 'conflict', 'stale')),
                    expected_output TEXT CHECK(expected_output IS NULL OR expected_output IN ('误触发', '正确触发', '无需协助')),
                    method TEXT NOT NULL CHECK(method IN ('single', 'consensus', 'adjudication')),
                    gt_relation TEXT NOT NULL DEFAULT 'unknown'
                        CHECK(gt_relation IN ('matches_gt', 'differs_from_gt', 'fills_missing_gt', 'unknown')),
                    PRIMARY KEY(snapshot_id, issue_id),
                    UNIQUE(snapshot_id, ordinal),
                    FOREIGN KEY(snapshot_id, baseline_scope)
                        REFERENCES label_result_snapshots(id, baseline_scope) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_items_scope_issue
                    ON label_result_snapshot_items(baseline_scope, issue_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS label_result_snapshot_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL REFERENCES label_result_snapshots(id) ON DELETE RESTRICT,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    label_case_id TEXT NOT NULL REFERENCES label_cases(id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    resolution_id INTEGER REFERENCES label_resolutions(id) ON DELETE RESTRICT,
                    revision_id INTEGER REFERENCES label_revisions(id) ON DELETE RESTRICT,
                    source_role TEXT NOT NULL DEFAULT 'head'
                        CHECK(source_role IN ('case', 'head', 'resolution_input', 'resolution_result')),
                    source_key TEXT NOT NULL,
                    UNIQUE(snapshot_id, source_key),
                    FOREIGN KEY(snapshot_id, issue_id)
                        REFERENCES label_result_snapshot_items(snapshot_id, issue_id) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_label_result_snapshot_sources_case
                    ON label_result_snapshot_sources(label_case_id, snapshot_id);

                CREATE TABLE IF NOT EXISTS label_gt_export_source_snapshots (
                    batch_id TEXT NOT NULL
                        REFERENCES label_gt_export_batches(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    PRIMARY KEY(batch_id, baseline_scope),
                    FOREIGN KEY(snapshot_id, baseline_scope, content_sha256)
                        REFERENCES gt_snapshots(id, baseline_scope, content_sha256) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS label_comment_links (
                    comment_id INTEGER PRIMARY KEY
                        REFERENCES review_comments(id) ON DELETE RESTRICT,
                    baseline_scope TEXT NOT NULL,
                    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    policy_version TEXT NOT NULL,
                    linked_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_label_comment_links_scope
                    ON label_comment_links(baseline_scope, issue_id, task_id);

                CREATE TABLE IF NOT EXISTS labeling_scope_state (
                    baseline_scope TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'shadow'
                        CHECK(status IN ('shadow', 'active', 'paused')),
                    policy_version TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 0,
                    source_inventory_sha256 TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS issue_work_assignments (
                    issue_id TEXT PRIMARY KEY REFERENCES issues(issue_id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL DEFAULT '',
                    split_id TEXT NOT NULL DEFAULT '',
                    assigned_by TEXT NOT NULL DEFAULT '',
                    assigned_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_issue_work_assignments_assignee
                    ON issue_work_assignments(assignee, assigned_at DESC);

                CREATE TABLE IF NOT EXISTS intent_label_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    routing_default TEXT
                        CHECK(routing_default IS NULL OR routing_default IN (
                            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
                        )),
                    lane_change_default TEXT
                        CHECK(lane_change_default IS NULL OR lane_change_default IN (
                            'lane_change', 'no_lane_change',
                            'left_lane_change', 'right_lane_change'
                        )),
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES intent_label_revisions(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_label_revisions_case
                    ON intent_label_revisions(dataset_id, case_id, id DESC);

                CREATE TABLE IF NOT EXISTS intent_frame_overrides (
                    revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id) ON DELETE CASCADE,
                    timepoint_id TEXT NOT NULL,
                    offset_ms INTEGER NOT NULL,
                    routing_intent TEXT
                        CHECK(routing_intent IS NULL OR routing_intent IN (
                            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
                        )),
                    lane_change_intent TEXT
                        CHECK(lane_change_intent IS NULL OR lane_change_intent IN (
                            'lane_change', 'no_lane_change',
                            'left_lane_change', 'right_lane_change'
                        )),
                    PRIMARY KEY (revision_id, timepoint_id),
                    CHECK(routing_intent IS NOT NULL OR lane_change_intent IS NOT NULL)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_frame_overrides_offset
                    ON intent_frame_overrides(revision_id, offset_ms ASC);

                CREATE TABLE IF NOT EXISTS intent_label_heads (
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    current_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, case_id)
                );
                UPDATE intent_label_revisions
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                UPDATE intent_label_heads
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';

                CREATE TABLE IF NOT EXISTS intent_user_label_heads (
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    current_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, case_id, username)
                );
                UPDATE intent_user_label_heads
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                INSERT OR IGNORE INTO intent_user_label_heads (
                    dataset_id, case_id, username, current_revision_id,
                    version, updated_at
                )
                SELECT head.dataset_id, head.case_id,
                       lower(CASE WHEN revision.author = '' THEN 'legacy' ELSE revision.author END),
                       head.current_revision_id, head.version, head.updated_at
                FROM intent_label_heads head
                JOIN intent_label_revisions revision
                  ON revision.id = head.current_revision_id;

                CREATE TABLE IF NOT EXISTS intent_label_deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    deleted_revision_id INTEGER NOT NULL
                        REFERENCES intent_label_revisions(id),
                    deleted_by TEXT NOT NULL,
                    deleted_by_source TEXT NOT NULL DEFAULT 'legacy',
                    deleted_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_label_deletions_case
                    ON intent_label_deletions(dataset_id, case_id, username, id DESC);

                CREATE TABLE IF NOT EXISTS intent_case_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    reply_to_id INTEGER REFERENCES intent_case_comments(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_case_comments_case
                    ON intent_case_comments(dataset_id, case_id, id ASC);

                CREATE TABLE IF NOT EXISTS intent_comment_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL REFERENCES intent_case_comments(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'retry', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    message_unique_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(comment_id, recipient)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_comment_notifications_dispatch
                    ON intent_comment_notifications(status, next_attempt_at, id);

                CREATE TABLE IF NOT EXISTS intent_experiments (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    annotation_mode TEXT NOT NULL
                        CHECK(annotation_mode IN ('blind', 'full')),
                    label_scope TEXT NOT NULL DEFAULT 'all'
                        CHECK(label_scope IN ('all', 'routing', 'lane_change')),
                    annotation_status_filter TEXT NOT NULL DEFAULT 'all'
                        CHECK(annotation_status_filter IN ('all', 'labeled', 'unlabeled')),
                    overlap_ratio REAL NOT NULL DEFAULT 0
                        CHECK(overlap_ratio >= 0 AND overlap_ratio <= 1),
                    overlap_reviewers INTEGER NOT NULL DEFAULT 2
                        CHECK(overlap_reviewers >= 1),
                    case_count INTEGER NOT NULL DEFAULT 0 CHECK(case_count >= 0),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'closed')),
                    seed INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_by_source TEXT NOT NULL DEFAULT 'legacy',
                    created_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    closed_by TEXT NOT NULL DEFAULT '',
                    closed_at TEXT,
                    UNIQUE(dataset_id, name)
                );
                UPDATE intent_experiments
                SET dataset_id = '0206-1335-v1'
                WHERE dataset_id = '0206-full2804-v1';
                CREATE INDEX IF NOT EXISTS idx_intent_experiments_dataset
                    ON intent_experiments(dataset_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS intent_experiment_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL
                        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
                    old_name TEXT NOT NULL,
                    new_name TEXT NOT NULL,
                    old_label_scope TEXT NOT NULL,
                    new_label_scope TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_by_source TEXT NOT NULL DEFAULT 'legacy',
                    updated_by_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_experiment_updates_experiment
                    ON intent_experiment_updates(experiment_id, id DESC);

                CREATE TABLE IF NOT EXISTS intent_experiment_assignments (
                    experiment_id TEXT NOT NULL
                        REFERENCES intent_experiments(id) ON DELETE RESTRICT,
                    username TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    assignment_kind TEXT NOT NULL
                        CHECK(assignment_kind IN ('base', 'cross', 'full')),
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, username, case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_experiment_assignments_user
                    ON intent_experiment_assignments(username, experiment_id, ordinal);

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
                """
            )
            revision_tables = (
                "issues",
                "annotations",
                "review_attachments",
                "model_runs",
                "model_predictions",
                "inference_jobs",
                "batch_prediction_jobs",
                "batch_prediction_items",
                "review_tag_catalog",
                "missing_evidence_catalog",
                "access_users",
                "mention_users",
                "review_comments",
                "comment_attachments",
                "issue_work_splits",
                "issue_work_assignments",
                "review_work_assignments",
                "review_work_assignment_changes",
                "review_worksets",
                "review_workset_items",
                "label_cases",
                "label_revisions",
                "label_attachments",
                "label_resolutions",
                "label_migration_map",
                "label_gt_export_batches",
                "label_gt_export_items",
                "label_gt_export_source_snapshots",
                "label_comment_links",
                "labeling_scope_state",
                "gt_snapshots",
                "gt_snapshot_items",
                "gt_snapshot_active",
                "label_result_snapshots",
                "label_result_snapshot_items",
                "label_result_snapshot_sources",
                "intent_label_revisions",
                "intent_frame_overrides",
                "intent_label_heads",
                "intent_user_label_heads",
                "intent_label_deletions",
                "intent_case_comments",
                "intent_experiments",
                "intent_experiment_updates",
                "intent_experiment_assignments",
                "trail_issue_exclusion_history",
            )
            for table in revision_tables:
                for action in ("insert", "update", "delete"):
                    conn.execute(
                        f"""
                        CREATE TRIGGER IF NOT EXISTS
                            trg_{table}_{action}_change_revision
                        AFTER {action.upper()} ON {table}
                        BEGIN
                            UPDATE dashboard_change_revision
                            SET revision = revision + 1,
                                updated_at = strftime(
                                    '%Y-%m-%dT%H:%M:%fZ', 'now'
                                )
                            WHERE id = 1;
                        END
                        """
                    )
            # Existing MVP databases are upgraded in place.  Each addition is
            # nullable/defaulted, so prior annotations and model runs survive.
            self._ensure_column(conn, "issues", "baseline_scope", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "annotations", "review_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "annotations", "model_run_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "annotations", "work_split_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "issue_work_splits", "mode", "TEXT NOT NULL DEFAULT 'single'")
            self._ensure_column(conn, "issue_work_splits", "reviewers_per_issue", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "issue_work_splits", "model_run_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "issue_work_splits", "assignment_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "issue_work_splits", "overlap_ratio", "REAL NOT NULL DEFAULT 1.0")
            self._ensure_column(conn, "issue_work_splits", "task_kind", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "issue_work_splits", "workset_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "issue_work_splits", "selection_source_run_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn, "intent_experiments", "overlap_reviewers",
                "INTEGER NOT NULL DEFAULT 2",
            )
            self._ensure_column(conn, "annotations", "is_excluded", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "annotations", "missing_evidence_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_id", "TEXT")
            self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_ids_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "label_gt_export_batches", "source_gt_snapshot_sha256", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "label_gt_export_batches", "reconcile_status", "TEXT NOT NULL DEFAULT 'not_checked'")
            self._ensure_column(conn, "label_gt_export_batches", "reconcile_error", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "label_gt_export_batches", "reconciled_at", "TEXT")
            self._ensure_column(conn, "label_gt_export_batches", "reconciled_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "label_gt_export_batches", "not_applied_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "label_gt_export_batches", "changed_again_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "label_gt_export_items", "reconcile_status", "TEXT NOT NULL DEFAULT 'not_checked'")
            self._ensure_column(conn, "label_gt_export_items", "reconciled_snapshot_id", "TEXT")
            self._ensure_column(conn, "label_gt_export_items", "reconciled_at", "TEXT")
            self._ensure_column(conn, "label_result_snapshot_sources", "task_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "label_result_snapshot_sources", "source_key", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "UPDATE label_result_snapshot_sources SET source_key = 'legacy:' || id WHERE source_key = ''"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_label_result_snapshot_sources_key "
                "ON label_result_snapshot_sources(snapshot_id, source_key)"
            )
            self._ensure_column(conn, "annotations", "author_source", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "annotations", "author_verified", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "annotations", "mentions_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "mention_users", "display_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "intent_case_comments", "mentions_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "access_users", "intent_permission", "TEXT NOT NULL DEFAULT 'manage'")
            self._ensure_column(
                conn, "intent_case_comments", "reply_to_id",
                "INTEGER REFERENCES intent_case_comments(id)",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_annotations_issue_run_id "
                "ON annotations(issue_id, model_run_id, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_annotations_work_split_author "
                "ON annotations(issue_id, model_run_id, work_split_id, author, id DESC)"
            )
            if self.backend == "sqlite":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO review_work_assignments (
                        split_id, issue_id, assignee, assignment_kind, ordinal,
                        assigned_by, assigned_at
                    )
                    SELECT split_id, issue_id, assignee, 'base', 1,
                           assigned_by, assigned_at
                    FROM issue_work_assignments
                    WHERE split_id <> '' AND assignee <> ''
                    """
                )
            self._ensure_column(conn, "missing_evidence_catalog", "active", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "review_tag_catalog", "hint", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "review_tag_catalog", "section", "TEXT NOT NULL DEFAULT 'scene'")
            self._ensure_column(conn, "review_tag_catalog", "group_key", "TEXT NOT NULL DEFAULT 'environment'")
            self._ensure_column(conn, "review_tag_catalog", "active", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "model_runs", "kind", "TEXT NOT NULL DEFAULT 'upload'")
            self._ensure_column(conn, "model_runs", "is_default", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "model_runs", "created_by", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn, "model_runs", "created_by_source", "TEXT NOT NULL DEFAULT 'legacy'"
            )
            self._ensure_column(
                conn, "model_runs", "created_by_verified", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn, "inference_jobs", "requested_by_source", "TEXT NOT NULL DEFAULT 'legacy'"
            )
            self._ensure_column(
                conn, "inference_jobs", "requested_by_verified", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn,
                "intent_experiments",
                "label_scope",
                "TEXT NOT NULL DEFAULT 'all'",
            )
            self._ensure_column(
                conn,
                "intent_experiments",
                "annotation_status_filter",
                "TEXT NOT NULL DEFAULT 'all'",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "provider_id",
                "TEXT NOT NULL DEFAULT 'kylin'",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "requested_model_id",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "resolved_model_id",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "model_source",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "catalog_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "model_validation_status",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "prompt_template",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "prompt_template_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "prompt_mode",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "input_profile",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "batch_prediction_jobs",
                "input_config_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_baseline ON issues(baseline_scope)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_annotations_author ON annotations(author)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_runs_created_by ON model_runs(created_by)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_model "
                "ON batch_prediction_jobs(requested_model_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt "
                "ON batch_prediction_jobs(prompt_version, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_prompt_revision "
                "ON batch_prediction_jobs("
                "prompt_version, prompt_mode, prompt_template_sha256, created_at DESC"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_prediction_jobs_input "
                "ON batch_prediction_jobs(input_profile, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_requested_by ON inference_jobs(requested_by)"
            )
            conn.execute(
                """
                UPDATE inference_jobs
                SET status = 'failed',
                    finished_at = ?,
                    error_text = '服务重启前任务未完成；请重新提交。'
                WHERE status IN ('queued', 'running')
                """,
                (utc_now(),),
            )
            interrupted_at = utc_now()
            # A hard restart can happen after an immutable manual-batch Run
            # commits but before the parent job/item linkage is finalized.
            # Recover that linkage first, then let the normal interruption
            # handling fail only items which truly have no persisted result.
            manual_runs = conn.execute(
                """
                SELECT id, metadata_json
                FROM model_runs
                WHERE kind = 'manual_batch'
                ORDER BY created_at DESC
                """
            ).fetchall()
            for run_row in manual_runs:
                metadata = _json_load(run_row["metadata_json"], {})
                if not isinstance(metadata, dict):
                    continue
                batch_job_id = str(
                    metadata.get("batch_prediction_job_id") or ""
                ).strip()
                if not batch_job_id:
                    continue
                experiment = metadata.get("experiment")
                if not isinstance(experiment, dict):
                    experiment = {}
                conn.execute(
                    """
                    UPDATE batch_prediction_jobs
                    SET model_run_id = COALESCE(model_run_id, ?),
                        model_name = CASE WHEN TRIM(model_name) = '' THEN ? ELSE model_name END,
                        prompt_version = CASE WHEN TRIM(prompt_version) = '' THEN ? ELSE prompt_version END,
                        experiment_source = CASE
                            WHEN TRIM(experiment_source) = '' THEN ?
                            ELSE experiment_source
                        END,
                        config_sha256 = CASE
                            WHEN TRIM(config_sha256) = '' THEN ?
                            ELSE config_sha256
                        END
                    WHERE id = ?
                    """,
                    (
                        str(run_row["id"]),
                        str(experiment.get("model_name") or ""),
                        str(experiment.get("prompt_version") or ""),
                        str(experiment.get("experiment_source") or ""),
                        str(metadata.get("config_sha256") or ""),
                        batch_job_id,
                    ),
                )
            recoverable = conn.execute(
                """
                SELECT id, model_run_id
                FROM batch_prediction_jobs
                WHERE status = 'running'
                  AND model_run_id IS NOT NULL
                  AND TRIM(model_run_id) != ''
                """
            ).fetchall()
            for job_row in recoverable:
                predictions = conn.execute(
                    """
                    SELECT issue_id, raw_json
                    FROM model_predictions
                    WHERE model_run_id = ?
                    """,
                    (job_row["model_run_id"],),
                ).fetchall()
                for prediction in predictions:
                    raw = _json_load(prediction["raw_json"], {})
                    if not isinstance(raw, dict):
                        raw = {}
                    conn.execute(
                        """
                        UPDATE batch_prediction_items
                        SET status = 'succeeded',
                            result_json = ?,
                            error_text = '',
                            started_at = COALESCE(started_at, ?),
                            finished_at = COALESCE(finished_at, ?)
                        WHERE job_id = ?
                          AND issue_id = ?
                          AND status = 'running'
                        """,
                        (
                            _json(raw),
                            interrupted_at,
                            interrupted_at,
                            job_row["id"],
                            prediction["issue_id"],
                        ),
                    )
            # Preserve already-completed item results, but make every unfinished
            # item belonging to an interrupted job terminal.  Updating the
            # children first lets the parent query still identify queued/running
            # jobs without introducing a temporary migration marker.
            conn.execute(
                """
                UPDATE batch_prediction_items
                SET status = 'failed',
                    finished_at = ?,
                    error_text = CASE
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 Batch 预测未完成。'
                        ELSE error_text
                    END
                WHERE status = 'running'
                  AND EXISTS (
                      SELECT 1
                      FROM batch_prediction_jobs bpj
                      WHERE bpj.id = batch_prediction_items.job_id
                        AND bpj.status = 'running'
                  )
                """,
                (interrupted_at,),
            )
            conn.execute(
                """
                UPDATE batch_prediction_jobs
                SET status = CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                        )
                         AND NOT EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status != 'succeeded'
                        ) THEN 'succeeded'
                        WHEN EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status = 'succeeded'
                        ) THEN 'partial'
                        ELSE 'failed'
                    END,
                    completed_count = (
                        SELECT COUNT(*)
                        FROM batch_prediction_items bpi
                        WHERE bpi.job_id = batch_prediction_jobs.id
                          AND bpi.status IN ('succeeded', 'failed')
                    ),
                    success_count = (
                        SELECT COUNT(*)
                        FROM batch_prediction_items bpi
                        WHERE bpi.job_id = batch_prediction_jobs.id
                          AND bpi.status = 'succeeded'
                    ),
                    failed_count = (
                        SELECT COUNT(*)
                        FROM batch_prediction_items bpi
                        WHERE bpi.job_id = batch_prediction_jobs.id
                          AND bpi.status = 'failed'
                    ),
                    finished_at = ?,
                    error_text = CASE
                        WHEN NOT EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status != 'succeeded'
                        ) THEN error_text
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 Batch 预测未完成；请重新创建任务。'
                        ELSE error_text
                    END
                WHERE status = 'running'
                """,
                (interrupted_at,),
            )
            conn.execute(
                """
                UPDATE batch_prediction_jobs
                SET publish_status = CASE
                        WHEN TRIM(autotriage_batch_id) != '' THEN 'partial'
                        ELSE 'failed'
                    END,
                    error_text = CASE
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 AutoTriage 推送未完成；为避免重复建批，不会自动重试。'
                        ELSE error_text
                    END
                WHERE publish_status = 'running'
                """
            )

    @staticmethod
    def _ensure_column(conn: Any, table: str, column: str, declaration: str) -> None:
        if isinstance(conn, _PostgresConnection):
            return
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def seed_examples(self, examples: Iterable[dict[str, Any]]) -> None:
        self.upsert_issues(examples, source="user_examples", replace_gt=False)


    @staticmethod
    def _scope_in_sql(scopes: list[str], column: str = "i.baseline_scope") -> tuple[str, list]:
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        placeholders = ", ".join("?" for _ in scopes)
        return f"{column} IN ({placeholders})", list(scopes)


    def review_reason_rows(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        annotation_author: str = "",
        review_status: str = "",
        gt_label: str = "",
        annotation_label: str = "",
        model_label: str = "",
        missing_evidence: str | list[str] | tuple[str, ...] = "",
        tag: str = "",
        tag_filters: tuple[str, ...] = (),
        scene_tags: tuple[str, ...] = (),
        trigger_tags: tuple[str, ...] = (),
        egress_tags: tuple[str, ...] = (),
        issue_ids: Sequence[str] | None = None,
        search: str = "",
        search_aliases: tuple[str, ...] = (),
        is_excluded: bool | None = None,
        include_unbound_fallback: bool = False,
        include_bound_history_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        """Return one latest-review row per baseline issue for analysis.

        When ``model_run_id`` is selected, the latest Review is normally
        resolved within that immutable Run.  Read-only Review/analysis surfaces
        can opt into historical fallbacks: the selected Run's own Review still
        wins, then a pre-Run shared Review, then the newest Review from another
        Run. Safety-sensitive callers (for example Trail candidate generation)
        keep the strict default. ``comparison_status`` can narrow the slice to
        MATCH, MISMATCH, or NONE (no canonical prediction).
        ``failure_only`` remains a compatibility alias for MISMATCH.
        """

        def _multi_values(*raw: Any) -> tuple[str, ...]:
            values: list[str] = []
            for item in raw:
                if item is None:
                    continue
                if isinstance(item, (list, tuple, set)):
                    for nested in item:
                        text = str(nested or "").strip()
                        if text:
                            values.append(text)
                    continue
                text = str(item or "").strip()
                if not text:
                    continue
                if "," in text:
                    values.extend(
                        part.strip() for part in text.split(",") if part.strip()
                    )
                else:
                    values.append(text)
            return tuple(dict.fromkeys(values))

        if failure_only:
            comparison_status = "mismatch"
        comparison_statuses = tuple(
            value
            for value in _multi_values(comparison_status)
            if value in {"match", "mismatch", "no_gt", "none"}
        )
        if comparison_statuses and set(comparison_statuses) == {
            "match",
            "mismatch",
            "no_gt",
            "none",
        }:
            comparison_statuses = ()
        if comparison_statuses and not model_run_id:
            raise ValueError("comparison_status requires model_run_id")

        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        scope_clause, scope_params = self._scope_in_sql(scopes)
        where = [scope_clause, "ann.id IS NOT NULL"]
        # A selected Run joins its prediction namespace explicitly.  With no
        # Run selected, the Trail update page is an all-Run aggregate: use the
        # latest annotation's own Run so its model label/reason are retained.
        annotation_params = self._latest_annotation_join_params(
            model_run_id,
            include_unbound_fallback=include_unbound_fallback,
            include_bound_history_fallback=include_bound_history_fallback,
        )
        if model_run_id:
            prediction_join = "mp.model_run_id = ?"
            # The correlated latest-annotation join appears before the
            # prediction join in SQL, so bind the annotation selector first.
            params: list[Any] = [*annotation_params, model_run_id, *scope_params]
        else:
            prediction_join = "mp.model_run_id = NULLIF(ann.model_run_id, '')"
            params = list(scope_params)
        if is_excluded is not None:
            where.append("ann.is_excluded = ?")
            # SQLite stores this legacy flag as INTEGER, while PostgreSQL uses
            # the native BOOLEAN type.  Bind a Python bool so psycopg emits a
            # boolean literal and SQLite continues to coerce it to 0/1.
            params.append(bool(is_excluded))
        if comparison_statuses:
            status_clauses: list[str] = []
            for status in comparison_statuses:
                if status == "no_gt":
                    clause, clause_params = model_prediction_no_gt_sql()
                elif status == "none":
                    clause, clause_params = model_prediction_none_sql()
                    clause = f"(i.gt_label IN (?, ?, ?) AND {clause})"
                    clause_params = (*LABELS, *clause_params)
                elif status == "match":
                    clause, clause_params = model_prediction_match_sql()
                    clause = f"(i.gt_label IN (?, ?, ?) AND {clause})"
                    clause_params = (*LABELS, *clause_params)
                else:
                    clause, clause_params = model_prediction_mismatch_sql()
                    clause = f"(i.gt_label IN (?, ?, ?) AND {clause})"
                    clause_params = (*LABELS, *clause_params)
                status_clauses.append(clause)
                params.extend(clause_params)
            where.append(f"({' OR '.join(status_clauses)})")
        authors = _multi_values(annotation_author)
        if authors:
            where.append(
                f"ann.author IN ({', '.join('?' for _ in authors)})"
            )
            params.extend(authors)
        statuses = tuple(
            value for value in _multi_values(review_status) if value in REVIEW_STATUSES
        )
        if statuses:
            where.append(
                f"ann.review_status IN ({', '.join('?' for _ in statuses)})"
            )
            params.extend(statuses)
        gt_labels = tuple(value for value in _multi_values(gt_label) if value in LABELS)
        if gt_labels:
            where.append(f"i.gt_label IN ({', '.join('?' for _ in gt_labels)})")
            params.extend(gt_labels)
        annotation_labels = tuple(
            value for value in _multi_values(annotation_label) if value in LABELS
        )
        if annotation_labels:
            where.append(
                f"ann.label IN ({', '.join('?' for _ in annotation_labels)})"
            )
            params.extend(annotation_labels)
        model_labels = tuple(
            value for value in _multi_values(model_label) if value in MODEL_LABELS
        )
        if model_labels:
            where.append(
                f"mp.model_label IN ({', '.join('?' for _ in model_labels)})"
            )
            params.extend(model_labels)
        selected_issue_ids = tuple(
            dict.fromkeys(
                str(issue_id or "").strip()
                for issue_id in (issue_ids or ())
                if str(issue_id or "").strip()
            )
        )
        evidence_keys = _multi_values(missing_evidence)
        if evidence_keys:
            evidence_clauses = [
                "ann.missing_evidence_json LIKE ?" for _ in evidence_keys
            ]
            where.append(f"({' OR '.join(evidence_clauses)})")
            params.extend(f'%"{key}"%' for key in evidence_keys)
        def _or_tag_group(keys: tuple[str, ...]) -> None:
            if not keys:
                return
            clauses = ["ann.tags_json LIKE ?" for _ in keys]
            where.append(f"({' OR '.join(clauses)})")
            params.extend(f'%"{key}"%' for key in keys)

        # Section-scoped multi-selects: OR within group, AND across groups.
        _or_tag_group(_multi_values(*scene_tags))
        _or_tag_group(_multi_values(*trigger_tags))
        _or_tag_group(_multi_values(*egress_tags))
        # Legacy flat tag filters remain AND-all for older callers.
        for requested_tag in _multi_values(tag, *tag_filters):
            where.append("ann.tags_json LIKE ?")
            params.append(f'%"{requested_tag}"%')
        if search.strip():
            terms = tuple(
                dict.fromkeys(
                    text.strip()
                    for text in (search, *search_aliases)
                    if text.strip()
                )
            )
            search_clauses: list[str] = []
            for text in terms:
                term = f"%{text}%"
                search_clauses.append(
                    "(ann.note LIKE ? OR ann.author LIKE ? OR ann.label LIKE ? "
                    "OR ann.review_status LIKE ? OR ann.tags_json LIKE ? "
                    "OR ann.missing_evidence_json LIKE ?)"
                )
                params.extend([term, term, term, term, term, term])
            where.append(f"({' OR '.join(search_clauses)})")

        select_sql = """
            SELECT i.issue_id, i.title, i.scenario, i.summary, i.gt_label,
                   i.baseline_scope,
                   ann.id AS annotation_id,
                   ann.label AS annotation_label,
                   ann.review_status AS annotation_review_status,
                   ann.is_excluded AS annotation_is_excluded,
                   ann.tags_json AS annotation_tags_json,
                   ann.missing_evidence_json AS annotation_missing_evidence_json,
                   ann.note AS annotation_note,
                   ann.author AS annotation_author,
                   ann.author_source AS annotation_author_source,
                   ann.author_verified AS annotation_author_verified,
                   ann.created_at AS annotation_created_at,
                   ann.model_run_id AS annotation_model_run_id,
                   mp.model_run_id, mp.model_label, mp.model_reason,
                   mp.model_confidence
        """
        from_sql = f"""
            FROM issues i
            {self._latest_annotation_join(
                model_run_id,
                include_unbound_fallback=include_unbound_fallback,
                include_bound_history_fallback=include_bound_history_fallback,
            )}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id AND {prediction_join}
        """
        with self.connect() as conn:
            rows: list[Any] = []
            if selected_issue_ids:
                for offset in range(0, len(selected_issue_ids), 400):
                    batch = selected_issue_ids[offset : offset + 400]
                    clauses = [
                        *where,
                        f"i.issue_id IN ({', '.join('?' for _ in batch)})",
                    ]
                    query = (
                        f"{select_sql} {from_sql} WHERE {' AND '.join(clauses)} "
                        "ORDER BY i.issue_id ASC"
                    )
                    rows.extend(
                        conn.execute(query, (*params, *batch)).fetchall()
                    )
            else:
                query = (
                    f"{select_sql} {from_sql} WHERE {' AND '.join(where)} "
                    "ORDER BY i.issue_id ASC"
                )
                rows = conn.execute(query, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            model_label = str(row["model_label"] or "")
            current_gt = str(row["gt_label"] or "")
            comparable = current_gt in LABELS and model_label in MODEL_LABELS
            results.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "title": str(row["title"] or ""),
                    "scenario": str(row["scenario"] or ""),
                    "summary": str(row["summary"] or ""),
                    "gt_label": current_gt,
                    "annotation": {
                        "id": int(row["annotation_id"]),
                        "model_run_id": str(row["annotation_model_run_id"] or ""),
                        "label": str(row["annotation_label"] or ""),
                        "review_status": str(
                            row["annotation_review_status"] or "pending"
                        ),
                        "is_excluded": bool(row["annotation_is_excluded"]),
                        "tags": _json_load(row["annotation_tags_json"], []),
                        "missing_evidence": _json_load(
                            row["annotation_missing_evidence_json"], []
                        ),
                        "note": str(row["annotation_note"] or ""),
                        "author": str(row["annotation_author"] or ""),
                        "author_source": str(
                            row["annotation_author_source"] or "legacy"
                        ),
                        "author_verified": bool(
                            row["annotation_author_verified"]
                        ),
                        "created_at": str(row["annotation_created_at"] or ""),
                    },
                    "prediction": {
                        "model_run_id": str(row["model_run_id"] or ""),
                        "label": model_label,
                        "reason": str(row["model_reason"] or ""),
                        "confidence": row["model_confidence"],
                        "comparable": comparable,
                        "mismatch": bool(
                            comparable
                            and not model_label_matches_gt(model_label, current_gt)
                        ),
                    },
                }
            )
        results.sort(key=lambda item: str(item.get("issue_id") or ""))
        return results

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        metadata = redact_sensitive_fields(_json_load(row["metadata_json"], {}))
        experiment = metadata.get("experiment") if isinstance(metadata, dict) else {}
        if not isinstance(experiment, dict):
            experiment = {}
        declared_author = str(
            experiment.get("author")
            or (metadata.get("author") if isinstance(metadata, dict) else "")
            or ""
        ).strip()
        return {
            "id": row["id"],
            "name": row["name"],
            "source_name": row["source_name"],
            "source_sha256": row["source_sha256"],
            "schema_version": row["schema_version"],
            "kind": row["kind"] if "kind" in row.keys() else "upload",
            "is_default": bool(row["is_default"]) if "is_default" in row.keys() else False,
            "created_by": row["created_by"] if "created_by" in row.keys() else "",
            "created_by_source": (
                row["created_by_source"] if "created_by_source" in row.keys() else "legacy"
            ),
            "created_by_verified": bool(row["created_by_verified"])
            if "created_by_verified" in row.keys()
            else False,
            "declared_author": declared_author,
            "metadata": metadata,
            "created_at": row["created_at"],
        }

    @staticmethod
    def _attachment_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "annotation_id": int(row["annotation_id"]),
            "original_name": row["original_name"],
            "stored_name": row["stored_name"],
            "media_type": row["media_type"],
            "size_bytes": int(row["size_bytes"]),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "sha256": row["sha256"],
            "created_at": row["created_at"],
        }
