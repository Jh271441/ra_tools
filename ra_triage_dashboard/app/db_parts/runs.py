from __future__ import annotations

import math
import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from ..sanitization import redact_sensitive_fields
from .shared import (
    LABELS,
    MODEL_LABELS,
    _json,
    _json_load,
    model_label_matches_gt,
    model_prediction_mismatch_sql,
    utc_now,
)


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
        mismatch_sql, mismatch_params = model_prediction_mismatch_sql()
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
                              AND {mismatch_sql}
                             THEN 1 ELSE 0 END) AS failure_count
                FROM model_runs mr
                LEFT JOIN model_predictions mp ON mp.model_run_id = mr.id
                LEFT JOIN issues i ON i.issue_id = mp.issue_id
                GROUP BY mr.id
                ORDER BY mr.is_default DESC, mr.created_at DESC
                """,
                (*scope_params, *scope_params, *labels, *mismatch_params),
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

    def compare_model_runs(
        self,
        *,
        baseline_run_id: str,
        candidate_run_id: str,
        baseline_scopes: Sequence[str],
        transition: str = "all",
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Compare two immutable Runs over the same baseline workset.

        P/F describes correctness against immutable GT, not a particular model
        label: P2F is a regression and F2P is an improvement. Missing or
        unsupported predictions remain visible as ``NONE`` and count as F.
        """

        baseline_run_id = str(baseline_run_id or "").strip()
        candidate_run_id = str(candidate_run_id or "").strip()
        if not baseline_run_id or not candidate_run_id:
            raise ValueError("请选择两个模型 Run。")
        if baseline_run_id == candidate_run_id:
            raise ValueError("基线 Run 与新 Run 不能相同。")
        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            raise ValueError("至少选择一个有效 GT 数据集。")
        normalized_transition = str(transition or "all").strip().upper()
        if normalized_transition not in {"ALL", "P2P", "P2F", "F2P", "F2F"}:
            raise ValueError("不支持的 Run 变化类型。")
        normalized_search = str(search or "").strip().lower()[:128]
        page_size = min(max(int(page_size), 1), 100)
        page = max(int(page), 1)

        run_ids = (baseline_run_id, candidate_run_id)
        run_placeholders = ", ".join("?" for _ in run_ids)
        scope_clause, scope_params = self._scope_in_sql(scopes, "i.baseline_scope")
        with self.connect() as conn:
            run_rows = conn.execute(
                f"SELECT * FROM model_runs WHERE id IN ({run_placeholders})",
                run_ids,
            ).fetchall()
            job_rows = conn.execute(
                f"""
                SELECT * FROM batch_prediction_jobs
                WHERE model_run_id IN ({run_placeholders})
                ORDER BY created_at DESC
                """,
                run_ids,
            ).fetchall()
            rows = conn.execute(
                f"""
                SELECT i.issue_id, i.gt_label, i.baseline_scope,
                       base.model_label AS baseline_model_label,
                       base.model_reason AS baseline_model_reason,
                       base.model_confidence AS baseline_model_confidence,
                       candidate.model_label AS candidate_model_label,
                       candidate.model_reason AS candidate_model_reason,
                       candidate.model_confidence AS candidate_model_confidence
                FROM issues i
                LEFT JOIN model_predictions base
                  ON base.issue_id = i.issue_id
                 AND base.model_run_id = ?
                LEFT JOIN model_predictions candidate
                  ON candidate.issue_id = i.issue_id
                 AND candidate.model_run_id = ?
                WHERE {scope_clause}
                  AND i.gt_label IN (?, ?, ?)
                ORDER BY i.issue_id ASC
                """,
                (
                    baseline_run_id,
                    candidate_run_id,
                    *scope_params,
                    *LABELS,
                ),
            ).fetchall()

        runs = {str(row["id"]): self._run_dict(row) for row in run_rows}
        if baseline_run_id not in runs or candidate_run_id not in runs:
            raise ValueError("模型 Run 不存在或已被删除。")
        jobs: dict[str, dict[str, Any]] = {}
        for row in job_rows:
            run_id = str(row["model_run_id"] or "")
            if run_id and run_id not in jobs:
                jobs[run_id] = self._batch_job_dict(row)

        model_columns = [*MODEL_LABELS, "NONE"]
        matrices = {
            "baseline": {
                gt_label: {column: 0 for column in model_columns}
                for gt_label in LABELS
            },
            "candidate": {
                gt_label: {column: 0 for column in model_columns}
                for gt_label in LABELS
            },
        }
        transition_counts = {key: 0 for key in ("P2P", "P2F", "F2P", "F2F")}
        comparison_rows: list[dict[str, Any]] = []
        for row in rows:
            gt_label = str(row["gt_label"] or "")
            baseline_label = str(row["baseline_model_label"] or "").strip()
            candidate_label = str(row["candidate_model_label"] or "").strip()
            baseline_bucket = (
                baseline_label if baseline_label in MODEL_LABELS else "NONE"
            )
            candidate_bucket = (
                candidate_label if candidate_label in MODEL_LABELS else "NONE"
            )
            baseline_correct = model_label_matches_gt(baseline_bucket, gt_label)
            candidate_correct = model_label_matches_gt(candidate_bucket, gt_label)
            transition_key = (
                ("P" if baseline_correct else "F")
                + "2"
                + ("P" if candidate_correct else "F")
            )
            matrices["baseline"][gt_label][baseline_bucket] += 1
            matrices["candidate"][gt_label][candidate_bucket] += 1
            transition_counts[transition_key] += 1
            comparison_rows.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "gt_label": gt_label,
                    "baseline": {
                        "model_label": baseline_bucket,
                        "model_reason": str(row["baseline_model_reason"] or ""),
                        "model_confidence": row["baseline_model_confidence"],
                        "correct": baseline_correct,
                    },
                    "candidate": {
                        "model_label": candidate_bucket,
                        "model_reason": str(row["candidate_model_reason"] or ""),
                        "model_confidence": row["candidate_model_confidence"],
                        "correct": candidate_correct,
                    },
                    "transition": transition_key,
                    "label_changed": baseline_bucket != candidate_bucket,
                }
            )

        def matrix_payload(side: str) -> dict[str, Any]:
            matrix_rows: list[dict[str, Any]] = []
            correct_count = 0
            prediction_count = 0
            for gt_label in LABELS:
                cells = matrices[side][gt_label]
                total = sum(cells.values())
                row_correct = sum(
                    count
                    for model_label, count in cells.items()
                    if model_label_matches_gt(model_label, gt_label)
                )
                correct_count += row_correct
                prediction_count += total - cells["NONE"]
                matrix_rows.append(
                    {
                        "gt_label": gt_label,
                        "cells": cells,
                        "total": total,
                        "correct_count": row_correct,
                        "accuracy": (row_correct / total) if total else 0.0,
                    }
                )
            total_count = len(comparison_rows)
            return {
                "columns": model_columns,
                "rows": matrix_rows,
                "total_count": total_count,
                "prediction_count": prediction_count,
                "missing_count": total_count - prediction_count,
                "correct_count": correct_count,
                "accuracy": (correct_count / total_count) if total_count else 0.0,
            }

        baseline_matrix = matrix_payload("baseline")
        candidate_matrix = matrix_payload("candidate")
        filtered_rows = [
            item
            for item in comparison_rows
            if (
                normalized_transition == "ALL"
                or item["transition"] == normalized_transition
            )
            and (
                not normalized_search
                or normalized_search in item["issue_id"].lower()
            )
        ]
        transition_priority = {"P2F": 0, "F2P": 1, "F2F": 2, "P2P": 3}
        filtered_rows.sort(
            key=lambda item: (
                transition_priority.get(str(item["transition"]), 9),
                str(item["issue_id"]),
            )
        )
        total_filtered = len(filtered_rows)
        page_count = max(1, math.ceil(total_filtered / page_size))
        page = min(page, page_count)
        offset = (page - 1) * page_size

        return {
            "baseline_run": self._comparison_run_snapshot(
                runs[baseline_run_id], jobs.get(baseline_run_id)
            ),
            "candidate_run": self._comparison_run_snapshot(
                runs[candidate_run_id], jobs.get(candidate_run_id)
            ),
            "baseline_scopes": scopes,
            "summary": {
                "total_count": len(comparison_rows),
                "label_changed_count": sum(
                    1 for item in comparison_rows if item["label_changed"]
                ),
                "transition_counts": transition_counts,
                "baseline": baseline_matrix,
                "candidate": candidate_matrix,
                "accuracy_delta": (
                    candidate_matrix["accuracy"] - baseline_matrix["accuracy"]
                ),
                "prediction_delta": (
                    candidate_matrix["prediction_count"]
                    - baseline_matrix["prediction_count"]
                ),
            },
            "filters": {
                "transition": normalized_transition,
                "search": normalized_search,
            },
            "items": filtered_rows[offset : offset + page_size],
            "total": total_filtered,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
        }

    @staticmethod
    def _comparison_run_snapshot(
        run: dict[str, Any], batch_job: dict[str, Any] | None
    ) -> dict[str, Any]:
        metadata = (
            run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
        )
        experiment = (
            metadata.get("experiment")
            if isinstance(metadata.get("experiment"), dict)
            else {}
        )
        job = batch_job or {}
        prompt_template = str(
            job.get("prompt_template")
            or metadata.get("prompt_template")
            or experiment.get("prompt_template")
            or ""
        )
        input_config = job.get("input_config")
        if not isinstance(input_config, dict) or not input_config:
            input_config = metadata.get("input_config")
        if not isinstance(input_config, dict) or not input_config:
            input_config = experiment.get("input_config")
        if not isinstance(input_config, dict):
            input_config = {}
        input_config = redact_sensitive_fields(input_config)
        return {
            "id": str(run.get("id") or ""),
            "name": str(run.get("name") or ""),
            "kind": str(run.get("kind") or ""),
            "source_name": str(run.get("source_name") or ""),
            "created_by": str(run.get("created_by") or ""),
            "declared_author": str(run.get("declared_author") or ""),
            "created_at": str(run.get("created_at") or ""),
            "model": {
                "name": str(
                    job.get("model_name")
                    or metadata.get("model_name")
                    or experiment.get("model_name")
                    or ""
                ),
                "requested_id": str(
                    job.get("requested_model_id")
                    or metadata.get("requested_model_id")
                    or ""
                ),
                "resolved_id": str(
                    job.get("resolved_model_id")
                    or metadata.get("resolved_model_id")
                    or ""
                ),
            },
            "prompt": {
                "available": bool(
                    prompt_template
                    or job.get("prompt_version")
                    or metadata.get("prompt_version")
                    or experiment.get("prompt_version")
                ),
                "version": str(
                    job.get("prompt_version")
                    or metadata.get("prompt_version")
                    or experiment.get("prompt_version")
                    or ""
                ),
                "mode": str(
                    job.get("prompt_mode")
                    or metadata.get("prompt_mode")
                    or experiment.get("prompt_mode")
                    or ""
                ),
                "sha256": str(
                    job.get("prompt_template_sha256")
                    or metadata.get("prompt_template_sha256")
                    or experiment.get("prompt_template_sha256")
                    or ""
                ),
                "template": prompt_template,
            },
            "input": {
                "available": bool(
                    input_config
                    or job.get("input_profile")
                    or metadata.get("input_profile")
                    or experiment.get("input_profile")
                ),
                "profile": str(
                    job.get("input_profile")
                    or metadata.get("input_profile")
                    or experiment.get("input_profile")
                    or ""
                ),
                "config": input_config,
            },
        }

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
