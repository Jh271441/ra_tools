from __future__ import annotations

from .initialize_schema import initialize_schema
from .initialize_change_tracking import initialize_change_tracking
from .initialize_campaign_compat import initialize_campaign_compat
from .initialize_columns import initialize_columns
from .initialize_recovery import initialize_recovery


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
        """Preserve migration, locking and transaction boundaries across phases."""
        if self.backend == "postgresql":
            self._apply_postgres_migrations()
        with self._write_lock, self.connect() as conn:
            initialize_schema(self, conn)
            initialize_change_tracking(self, conn)
            initialize_campaign_compat(self, conn)
            initialize_columns(self, conn)
            initialize_recovery(self, conn)

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
        model_review_status: str = "",
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
        if self.legacy_business_read_mode(scopes) == "canonical":
            include_unbound_fallback = False
            include_bound_history_fallback = False
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
        model_statuses = tuple(
            value
            for value in _multi_values(model_review_status)
            if value in {"pending", "in_progress", "completed", "blocked_by_label"}
        )
        if model_statuses:
            where.append(
                "(ann.review_domain = 'model_review' AND ann.model_review_status IN "
                f"({', '.join('?' for _ in model_statuses)}))"
            )
            params.extend(model_statuses)
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
                   ann.review_domain AS annotation_review_domain,
                   ann.model_review_status AS annotation_model_review_status,
                   ann.campaign_id AS annotation_campaign_id,
                   ann.reference_id AS annotation_reference_id,
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
                        "review_domain": str(
                            row["annotation_review_domain"] or "legacy"
                        ),
                        "model_review_status": str(
                            row["annotation_model_review_status"] or ""
                        ),
                        "campaign_id": str(row["annotation_campaign_id"] or ""),
                        "reference_id": str(row["annotation_reference_id"] or ""),
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
