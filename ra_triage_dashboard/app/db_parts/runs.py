from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from ..sanitization import redact_sensitive_fields
from .shared import LABELS, _json, _json_load, utc_now


class DatabaseRunsMixin:
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

    def list_model_runs(
        self,
        baseline_scope: str | Sequence[str] = "",
        *,
        baseline_scopes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        labels = tuple(LABELS)
        scopes = self._normalize_baseline_scopes(
            baseline_scopes,
            baseline_scope=baseline_scope if isinstance(baseline_scope, str) else "",
        )
        if not scopes and isinstance(baseline_scope, (list, tuple)):
            scopes = self._normalize_baseline_scopes(baseline_scope)
        if not scopes:
            # No scope filter → treat as empty membership (counts 0 against baseline).
            scopes = ["__no_such_scope__"]
        in_clause, scope_params = self._scope_in_sql(scopes, "i.baseline_scope")
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT mr.*,
                       COUNT(mp.id) AS prediction_count,
                       SUM(CASE WHEN {in_clause} THEN 1 ELSE 0 END) AS baseline_prediction_count,
                       SUM(CASE
                             WHEN {in_clause}
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
                (*scope_params, *scope_params, *labels, *labels),
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

    def model_run_scope_coverage(self, run_id: str) -> list[dict[str, Any]]:
        """Count predictions per issue baseline_scope for one Model Run.

        Issues without a baseline_scope (e.g. imported-only orphans) are returned
        under an empty scope key so callers can see unmatched rows.
        """

        return self.model_run_scope_coverage_map([run_id]).get(
            str(run_id or "").strip(), []
        )

    def model_run_scope_coverage_map(
        self, run_ids: Sequence[str] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch variant: one GROUP BY for many runs (avoids N+1 on list endpoints)."""

        ids = [
            str(run_id or "").strip()
            for run_id in (run_ids or [])
            if str(run_id or "").strip()
        ]
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT mp.model_run_id AS model_run_id,
                       COALESCE(i.baseline_scope, '') AS baseline_scope,
                       COUNT(*) AS prediction_count
                FROM model_predictions mp
                LEFT JOIN issues i ON i.issue_id = mp.issue_id
                WHERE mp.model_run_id IN ({placeholders})
                GROUP BY mp.model_run_id, COALESCE(i.baseline_scope, '')
                ORDER BY mp.model_run_id ASC, prediction_count DESC, baseline_scope ASC
                """,
                tuple(ids),
            ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in ids}
        for row in rows:
            run_id = str(row["model_run_id"] or "").strip()
            if not run_id:
                continue
            out.setdefault(run_id, []).append(
                {
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "prediction_count": int(row["prediction_count"] or 0),
                }
            )
        return out

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
