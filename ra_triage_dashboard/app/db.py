from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .sanitization import redact_sensitive_fields


LABELS = ("误触发", "正确触发", "无需协助")
COMPARISON_STATUSES = ("all", "mismatch", "match", "none")
REVIEW_STATUSES = ("pending", "reviewed", "needs_gt_review")
BATCH_JOB_STATUSES = ("queued", "running", "succeeded", "partial", "failed")
BATCH_PUBLISH_STATUSES = (
    "not_requested",
    "running",
    "succeeded",
    "partial",
    "failed",
)
ACCESS_ROLES = ("writer", "admin")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _postgres_sql(sql: str) -> str:
    """Translate the deliberately small SQLite query subset to psycopg."""

    output: list[str] = []
    quoted = False
    index = 0
    while index < len(sql):
        character = sql[index]
        if character == "'":
            output.append(character)
            if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                output.append("'")
                index += 2
                continue
            quoted = not quoted
        elif character == "?" and not quoted:
            output.append("%s")
        else:
            output.append(character)
        index += 1
    translated = "".join(output).replace(" COLLATE BINARY", "")
    translated = re.sub(
        r"\b(ann\.(?:tags_json|missing_evidence_json))\s+LIKE\s+",
        r"\1::text ILIKE ",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(r"\s+LIKE\s+", " ILIKE ", translated, flags=re.IGNORECASE)
    return translated


class _CompatRow:
    """Expose psycopg mapping rows through sqlite3.Row's tiny used surface."""

    def __init__(self, values: dict[str, Any]):
        self._values = values
        self._keys = tuple(values.keys())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            key = self._keys[key]
        value = self._values[key]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def keys(self) -> tuple[str, ...]:
        return self._keys


class _PostgresCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    @property
    def lastrowid(self) -> None:
        return None

    def fetchone(self) -> _CompatRow | None:
        row = self._cursor.fetchone()
        return _CompatRow(row) if row is not None else None

    def fetchall(self) -> list[_CompatRow]:
        return [_CompatRow(row) for row in self._cursor.fetchall()]


class _NoopCursor:
    rowcount = 0
    lastrowid = None

    @staticmethod
    def fetchone() -> None:
        return None

    @staticmethod
    def fetchall() -> list[Any]:
        return []


class _PostgresConnection:
    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _PostgresCursor | _NoopCursor:
        if sql.lstrip().upper().startswith("CREATE TRIGGER IF NOT EXISTS"):
            return _NoopCursor()
        return _PostgresCursor(
            self._connection.execute(_postgres_sql(sql), tuple(params))
        )

    def executemany(
        self, sql: str, params: Iterable[Iterable[Any]]
    ) -> _PostgresCursor:
        cursor = self._connection.cursor()
        cursor.executemany(
            _postgres_sql(sql), [tuple(values) for values in params]
        )
        return _PostgresCursor(
            cursor
        )

    @staticmethod
    def executescript(_: str) -> None:
        # PostgreSQL schema and revision triggers are applied by migrations.
        return None


class Database:
    """SQLite/PostgreSQL storage with versioned review history.

    ``baseline_scope`` is intentionally stored on the issue rather than
    deleting old imports.  This lets the active 0508/1071 evaluation set stay
    stable while uploaded model runs and prior reviews remain recoverable.
    """

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

    def bootstrap_access_users(
        self, *, writers: Iterable[str], administrators: Iterable[str]
    ) -> None:
        """Seed the persistent ACL once so UI removals survive restarts."""

        writer_names = {
            str(value).strip().lower() for value in writers if str(value).strip()
        }
        admin_names = {
            str(value).strip().lower()
            for value in administrators
            if str(value).strip()
        }
        names = sorted(writer_names | admin_names)
        if not names:
            return
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS count FROM access_users"
            ).fetchone()
            if existing and int(existing["count"] or 0) > 0:
                return
            conn.executemany(
                """
                INSERT INTO access_users (
                    username, role, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        name,
                        "admin" if name in admin_names else "writer",
                        "bootstrap",
                        now,
                        now,
                    )
                    for name in names
                ],
            )

    def access_role(self, username: str) -> str:
        normalized = str(username or "").strip().lower()
        if not normalized:
            return ""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
        return str(row["role"] or "") if row else ""

    def list_access_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT username, role, created_by, created_at, updated_at
                FROM access_users
                ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                         username ASC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def set_access_user(
        self, *, username: str, role: str, actor: str
    ) -> dict[str, Any]:
        normalized = str(username or "").strip().lower()
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in ACCESS_ROLES:
            raise ValueError("权限角色必须是 writer 或 admin。")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
            if current and current["role"] == "admin" and normalized_role != "admin":
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM access_users WHERE role = 'admin'"
                ).fetchone()
                if count and int(count["count"] or 0) <= 1:
                    raise ValueError("不能降级唯一的管理员。")
            if current:
                conn.execute(
                    "UPDATE access_users SET role = ?, updated_at = ? WHERE username = ?",
                    (normalized_role, now, normalized),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO access_users (
                        username, role, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (normalized, normalized_role, actor, now, now),
                )
        return next(
            item for item in self.list_access_users() if item["username"] == normalized
        )

    def delete_access_user(self, username: str) -> bool:
        normalized = str(username or "").strip().lower()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
            if not current:
                return False
            if current["role"] == "admin":
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM access_users WHERE role = 'admin'"
                ).fetchone()
                if count and int(count["count"] or 0) <= 1:
                    raise ValueError("不能移除唯一的管理员。")
            cursor = conn.execute(
                "DELETE FROM access_users WHERE username = ?", (normalized,)
            )
            return cursor.rowcount > 0

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
                    label TEXT,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    missing_evidence_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    author_source TEXT NOT NULL DEFAULT 'legacy',
                    author_verified INTEGER NOT NULL DEFAULT 0,
                    supersedes_id INTEGER REFERENCES annotations(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotations_issue_id
                    ON annotations(issue_id, id DESC);

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

                CREATE TABLE IF NOT EXISTS review_tag_catalog (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS access_users (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('writer', 'admin')),
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
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
                "access_users",
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
            self._ensure_column(conn, "annotations", "is_excluded", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "annotations", "missing_evidence_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "annotations", "author_source", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "annotations", "author_verified", "INTEGER NOT NULL DEFAULT 0")
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

    def replace_baseline_scope(
        self,
        *,
        scope: str,
        rows: Iterable[dict[str, Any]],
        source: str,
    ) -> dict[str, int]:
        materialized = list(rows)
        with self._write_lock, self.connect() as conn:
            conn.execute("UPDATE issues SET baseline_scope = '' WHERE baseline_scope = ?", (scope,))
        return self.upsert_issues(
            materialized,
            source=source,
            replace_gt=True,
            baseline_scope=scope,
        )

    def baseline_issue_ids(self, scope: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT issue_id FROM issues WHERE baseline_scope = ? ORDER BY issue_id", (scope,)
            ).fetchall()
        return [str(row["issue_id"]) for row in rows]

    def upsert_issues(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        source: str,
        replace_gt: bool,
        baseline_scope: str = "",
    ) -> dict[str, int]:
        inserted = updated = skipped = 0
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            for row in rows:
                issue_id = str(row.get("issue_id") or "").strip()
                if not issue_id:
                    skipped += 1
                    continue
                gt_label = str(row.get("gt_label") or "").strip()
                if gt_label not in LABELS:
                    gt_label = ""
                existing = conn.execute(
                    "SELECT issue_id, gt_label FROM issues WHERE issue_id = ?", (issue_id,)
                ).fetchone()
                extra = row.get("extra") or {}
                values = {
                    "trip_id": str(row.get("trip_id") or "").strip(),
                    "title": str(row.get("title") or "").strip(),
                    "scenario": str(row.get("scenario") or "").strip(),
                    "summary": str(row.get("summary") or "").strip(),
                    "review_note": str(row.get("review_note") or "").strip(),
                    "trail_url": str(row.get("trail_url") or "").strip(),
                    "gt_source": str(row.get("gt_source") or source).strip(),
                    "extra_json": _json(extra),
                }
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO issues (
                            issue_id, trip_id, title, scenario, summary, review_note,
                            trail_url, gt_label, gt_source, source, baseline_scope,
                            extra_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            issue_id,
                            values["trip_id"],
                            values["title"],
                            values["scenario"],
                            values["summary"],
                            values["review_note"],
                            values["trail_url"],
                            gt_label or None,
                            values["gt_source"],
                            source,
                            baseline_scope,
                            values["extra_json"],
                            now,
                            now,
                        ),
                    )
                    inserted += 1
                    continue

                # Model-result imports often contain only issue_id.  Never
                # blank richer fields from a prior baseline or manual review.
                updates = {key: value for key, value in values.items() if value not in ("", "{}")}
                if gt_label and (replace_gt or not existing["gt_label"]):
                    updates["gt_label"] = gt_label
                    updates["gt_source"] = values["gt_source"]
                if baseline_scope:
                    updates["baseline_scope"] = baseline_scope
                if not updates:
                    skipped += 1
                    continue
                assignments = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE issues SET {assignments}, source = ?, updated_at = ? WHERE issue_id = ?",
                    (*updates.values(), source, now, issue_id),
                )
                updated += 1
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def import_model_run(
        self,
        *,
        name: str,
        source_name: str,
        source_sha256: str,
        metadata: dict[str, Any],
        rows: list[dict[str, Any]],
        kind: str = "upload",
        make_default: bool = False,
        created_by: str = "",
        created_by_source: str = "legacy",
        created_by_verified: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        metadata = redact_sensitive_fields(metadata)
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM model_runs WHERE source_sha256 = ?", (source_sha256,)
            ).fetchone()
            if existing:
                if make_default:
                    conn.execute("UPDATE model_runs SET is_default = FALSE")
                    conn.execute("UPDATE model_runs SET is_default = TRUE WHERE id = ?", (existing["id"],))
                    existing = conn.execute(
                        "SELECT * FROM model_runs WHERE id = ?", (existing["id"],)
                    ).fetchone()
                return self._run_dict(existing), True

            run_id = str(uuid.uuid4())
            if make_default:
                conn.execute("UPDATE model_runs SET is_default = FALSE")
            conn.execute(
                """
                INSERT INTO model_runs (
                    id, name, source_name, source_sha256, schema_version,
                    kind, is_default, created_by, created_by_source,
                    created_by_verified, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    name,
                    source_name,
                    source_sha256,
                    str(metadata.get("schema_version") or "v1"),
                    kind,
                    bool(make_default),
                    created_by.strip(),
                    created_by_source.strip() or "legacy",
                    bool(created_by_verified),
                    _json(metadata),
                    now,
                ),
            )
            for row in rows:
                issue_id = str(row["issue_id"])
                issue = conn.execute("SELECT issue_id FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
                if issue is None:
                    conn.execute(
                        """
                        INSERT INTO issues (issue_id, trip_id, source, created_at, updated_at)
                        VALUES (?, ?, 'model_import', ?, ?)
                        """,
                        (issue_id, str(row.get("trip_id") or ""), now, now),
                    )
                conn.execute(
                    """
                    INSERT INTO model_predictions (
                        model_run_id, issue_id, trip_id, model_label, model_reason,
                        model_confidence, model_extra_json, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        issue_id,
                        str(row.get("trip_id") or ""),
                        str(row.get("model_label") or ""),
                        str(row.get("model_reason") or ""),
                        row.get("model_confidence"),
                        _json(redact_sensitive_fields(row.get("model_extra") or {})),
                        _json(redact_sensitive_fields(row.get("raw") or {})),
                        now,
                    ),
                )
            result = conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_dict(result), False

    def default_model_run_id(self) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM model_runs WHERE is_default = TRUE ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return str(row["id"]) if row else ""

    def get_model_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._run_dict(row) if row else None

    def model_run_source_rows(self, run_id: str) -> list[dict[str, Any]]:
        """Return redacted normalized/raw rows for legacy source reconstruction."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT issue_id, trip_id, model_label, model_reason,
                       model_confidence, model_extra_json, raw_json
                FROM model_predictions
                WHERE model_run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            raw = _json_load(row["raw_json"], {})
            if not isinstance(raw, dict):
                raw = {}
            item = dict(redact_sensitive_fields(raw))
            item.setdefault("issue_id", row["issue_id"])
            item.setdefault("trip_id", row["trip_id"])
            item.setdefault("model_label", row["model_label"])
            item.setdefault("model_reason", row["model_reason"])
            if row["model_confidence"] is not None:
                item.setdefault("model_confidence", row["model_confidence"])
            extra = _json_load(row["model_extra_json"], {})
            if isinstance(extra, dict):
                for key, value in redact_sensitive_fields(extra).items():
                    item.setdefault(key, value)
            result.append(item)
        return result

    def delete_model_run(self, run_id: str) -> dict[str, Any] | None:
        """Delete one non-default local Run and its prediction rows.

        Model Runs are immutable while retained, but explicit user deletion is
        useful for removing an obsolete upload.  SQLite foreign-key cascades
        remove predictions and detach any Batch job's optional run pointer;
        issues, GT and append-only human annotations are not deleted.
        """

        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            if bool(row["is_default"]):
                raise ValueError("当前团队默认 Run 不能删除，请先切换默认 Run。")
            conn.execute("DELETE FROM model_runs WHERE id = ?", (run_id,))
        return self._run_dict(row)

    def set_default_model_run(self, run_id: str) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE model_runs SET is_default = FALSE")
            conn.execute("UPDATE model_runs SET is_default = TRUE WHERE id = ?", (run_id,))
            updated = conn.execute(
                "SELECT * FROM model_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._run_dict(updated)

    def list_model_runs(self, baseline_scope: str = "") -> list[dict[str, Any]]:
        labels = tuple(LABELS)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT mr.*,
                       COUNT(mp.id) AS prediction_count,
                       SUM(CASE WHEN i.baseline_scope = ? THEN 1 ELSE 0 END) AS baseline_prediction_count,
                       SUM(CASE
                             WHEN i.baseline_scope = ?
                              AND i.gt_label IN (?, ?, ?)
                              AND mp.model_label IN (?, ?, ?)
                              AND mp.model_label != i.gt_label
                             THEN 1 ELSE 0 END) AS failure_count
                FROM model_runs mr
                LEFT JOIN model_predictions mp ON mp.model_run_id = mr.id
                LEFT JOIN issues i ON i.issue_id = mp.issue_id
                GROUP BY mr.id
                ORDER BY mr.is_default DESC, mr.created_at DESC
                """,
                (baseline_scope, baseline_scope, *labels, *labels),
            ).fetchall()
        return [
            self._run_dict(row)
            | {
                "prediction_count": int(row["prediction_count"] or 0),
                "baseline_prediction_count": int(row["baseline_prediction_count"] or 0),
                "failure_count": int(row["failure_count"] or 0),
            }
            for row in rows
        ]

    def list_reviewers(self, baseline_scope: str = "") -> list[dict[str, Any]]:
        params: list[Any] = []
        scope_filter = ""
        if baseline_scope:
            scope_filter = "AND i.baseline_scope = ?"
            params.append(baseline_scope)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ann.author,
                       SUM(CASE WHEN ann.author_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN ann.author_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS review_count
                FROM issues i
                {self._latest_annotation_join()}
                WHERE ann.id IS NOT NULL
                  AND TRIM(ann.author) != ''
                  {scope_filter}
                GROUP BY ann.author
                ORDER BY review_count DESC, ann.author ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "name": str(row["author"]),
                "verified": bool(row["verified_count"])
                and not bool(row["unverified_count"]),
                "verified_count": int(row["verified_count"] or 0),
                "unverified_count": int(row["unverified_count"] or 0),
                "review_count": int(row["review_count"] or 0),
            }
            for row in rows
        ]

    @staticmethod
    def _latest_annotation_join() -> str:
        return """
            LEFT JOIN annotations ann
              ON ann.id = (
                  SELECT a.id FROM annotations a
                  WHERE a.issue_id = i.issue_id
                  ORDER BY a.id DESC LIMIT 1
              )
        """

    def list_cases(
        self,
        *,
        baseline_scope: str = "",
        search: str = "",
        gt_label: str = "",
        annotation_label: str = "",
        annotation_author: str = "",
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        missing_evidence: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = min(max(1, page_size), 2000)
        comparison_status = str(comparison_status or "all").strip().lower()
        if failure_only:
            comparison_status = "mismatch"
        if comparison_status not in COMPARISON_STATUSES:
            raise ValueError("unsupported comparison_status")
        if comparison_status != "all" and not model_run_id:
            raise ValueError("comparison_status requires model_run_id")
        where: list[str] = []
        params: list[Any] = []
        if baseline_scope:
            where.append("i.baseline_scope = ?")
            params.append(baseline_scope)
        if search.strip():
            term = f"%{search.strip()}%"
            where.append("(i.issue_id LIKE ? OR i.title LIKE ? OR i.scenario LIKE ? OR i.summary LIKE ?)")
            params.extend([term, term, term, term])
        if gt_label in LABELS:
            where.append("i.gt_label = ?")
            params.append(gt_label)
        if annotation_label in LABELS:
            where.append("ann.label = ?")
            params.append(annotation_label)
        if annotation_author.strip():
            where.append("ann.author = ?")
            params.append(annotation_author.strip())
        if missing_evidence.strip():
            # Values are serialized as a JSON array; matching the quoted token
            # avoids treating a prefix as a different evidence item.
            where.append("ann.missing_evidence_json LIKE ?")
            params.append(f'%"{missing_evidence.strip()}"%')
        if comparison_status != "all":
            where.append("i.gt_label IN (?, ?, ?)")
            params.extend(LABELS)
            if comparison_status == "none":
                where.append("(mp.model_label IS NULL OR mp.model_label NOT IN (?, ?, ?))")
                params.extend(LABELS)
            else:
                where.append("mp.model_label IN (?, ?, ?)")
                params.extend(LABELS)
                operator = "=" if comparison_status == "match" else "!="
                where.append(f"mp.model_label {operator} i.gt_label")
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        common = f"""
            FROM issues i
            {self._latest_annotation_join()}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id
             AND mp.model_run_id = ?
        """
        model_args = [model_run_id]
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(DISTINCT i.issue_id) {common} {condition}", (*model_args, *params)
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT i.*, ann.label AS annotation_label, ann.review_status AS annotation_review_status,
                       ann.is_excluded AS annotation_is_excluded,
                       ann.tags_json AS annotation_tags_json,
                       ann.missing_evidence_json AS annotation_missing_evidence_json,
                       ann.note AS annotation_note, ann.author AS annotation_author,
                       ann.author_source AS annotation_author_source,
                       ann.author_verified AS annotation_author_verified,
                       ann.created_at AS annotation_created_at,
                       mp.model_label, mp.model_reason, mp.model_confidence, mp.model_run_id
                {common}
                {condition}
                ORDER BY i.issue_id ASC
                LIMIT ? OFFSET ?
                """,
                (*model_args, *params, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "items": [self._case_summary(row) for row in rows],
            "total": int(total),
            "page": page,
            "page_size": page_size,
        }

    def get_case(self, issue_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            issue = conn.execute("SELECT * FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
            if issue is None:
                return None
            annotations = conn.execute(
                "SELECT * FROM annotations WHERE issue_id = ? ORDER BY id DESC", (issue_id,)
            ).fetchall()
            predictions = conn.execute(
                """
                SELECT mp.*, mr.name AS run_name, mr.created_at AS run_created_at,
                       mr.kind AS run_kind, mr.is_default AS run_is_default,
                       mr.created_by AS run_created_by,
                       mr.created_by_source AS run_created_by_source,
                       mr.created_by_verified AS run_created_by_verified
                FROM model_predictions mp
                JOIN model_runs mr ON mr.id = mp.model_run_id
                WHERE mp.issue_id = ?
                ORDER BY mr.is_default DESC, mr.created_at DESC
                """,
                (issue_id,),
            ).fetchall()
            jobs = conn.execute(
                "SELECT * FROM inference_jobs WHERE issue_id = ? ORDER BY created_at DESC LIMIT 10", (issue_id,)
            ).fetchall()
            batch_jobs = conn.execute(
                """
                SELECT bpj.*, bpi.status AS item_status,
                       bpi.job_id AS item_job_id,
                       bpi.issue_id AS item_issue_id,
                       bpi.ordinal AS item_ordinal,
                       bpi.result_json AS item_result_json,
                       bpi.error_text AS item_error_text,
                       bpi.autotriage_record_id AS item_autotriage_record_id,
                       bpi.started_at AS item_started_at,
                       bpi.finished_at AS item_finished_at
                FROM batch_prediction_items bpi
                JOIN batch_prediction_jobs bpj ON bpj.id = bpi.job_id
                WHERE bpi.issue_id = ?
                ORDER BY bpj.created_at DESC
                LIMIT 10
                """,
                (issue_id,),
            ).fetchall()
            attachments = conn.execute(
                """
                SELECT ra.*
                FROM review_attachments ra
                JOIN annotations ann ON ann.id = ra.annotation_id
                WHERE ann.issue_id = ?
                ORDER BY ra.created_at ASC
                """,
                (issue_id,),
            ).fetchall()
        data = self._issue_dict(issue)
        attachments_by_annotation: dict[int, list[dict[str, Any]]] = {}
        for row in attachments:
            attachments_by_annotation.setdefault(int(row["annotation_id"]), []).append(
                self._attachment_dict(row)
            )
        annotation_items = [self._annotation_dict(row) for row in annotations]
        for annotation in annotation_items:
            annotation["attachments"] = attachments_by_annotation.get(int(annotation["id"]), [])
        data["annotations"] = annotation_items
        data["predictions"] = [self._prediction_dict(row) for row in predictions]
        data["jobs"] = [self._job_dict(row) for row in jobs]
        data["batch_jobs"] = [self._case_batch_job_dict(row) for row in batch_jobs]
        return data

    def create_annotation(
        self,
        *,
        issue_id: str,
        label: str,
        review_status: str,
        tags: list[str],
        missing_evidence: list[str],
        note: str,
        author: str,
        author_source: str = "legacy",
        author_verified: bool = False,
        attachments: list[dict[str, Any]] | None = None,
        is_excluded: bool = False,
    ) -> dict[str, Any]:
        if label and label not in LABELS:
            raise ValueError(f"不支持的标注标签: {label}")
        if review_status not in REVIEW_STATUSES:
            raise ValueError(f"不支持的 review 状态: {review_status}")
        if not author.strip():
            raise ValueError("复核人不能为空。")
        tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        missing_evidence = sorted(
            {str(item).strip() for item in missing_evidence if str(item).strip()}
        )
        attachments = attachments or []
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            previous = conn.execute(
                "SELECT id FROM annotations WHERE issue_id = ? ORDER BY id DESC LIMIT 1", (issue_id,)
            ).fetchone()
            annotation_sql = """
                INSERT INTO annotations (
                    issue_id, label, review_status, is_excluded, tags_json, missing_evidence_json,
                    note, author, author_source, author_verified, supersedes_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                annotation_sql += " RETURNING id"
            cursor = conn.execute(
                annotation_sql,
                (
                    issue_id,
                    label or None,
                    review_status,
                    bool(is_excluded),
                    _json(tags),
                    _json(missing_evidence),
                    note.strip(),
                    author.strip(),
                    author_source.strip() or "legacy",
                    bool(author_verified),
                    previous["id"] if previous else None,
                    now,
                ),
            )
            annotation_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            conn.execute("UPDATE issues SET updated_at = ? WHERE issue_id = ?", (now, issue_id))
            for attachment in attachments:
                conn.execute(
                    """
                    INSERT INTO review_attachments (
                        id, annotation_id, original_name, stored_name,
                        media_type, size_bytes, width, height, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(attachment["id"]),
                        annotation_id,
                        str(attachment.get("original_name") or ""),
                        str(attachment["stored_name"]),
                        str(attachment["media_type"]),
                        int(attachment["size_bytes"]),
                        int(attachment["width"]),
                        int(attachment["height"]),
                        str(attachment["sha256"]),
                        now,
                    ),
                )
            row = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,)).fetchone()
        result = self._annotation_dict(row)
        result["attachments"] = [
            {
                **attachment,
                "annotation_id": annotation_id,
                "created_at": now,
            }
            for attachment in attachments
        ]
        return result

    def delete_annotation(
        self,
        *,
        issue_id: str,
        annotation_id: int,
    ) -> dict[str, Any] | None:
        """Delete one review version and reconnect its superseding chain."""
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotations WHERE id = ? AND issue_id = ?",
                (annotation_id, issue_id),
            ).fetchone()
            if row is None:
                return None
            attachments = conn.execute(
                "SELECT * FROM review_attachments WHERE annotation_id = ? ORDER BY created_at ASC",
                (annotation_id,),
            ).fetchall()
            conn.execute(
                "UPDATE annotations SET supersedes_id = ? WHERE supersedes_id = ?",
                (row["supersedes_id"], annotation_id),
            )
            conn.execute(
                "DELETE FROM annotations WHERE id = ? AND issue_id = ?",
                (annotation_id, issue_id),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE issue_id = ?",
                (now, issue_id),
            )
        result = self._annotation_dict(row)
        result["attachments"] = [self._attachment_dict(item) for item in attachments]
        return result

    def get_review_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
        return self._attachment_dict(row) if row else None

    def review_attachment_storage_bytes(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM review_attachments"
            ).fetchone()
        return int(row["total"] or 0)

    def review_reason_rows(
        self,
        *,
        baseline_scope: str,
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        annotation_author: str = "",
        review_status: str = "",
        gt_label: str = "",
        annotation_label: str = "",
        missing_evidence: str = "",
        tag: str = "",
        search: str = "",
        search_aliases: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """Return one latest-review row per baseline issue for analysis.

        Human Review is dataset-level rather than run-bound. ``model_run_id``
        only adds the selected immutable prediction snapshot. ``comparison_status``
        can narrow the slice to MATCH, MISMATCH, or NONE (no canonical
        prediction). ``failure_only`` remains a compatibility alias for
        MISMATCH.
        """

        comparison_status = str(comparison_status or "all").strip().lower()
        if failure_only:
            comparison_status = "mismatch"
        if comparison_status not in {"all", "mismatch", "match", "none"}:
            raise ValueError("unsupported comparison_status")
        if comparison_status != "all" and not model_run_id:
            raise ValueError("comparison_status requires model_run_id")

        where = ["i.baseline_scope = ?", "ann.id IS NOT NULL"]
        params: list[Any] = [model_run_id, baseline_scope]
        if comparison_status != "all":
            where.append("i.gt_label IN (?, ?, ?)")
            params.extend(LABELS)
            if comparison_status == "none":
                where.append(
                    "(mp.model_label IS NULL OR mp.model_label NOT IN (?, ?, ?))"
                )
                params.extend(LABELS)
            else:
                where.append("mp.model_label IN (?, ?, ?)")
                params.extend(LABELS)
                operator = "=" if comparison_status == "match" else "!="
                where.append(f"mp.model_label {operator} i.gt_label")
        if annotation_author.strip():
            where.append("ann.author = ?")
            params.append(annotation_author.strip())
        if review_status in REVIEW_STATUSES:
            where.append("ann.review_status = ?")
            params.append(review_status)
        if gt_label in LABELS:
            where.append("i.gt_label = ?")
            params.append(gt_label)
        if annotation_label in LABELS:
            where.append("ann.label = ?")
            params.append(annotation_label)
        if missing_evidence.strip():
            where.append("ann.missing_evidence_json LIKE ?")
            params.append(f'%"{missing_evidence.strip()}"%')
        if tag.strip():
            where.append("ann.tags_json LIKE ?")
            params.append(f'%"{tag.strip()}"%')
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

        query = f"""
            SELECT i.issue_id, i.title, i.scenario, i.summary, i.gt_label,
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
                   mp.model_run_id, mp.model_label, mp.model_reason,
                   mp.model_confidence
            FROM issues i
            {self._latest_annotation_join()}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
            WHERE {' AND '.join(where)}
            ORDER BY ann.created_at DESC, i.issue_id ASC
        """
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            model_label = str(row["model_label"] or "")
            current_gt = str(row["gt_label"] or "")
            comparable = current_gt in LABELS and model_label in LABELS
            results.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "title": str(row["title"] or ""),
                    "scenario": str(row["scenario"] or ""),
                    "summary": str(row["summary"] or ""),
                    "gt_label": current_gt,
                    "annotation": {
                        "id": int(row["annotation_id"]),
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
                            comparable and model_label != current_gt
                        ),
                    },
                }
            )
        return results

    def review_clusters(
        self,
        *,
        baseline_scope: str,
        model_run_id: str = "",
        failure_only: bool = True,
        annotation_author: str = "",
    ) -> list[dict[str, Any]]:
        where = ["i.baseline_scope = ?", "ann.id IS NOT NULL"]
        params: list[Any] = [model_run_id, baseline_scope]
        if failure_only and model_run_id:
            where.extend(
                [
                    "i.gt_label IN (?, ?, ?)",
                    "mp.model_label IN (?, ?, ?)",
                    "mp.model_label != i.gt_label",
                ]
            )
            params.extend((*LABELS, *LABELS))
        if annotation_author.strip():
            where.append("ann.author = ?")
            params.append(annotation_author.strip())
        query = f"""
            SELECT ann.missing_evidence_json
            FROM issues i
            {self._latest_annotation_join()}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
            WHERE {' AND '.join(where)}
        """
        counts: dict[str, int] = {}
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        for row in rows:
            values = _json_load(row["missing_evidence_json"], [])
            if not isinstance(values, list):
                continue
            for value in values:
                key = str(value).strip()
                if key:
                    counts[key] = counts.get(key, 0) + 1
        return [{"key": key, "count": count} for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

    def create_job(
        self,
        *,
        issue_id: str,
        requested_by: str,
        model_name: str,
        base_url: str,
        config: dict[str, Any],
        requested_by_source: str = "legacy",
        requested_by_verified: bool = False,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO inference_jobs (
                    id, issue_id, status, requested_by, requested_by_source,
                    requested_by_verified, model_name, base_url, config_json, created_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    issue_id,
                    requested_by.strip(),
                    requested_by_source.strip() or "legacy",
                    bool(requested_by_verified),
                    model_name.strip(),
                    base_url.strip(),
                    _json(config),
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row)

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_text: str = "",
        log_path: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        values: dict[str, Any] = {"status": status}
        if status == "running":
            values["started_at"] = now
        if status in {"succeeded", "failed"}:
            values["finished_at"] = now
        if result is not None:
            values["result_json"] = _json(result)
        if error_text:
            values["error_text"] = error_text
        if log_path:
            values["log_path"] = log_path
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE inference_jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_inference_jobs(
        self,
        *,
        requested_by: str = "",
        status: str = "",
        page_size: int = 100,
    ) -> dict[str, Any]:
        page_size = min(max(1, page_size), 500)
        where: list[str] = []
        params: list[Any] = []
        if requested_by.strip():
            where.append("requested_by = ?")
            params.append(requested_by.strip())
        if status in {"queued", "running", "succeeded", "failed"}:
            where.append("status = ?")
            params.append(status)
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM inference_jobs {condition}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM inference_jobs
                {condition}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, page_size),
            ).fetchall()
            requester_rows = conn.execute(
                """
                SELECT requested_by,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS job_count
                FROM inference_jobs
                WHERE TRIM(requested_by) != ''
                GROUP BY requested_by
                ORDER BY job_count DESC, requested_by ASC
                """
            ).fetchall()
        return {
            "items": [self._job_dict(row) for row in rows],
            "total": int(total),
            "requesters": [
                {
                    "name": str(row["requested_by"]),
                    "verified": bool(row["verified_count"])
                    and not bool(row["unverified_count"]),
                    "verified_count": int(row["verified_count"] or 0),
                    "unverified_count": int(row["unverified_count"] or 0),
                    "job_count": int(row["job_count"] or 0),
                }
                for row in requester_rows
            ],
        }

    def create_batch_prediction_job(
        self,
        *,
        name: str,
        issue_ids: list[str],
        requested_by: str,
        requested_by_source: str = "legacy",
        requested_by_verified: bool = False,
        provider_id: str = "kylin",
        requested_model_id: str,
        resolved_model_id: str,
        model_source: str,
        catalog_sha256: str,
        model_validation_status: str = "legacy",
        prompt_version: str = "",
        prompt_template: str = "",
        prompt_template_sha256: str = "",
        prompt_mode: str = "",
        input_profile: str = "",
        input_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_issue_ids = [str(issue_id).strip() for issue_id in issue_ids]
        if not normalized_issue_ids or any(not issue_id for issue_id in normalized_issue_ids):
            raise ValueError("Batch 任务至少需要一个有效 issue_id。")
        if len(set(normalized_issue_ids)) != len(normalized_issue_ids):
            raise ValueError("Batch 任务中的 issue_id 不能重复。")

        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            known_issue_ids: set[str] = set()
            for offset in range(0, len(normalized_issue_ids), 500):
                chunk = normalized_issue_ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                known_issue_ids.update(
                    str(row["issue_id"])
                    for row in conn.execute(
                        f"SELECT issue_id FROM issues WHERE issue_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            missing_issue_ids = [
                issue_id
                for issue_id in normalized_issue_ids
                if issue_id not in known_issue_ids
            ]
            if missing_issue_ids:
                preview = ", ".join(missing_issue_ids[:5])
                suffix = (
                    f" 等 {len(missing_issue_ids)} 个"
                    if len(missing_issue_ids) > 5
                    else ""
                )
                raise ValueError(f"Batch 任务包含未导入的 Issue：{preview}{suffix}")

            conn.execute(
                """
                INSERT INTO batch_prediction_jobs (
                    id, name, status, requested_by, requested_by_source,
                    requested_by_verified, total_count, provider_id, requested_model_id,
                    resolved_model_id, model_source, catalog_sha256,
                    model_validation_status, model_name, prompt_version,
                    prompt_template, prompt_template_sha256, prompt_mode,
                    input_profile, input_config_json, created_at
                ) VALUES (
                    ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    job_id,
                    name.strip() or f"Batch {now[:16].replace('T', ' ')} UTC",
                    requested_by.strip(),
                    requested_by_source.strip() or "legacy",
                    bool(requested_by_verified),
                    len(normalized_issue_ids),
                    str(provider_id or "kylin").strip().lower() or "kylin",
                    requested_model_id.strip(),
                    resolved_model_id.strip(),
                    model_source.strip() or "ra_model_gateway",
                    catalog_sha256.strip(),
                    model_validation_status.strip(),
                    resolved_model_id.strip(),
                    prompt_version.strip(),
                    prompt_template,
                    prompt_template_sha256.strip(),
                    prompt_mode.strip(),
                    input_profile.strip(),
                    _json(input_config),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO batch_prediction_items (
                    job_id, issue_id, ordinal, status
                ) VALUES (?, ?, ?, 'queued')
                """,
                [
                    (job_id, issue_id, ordinal)
                    for ordinal, issue_id in enumerate(normalized_issue_ids)
                ],
            )
        result = self.get_batch_prediction_job(job_id)
        if result is None:
            raise RuntimeError("Batch 任务创建后无法读取。")
        return result

    def update_batch_prediction_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        completed_count: int | None = None,
        success_count: int | None = None,
        failed_count: int | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        experiment_source: str | None = None,
        config_sha256: str | None = None,
        model_run_id: str | None = None,
        publish_status: str | None = None,
        autotriage_batch_id: str | None = None,
        autotriage_writer: str | None = None,
        summary: dict[str, Any] | None = None,
        error_text: str | None = None,
        log_path: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {}
        if status is not None:
            if status not in BATCH_JOB_STATUSES:
                raise ValueError(f"Batch 任务状态非法：{status}")
            values["status"] = status
            if status == "running":
                values["started_at"] = utc_now()
            if status in {"succeeded", "partial", "failed"}:
                values["finished_at"] = utc_now()
        if publish_status is not None and publish_status not in BATCH_PUBLISH_STATUSES:
            raise ValueError(f"Batch 推送状态非法：{publish_status}")
        for count_name, count_value in (
            ("completed_count", completed_count),
            ("success_count", success_count),
            ("failed_count", failed_count),
        ):
            if count_value is not None and int(count_value) < 0:
                raise ValueError(f"{count_name} 不能为负数。")
        for key, value in (
            (
                "completed_count",
                int(completed_count) if completed_count is not None else None,
            ),
            ("success_count", int(success_count) if success_count is not None else None),
            ("failed_count", int(failed_count) if failed_count is not None else None),
            ("model_name", model_name),
            ("prompt_version", prompt_version),
            ("experiment_source", experiment_source),
            ("config_sha256", config_sha256),
            ("model_run_id", model_run_id),
            ("publish_status", publish_status),
            ("autotriage_batch_id", autotriage_batch_id),
            ("autotriage_writer", autotriage_writer),
            ("error_text", error_text),
            ("log_path", log_path),
        ):
            if value is not None:
                values[key] = value
        if summary is not None:
            values["summary_json"] = _json(summary)
        if not values:
            return self.get_batch_prediction_job(job_id)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                f"UPDATE batch_prediction_jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )
        return self.get_batch_prediction_job(job_id)

    @staticmethod
    def _refresh_batch_prediction_counts(
        conn: sqlite3.Connection,
        job_id: str,
    ) -> None:
        conn.execute(
            """
            UPDATE batch_prediction_jobs
            SET completed_count = (
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
                )
            WHERE id = ?
            """,
            (job_id,),
        )

    def update_batch_prediction_items(
        self,
        job_id: str,
        results: list[dict[str, Any]],
    ) -> int:
        issue_ids = [str(result.get("issue_id") or "").strip() for result in results]
        if any(not issue_id for issue_id in issue_ids):
            raise ValueError("Batch 结果缺少 issue_id。")
        if len(set(issue_ids)) != len(issue_ids):
            raise ValueError("同一次 Batch 结果更新不能包含重复 issue_id。")

        finished_at = utc_now()
        updated = 0
        with self._write_lock, self.connect() as conn:
            for result in results:
                issue_id = str(result.get("issue_id") or "").strip()
                success = bool(result.get("success"))
                cursor = conn.execute(
                    """
                    UPDATE batch_prediction_items
                    SET status = ?,
                        result_json = ?,
                        error_text = ?,
                        started_at = COALESCE(started_at, ?),
                        finished_at = ?
                    WHERE job_id = ? AND issue_id = ?
                    """,
                    (
                        "succeeded" if success else "failed",
                        _json(result),
                        str(result.get("error") or ""),
                        finished_at,
                        finished_at,
                        job_id,
                        issue_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Batch 任务 {job_id} 不包含 issue_id={issue_id}。"
                    )
                updated += 1
            self._refresh_batch_prediction_counts(conn, job_id)
        return updated

    def update_batch_prediction_records(
        self,
        job_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        updated = 0
        with self._write_lock, self.connect() as conn:
            for record in records:
                issue_id = str(record.get("issue_id") or "").strip()
                record_id = str(
                    record.get("record_id") or record.get("id") or ""
                ).strip()
                if not issue_id or not record_id:
                    continue
                cursor = conn.execute(
                    """
                    UPDATE batch_prediction_items
                    SET autotriage_record_id = ?
                    WHERE job_id = ? AND issue_id = ?
                    """,
                    (record_id, job_id, issue_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Batch 任务 {job_id} 不包含 issue_id={issue_id}。"
                    )
                updated += 1
        return updated

    def next_queued_batch_prediction_job(self) -> dict[str, Any] | None:
        """Return the oldest durable prediction job waiting for the runner."""

        queue_order = "queue_order" if self.backend == "postgresql" else "rowid"
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT id
                FROM batch_prediction_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC, {queue_order} ASC
                LIMIT 1
                """
            ).fetchone()
        return self.get_batch_prediction_job(str(row["id"])) if row else None

    def get_batch_prediction_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM batch_prediction_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            items = conn.execute(
                """
                SELECT * FROM batch_prediction_items
                WHERE job_id = ?
                ORDER BY ordinal ASC
                """,
                (job_id,),
            ).fetchall()
        result = self._batch_job_dict(row)
        result["items"] = [self._batch_item_dict(item) for item in items]
        return result

    def list_batch_prediction_jobs(
        self,
        *,
        requested_by: str = "",
        status: str = "",
        model_id: str = "",
        prompt_version: str = "",
        prompt_mode: str = "",
        prompt_sha256: str = "",
        input_profile: str = "",
        page_size: int = 100,
    ) -> dict[str, Any]:
        page_size = min(max(1, page_size), 200)
        where: list[str] = []
        params: list[Any] = []
        if requested_by.strip():
            where.append("requested_by = ?")
            params.append(requested_by.strip())
        if status in BATCH_JOB_STATUSES:
            where.append("status = ?")
            params.append(status)
        if model_id.strip():
            where.append("(requested_model_id = ? OR resolved_model_id = ?)")
            params.extend((model_id.strip(), model_id.strip()))
        if prompt_version.strip():
            where.append("prompt_version = ?")
            params.append(prompt_version.strip())
        if prompt_mode.strip():
            where.append("prompt_mode = ?")
            params.append(prompt_mode.strip())
        if prompt_sha256.strip():
            where.append("prompt_template_sha256 = ?")
            params.append(prompt_sha256.strip())
        if input_profile.strip():
            where.append("input_profile = ?")
            params.append(input_profile.strip())
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM batch_prediction_jobs {condition}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM batch_prediction_jobs
                {condition}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, page_size),
            ).fetchall()
            requester_rows = conn.execute(
                """
                SELECT requested_by,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(requested_by) != ''
                GROUP BY requested_by
                ORDER BY job_count DESC, requested_by ASC
                """
            ).fetchall()
            model_rows = conn.execute(
                """
                SELECT model_id, COUNT(*) AS job_count
                FROM (
                    SELECT id, TRIM(requested_model_id) AS model_id
                    FROM batch_prediction_jobs
                    WHERE TRIM(requested_model_id) != ''
                    UNION
                    SELECT id, TRIM(resolved_model_id) AS model_id
                    FROM batch_prediction_jobs
                    WHERE TRIM(resolved_model_id) != ''
                ) AS model_catalog
                GROUP BY model_id
                ORDER BY job_count DESC, model_id ASC
                """
            ).fetchall()
            prompt_rows = conn.execute(
                """
                SELECT prompt_version, prompt_mode, prompt_template_sha256,
                       COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(prompt_version) != ''
                GROUP BY prompt_version, prompt_mode, prompt_template_sha256
                ORDER BY job_count DESC, prompt_version ASC,
                         prompt_mode ASC, prompt_template_sha256 ASC
                """
            ).fetchall()
            input_rows = conn.execute(
                """
                SELECT input_profile, COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(input_profile) != ''
                GROUP BY input_profile
                ORDER BY job_count DESC, input_profile ASC
                """
            ).fetchall()
        return {
            # List responses intentionally contain summaries only.  Item
            # results can be large and belong to the per-job detail endpoint.
            "items": [self._batch_job_dict(row) for row in rows],
            "total": int(total),
            "requesters": [
                {
                    "name": str(row["requested_by"]),
                    "verified": bool(row["verified_count"])
                    and not bool(row["unverified_count"]),
                    "verified_count": int(row["verified_count"] or 0),
                    "unverified_count": int(row["unverified_count"] or 0),
                    "job_count": int(row["job_count"] or 0),
                }
                for row in requester_rows
            ],
            "facets": {
                "models": [
                    {
                        "id": str(row["model_id"]),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in model_rows
                ],
                "prompts": [
                    {
                        "version": str(row["prompt_version"]),
                        "mode": str(row["prompt_mode"] or ""),
                        "sha256": str(row["prompt_template_sha256"] or ""),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in prompt_rows
                ],
                "input_profiles": [
                    {
                        "id": str(row["input_profile"]),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in input_rows
                ],
            },
        }

    def overview(self, *, baseline_scope: str, model_run_id: str = "") -> dict[str, Any]:
        base_where = "WHERE i.baseline_scope = ?"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM issues i {base_where}", (baseline_scope,)).fetchone()[0]
            labelled = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM issues i
                {self._latest_annotation_join()}
                {base_where} AND ann.id IS NOT NULL
                """,
                (baseline_scope,),
            ).fetchone()[0]
            predictions = failures = reviewed_failures = 0
            if model_run_id:
                common = f"""
                    FROM issues i
                    {self._latest_annotation_join()}
                    LEFT JOIN model_predictions mp
                      ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
                    WHERE i.baseline_scope = ?
                """
                predictions = conn.execute(
                    f"SELECT COUNT(mp.id) {common}", (model_run_id, baseline_scope)
                ).fetchone()[0]
                failure_condition = " AND i.gt_label IN (?, ?, ?) AND mp.model_label IN (?, ?, ?) AND mp.model_label != i.gt_label"
                failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition}",
                    (model_run_id, baseline_scope, *LABELS, *LABELS),
                ).fetchone()[0]
                reviewed_failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition} AND ann.id IS NOT NULL",
                    (model_run_id, baseline_scope, *LABELS, *LABELS),
                ).fetchone()[0]
            running = conn.execute(
                "SELECT COUNT(*) FROM inference_jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            running += conn.execute(
                "SELECT COUNT(*) FROM batch_prediction_jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
        return {
            "issues": int(total),
            "labelled": int(labelled),
            "unlabelled": max(int(total) - int(labelled), 0),
            "predictions": int(predictions),
            "model_failures": int(failures),
            "reviewed_failures": int(reviewed_failures),
            "running_jobs": int(running),
        }

    @staticmethod
    def _issue_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "issue_id": row["issue_id"],
            "trip_id": row["trip_id"],
            "title": row["title"],
            "scenario": row["scenario"],
            "summary": row["summary"],
            "review_note": row["review_note"],
            "trail_url": row["trail_url"],
            "gt_label": row["gt_label"] or "",
            "gt_source": row["gt_source"],
            "source": row["source"],
            "baseline_scope": row["baseline_scope"] if "baseline_scope" in row.keys() else "",
            "extra": _json_load(row["extra_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _case_summary(cls, row: sqlite3.Row) -> dict[str, Any]:
        data = cls._issue_dict(row)
        model_label = row["model_label"] or ""
        comparable = bool(data["gt_label"] in LABELS and model_label in LABELS)
        data.update(
            {
                "annotation": {
                    "label": row["annotation_label"] or "",
                    "review_status": row["annotation_review_status"] or "pending",
                    "is_excluded": bool(row["annotation_is_excluded"]),
                    "tags": _json_load(row["annotation_tags_json"], []),
                    "missing_evidence": _json_load(row["annotation_missing_evidence_json"], []),
                    "note": row["annotation_note"] or "",
                    "author": row["annotation_author"] or "",
                    "author_source": row["annotation_author_source"] or "legacy",
                    "author_verified": bool(row["annotation_author_verified"]),
                    "created_at": row["annotation_created_at"] or "",
                },
                "prediction": {
                    "model_run_id": row["model_run_id"] or "",
                    "label": model_label,
                    "reason": row["model_reason"] or "",
                    "confidence": row["model_confidence"],
                    "comparable": comparable,
                    "mismatch": bool(comparable and model_label != data["gt_label"]),
                },
            }
        )
        return data

    @staticmethod
    def _annotation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "issue_id": row["issue_id"],
            "label": row["label"] or "",
            "review_status": row["review_status"] if "review_status" in row.keys() else "pending",
            "is_excluded": bool(row["is_excluded"]) if "is_excluded" in row.keys() else False,
            "tags": _json_load(row["tags_json"], []),
            "missing_evidence": _json_load(
                row["missing_evidence_json"] if "missing_evidence_json" in row.keys() else "[]", []
            ),
            "note": row["note"],
            "author": row["author"],
            "author_source": (
                row["author_source"] if "author_source" in row.keys() else "legacy"
            ),
            "author_verified": bool(row["author_verified"])
            if "author_verified" in row.keys()
            else False,
            "supersedes_id": row["supersedes_id"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _prediction_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "model_run_id": row["model_run_id"],
            "run_name": row["run_name"] if "run_name" in row.keys() else "",
            "run_created_at": row["run_created_at"] if "run_created_at" in row.keys() else "",
            "run_kind": row["run_kind"] if "run_kind" in row.keys() else "",
            "run_is_default": bool(row["run_is_default"]) if "run_is_default" in row.keys() else False,
            "run_created_by": (
                row["run_created_by"] if "run_created_by" in row.keys() else ""
            ),
            "run_created_by_source": (
                row["run_created_by_source"]
                if "run_created_by_source" in row.keys()
                else "legacy"
            ),
            "run_created_by_verified": bool(row["run_created_by_verified"])
            if "run_created_by_verified" in row.keys()
            else False,
            "issue_id": row["issue_id"],
            "trip_id": row["trip_id"],
            "model_label": row["model_label"],
            "model_reason": row["model_reason"],
            "model_confidence": row["model_confidence"],
            "model_extra": redact_sensitive_fields(
                _json_load(row["model_extra_json"], {})
            ),
            "created_at": row["created_at"],
        }

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
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "issue_id": row["issue_id"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_by_source": (
                row["requested_by_source"]
                if "requested_by_source" in row.keys()
                else "legacy"
            ),
            "requested_by_verified": bool(row["requested_by_verified"])
            if "requested_by_verified" in row.keys()
            else False,
            "model_name": row["model_name"],
            "config": redact_sensitive_fields(_json_load(row["config_json"], {})),
            "result": redact_sensitive_fields(_json_load(row["result_json"], {})),
            "error_text": row["error_text"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _batch_job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_by_source": row["requested_by_source"],
            "requested_by_verified": bool(row["requested_by_verified"]),
            "total_count": int(row["total_count"] or 0),
            "completed_count": int(row["completed_count"] or 0),
            "success_count": int(row["success_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "provider_id": row["provider_id"]
            if "provider_id" in row.keys()
            else "kylin",
            "requested_model_id": row["requested_model_id"]
            if "requested_model_id" in row.keys()
            else "",
            "resolved_model_id": row["resolved_model_id"]
            if "resolved_model_id" in row.keys()
            else "",
            "model_source": row["model_source"]
            if "model_source" in row.keys()
            else "legacy_server_default",
            "catalog_sha256": row["catalog_sha256"]
            if "catalog_sha256" in row.keys()
            else "",
            "model_validation_status": row["model_validation_status"]
            if "model_validation_status" in row.keys()
            else "",
            "model_name": row["model_name"],
            "prompt_version": row["prompt_version"],
            "prompt_template": row["prompt_template"]
            if "prompt_template" in row.keys()
            else "",
            "prompt_template_sha256": row["prompt_template_sha256"]
            if "prompt_template_sha256" in row.keys()
            else "",
            "prompt_mode": row["prompt_mode"]
            if "prompt_mode" in row.keys()
            else "",
            "input_profile": row["input_profile"]
            if "input_profile" in row.keys()
            else "",
            "input_config": redact_sensitive_fields(
                _json_load(
                    row["input_config_json"]
                    if "input_config_json" in row.keys()
                    else "{}",
                    {},
                )
            ),
            "experiment_source": row["experiment_source"],
            "config_sha256": row["config_sha256"],
            "model_run_id": row["model_run_id"] or "",
            "publish_status": row["publish_status"],
            "autotriage_batch_id": row["autotriage_batch_id"],
            "autotriage_writer": row["autotriage_writer"],
            "summary": redact_sensitive_fields(_json_load(row["summary_json"], {})),
            "error_text": row["error_text"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _batch_item_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "issue_id": row["issue_id"],
            "ordinal": int(row["ordinal"]),
            "status": row["status"],
            "result": redact_sensitive_fields(_json_load(row["result_json"], {})),
            "error_text": row["error_text"],
            "autotriage_record_id": row["autotriage_record_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @classmethod
    def _case_batch_job_dict(cls, row: sqlite3.Row) -> dict[str, Any]:
        result = cls._batch_job_dict(row)
        result["item"] = {
            "job_id": row["item_job_id"],
            "issue_id": row["item_issue_id"],
            "ordinal": int(row["item_ordinal"]),
            "status": row["item_status"],
            "result": redact_sensitive_fields(
                _json_load(row["item_result_json"], {})
            ),
            "error_text": row["item_error_text"],
            "autotriage_record_id": row["item_autotriage_record_id"],
            "started_at": row["item_started_at"],
            "finished_at": row["item_finished_at"],
        }
        return result

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
