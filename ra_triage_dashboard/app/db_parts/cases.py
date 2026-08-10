from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from .shared import COMPARISON_STATUSES, LABELS, _json, _json_load, utc_now


class DatabaseCasesMixin:
    @staticmethod
    def _normalize_baseline_scopes(
        baseline_scopes: "Sequence[str] | str | None" = None,
        *,
        baseline_scope: str = "",
    ) -> list[str]:
        """Accept legacy single scope or multi scopes; never return empty when either is set."""
        from typing import Sequence as _Seq
        values: list[str] = []
        if baseline_scopes is not None and baseline_scopes != "":
            if isinstance(baseline_scopes, str):
                parts = [part.strip() for part in baseline_scopes.split(",") if part.strip()]
                values.extend(parts)
            else:
                for item in baseline_scopes:
                    text = str(item or "").strip()
                    if text:
                        values.append(text)
        if not values and baseline_scope:
            values.append(str(baseline_scope).strip())
        # Preserve order, drop empties/dupes.
        ordered: list[str] = []
        seen: set[str] = set()
        for item in values:
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def replace_baseline_scope(
        self,
        *,
        scope: str,
        rows: Iterable[dict[str, Any]],
        source: str,
    ) -> dict[str, int]:
        materialized = self.merge_gt_sync_overlay(scope, rows)
        with self._write_lock, self.connect() as conn:
            conn.execute("UPDATE issues SET baseline_scope = '' WHERE baseline_scope = ?", (scope,))
        return self.upsert_issues(
            materialized,
            source=source,
            replace_gt=True,
            baseline_scope=scope,
        )

    def baseline_issue_ids(
        self,
        scope: str | Sequence[str] = "",
        *,
        baseline_scopes: Sequence[str] | None = None,
    ) -> list[str]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=scope if isinstance(scope, str) else "")
        if not scopes and isinstance(scope, (list, tuple)):
            scopes = self._normalize_baseline_scopes(scope)
        if not scopes:
            return []
        clause, params = self._scope_in_sql(scopes, "baseline_scope")
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT issue_id FROM issues WHERE {clause} ORDER BY issue_id",
                params,
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

    def _case_list_filters(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        search: str = "",
        gt_label: str = "",
        model_label: str = "",
        annotation_label: str = "",
        annotation_author: str = "",
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        missing_evidence: str = "",
        issue_ids: list[str] | None = None,
        work_assignee: str = "",
    ) -> tuple[str, list[Any], list[Any], str]:
        comparison_status = str(comparison_status or "all").strip().lower()
        if failure_only:
            comparison_status = "mismatch"
        if comparison_status not in COMPARISON_STATUSES:
            raise ValueError("unsupported comparison_status")
        if comparison_status != "all" and not model_run_id:
            raise ValueError("comparison_status requires model_run_id")
        where: list[str] = []
        params: list[Any] = []
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if scopes:
            clause, scope_params = self._scope_in_sql(scopes)
            where.append(clause)
            params.extend(scope_params)
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

        if search.strip():
            term = f"%{search.strip()}%"
            where.append("(i.issue_id LIKE ? OR i.title LIKE ? OR i.scenario LIKE ? OR i.summary LIKE ?)")
            params.extend([term, term, term, term])
        gt_labels = tuple(value for value in _multi_values(gt_label) if value in LABELS)
        if gt_labels:
            where.append(f"i.gt_label IN ({', '.join('?' for _ in gt_labels)})")
            params.extend(gt_labels)
        model_labels = tuple(
            value for value in _multi_values(model_label) if value in LABELS
        )
        if model_labels:
            where.append(
                f"mp.model_label IN ({', '.join('?' for _ in model_labels)})"
            )
            params.extend(model_labels)
        annotation_labels = tuple(
            value for value in _multi_values(annotation_label) if value in LABELS
        )
        if annotation_labels:
            where.append(
                f"ann.label IN ({', '.join('?' for _ in annotation_labels)})"
            )
            params.extend(annotation_labels)
        authors = _multi_values(annotation_author)
        if authors:
            where.append(f"ann.author IN ({', '.join('?' for _ in authors)})")
            params.extend(authors)
        if missing_evidence.strip():
            # Values are serialized as a JSON array; matching the quoted token
            # avoids treating a prefix as a different evidence item.
            where.append("ann.missing_evidence_json LIKE ?")
            params.append(f'%"{missing_evidence.strip()}"%')
        cleaned_ids = [
            str(item).strip()
            for item in (issue_ids or [])
            if str(item or "").strip()
        ][:2000]
        if cleaned_ids:
            placeholders = ", ".join("?" for _ in cleaned_ids)
            where.append(f"i.issue_id IN ({placeholders})")
            params.extend(cleaned_ids)
        assignees = _multi_values(work_assignee)
        if assignees:
            assignee_clauses: list[str] = []
            if any(
                value in {"__none__", "none", "未分配"} for value in assignees
            ):
                assignee_clauses.append("(wa.assignee IS NULL OR wa.assignee = '')")
            named = [
                value
                for value in assignees
                if value not in {"__none__", "none", "未分配"}
            ]
            if named:
                assignee_clauses.append(
                    f"wa.assignee IN ({', '.join('?' for _ in named)})"
                )
                params.extend(named)
            where.append(f"({' OR '.join(assignee_clauses)})")
        comparison_statuses = tuple(
            value
            for value in _multi_values(comparison_status)
            if value in {"match", "mismatch", "none"}
        )
        if comparison_statuses and set(comparison_statuses) != {
            "match",
            "mismatch",
            "none",
        }:
            where.append("i.gt_label IN (?, ?, ?)")
            params.extend(LABELS)
            status_clauses: list[str] = []
            for status in comparison_statuses:
                if status == "none":
                    status_clauses.append(
                        "(mp.model_label IS NULL OR mp.model_label NOT IN (?, ?, ?))"
                    )
                    params.extend(LABELS)
                elif status == "match":
                    status_clauses.append(
                        "(mp.model_label IN (?, ?, ?) AND mp.model_label = i.gt_label)"
                    )
                    params.extend(LABELS)
                else:
                    status_clauses.append(
                        "(mp.model_label IN (?, ?, ?) AND mp.model_label != i.gt_label)"
                    )
                    params.extend(LABELS)
            where.append(f"({' OR '.join(status_clauses)})")
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        common = f"""
            FROM issues i
            {self._latest_annotation_join(model_run_id)}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id
             AND mp.model_run_id = ?
            LEFT JOIN issue_work_assignments wa
              ON wa.issue_id = i.issue_id
        """
        # The correlated annotation lookup appears before the prediction JOIN
        # in the SQL, so its run id must be the first bound parameter.  A
        # selected Run has strict Review isolation; no legacy fallback.
        model_args = ([model_run_id] if model_run_id else []) + [model_run_id]
        return condition, params, model_args, common

    def list_cases(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        search: str = "",
        gt_label: str = "",
        model_label: str = "",
        annotation_label: str = "",
        annotation_author: str = "",
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        missing_evidence: str = "",
        issue_ids: list[str] | None = None,
        work_assignee: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        page = max(1, page)
        # Public routes cap pages at 100. Internal derived-status filtering may
        # materialize the complete bounded workset so Tag-only legacy Reviews
        # are filtered before pagination and task handoff.
        page_size = min(max(1, page_size), 5000)
        condition, params, model_args, common = self._case_list_filters(
            baseline_scope=baseline_scope,
            baseline_scopes=baseline_scopes,
            search=search,
            gt_label=gt_label,
            model_label=model_label,
            annotation_label=annotation_label,
            annotation_author=annotation_author,
            model_run_id=model_run_id,
            comparison_status=comparison_status,
            failure_only=failure_only,
            missing_evidence=missing_evidence,
            issue_ids=issue_ids,
            work_assignee=work_assignee,
        )
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(DISTINCT i.issue_id) {common} {condition}", (*model_args, *params)
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT i.*, ann.id AS annotation_id,
                       ann.label AS annotation_label, ann.review_status AS annotation_review_status,
                       ann.is_excluded AS annotation_is_excluded,
                       ann.tags_json AS annotation_tags_json,
                       ann.missing_evidence_json AS annotation_missing_evidence_json,
                       ann.note AS annotation_note, ann.author AS annotation_author,
                       ann.author_source AS annotation_author_source,
                       ann.author_verified AS annotation_author_verified,
                       ann.created_at AS annotation_created_at,
                       ann.model_run_id AS annotation_model_run_id,
                       mp.model_label, mp.model_reason, mp.model_confidence, mp.model_run_id,
                       COALESCE(wa.assignee, '') AS work_assignee,
                       COALESCE(wa.split_id, '') AS work_split_id
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

    def list_case_issue_ids(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        search: str = "",
        gt_label: str = "",
        model_label: str = "",
        annotation_label: str = "",
        annotation_author: str = "",
        model_run_id: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        missing_evidence: str = "",
        issue_ids: list[str] | None = None,
        work_assignee: str = "",
        limit: int = 5000,
    ) -> list[str]:
        """Return ordered issue IDs matching the same filters as list_cases."""

        condition, params, model_args, common = self._case_list_filters(
            baseline_scope=baseline_scope,
            baseline_scopes=baseline_scopes,
            search=search,
            gt_label=gt_label,
            model_label=model_label,
            annotation_label=annotation_label,
            annotation_author=annotation_author,
            model_run_id=model_run_id,
            comparison_status=comparison_status,
            failure_only=failure_only,
            missing_evidence=missing_evidence,
            issue_ids=issue_ids,
            work_assignee=work_assignee,
        )
        limit = min(max(1, int(limit)), 5000)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT i.issue_id
                {common}
                {condition}
                ORDER BY i.issue_id ASC
                LIMIT ?
                """,
                (*model_args, *params, limit),
            ).fetchall()
        return [str(row["issue_id"] if hasattr(row, "keys") else row[0]) for row in rows]

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

    def review_clusters(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        model_run_id: str = "",
        failure_only: bool = True,
        annotation_author: str = "",
    ) -> list[dict[str, Any]]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        scope_clause, scope_params = self._scope_in_sql(scopes)
        where = [scope_clause, "ann.id IS NOT NULL"]
        params: list[Any] = ([model_run_id] if model_run_id else []) + [
            model_run_id,
            *scope_params,
        ]
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
            {self._latest_annotation_join(model_run_id)}
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

    def overview(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if scopes:
            scope_clause, scope_params = self._scope_in_sql(scopes)
            base_where = f"WHERE {scope_clause}"
        else:
            # Legacy empty filter: count all issues (tests / unrestricted callers).
            scope_clause, scope_params = "1=1", []
            base_where = "WHERE 1=1"
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM issues i {base_where}", tuple(scope_params)
            ).fetchone()[0]
            labelled = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM issues i
                {self._latest_annotation_join(model_run_id)}
                {base_where} AND ann.id IS NOT NULL
                """,
                ((model_run_id, *scope_params)
                 if model_run_id else tuple(scope_params)),
            ).fetchone()[0]
            predictions = failures = reviewed_failures = 0
            if model_run_id:
                common = f"""
                    FROM issues i
                    {self._latest_annotation_join(model_run_id)}
                    LEFT JOIN model_predictions mp
                      ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
                    WHERE {scope_clause}
                """
                predictions = conn.execute(
                    f"SELECT COUNT(mp.id) {common}",
                    (model_run_id, model_run_id, *scope_params),
                ).fetchone()[0]
                failure_condition = " AND i.gt_label IN (?, ?, ?) AND mp.model_label IN (?, ?, ?) AND mp.model_label != i.gt_label"
                failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition}",
                    (model_run_id, model_run_id, *scope_params, *LABELS, *LABELS),
                ).fetchone()[0]
                reviewed_failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition} AND ann.id IS NOT NULL",
                    (model_run_id, model_run_id, *scope_params, *LABELS, *LABELS),
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
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        work_assignee = (
            str(row["work_assignee"] or "") if "work_assignee" in keys else ""
        )
        work_split_id = (
            str(row["work_split_id"] or "") if "work_split_id" in keys else ""
        )
        data.update(
            {
                "work_assignee": work_assignee,
                "work_split_id": work_split_id,
                "annotation": {
                    "id": row["annotation_id"] if "annotation_id" in keys else None,
                    "model_run_id": (
                        str(row["annotation_model_run_id"] or "")
                        if "annotation_model_run_id" in keys
                        else ""
                    ),
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

    def list_work_assignees(self) -> list[dict[str, Any]]:
        """Distinct people currently assigned via work-split."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT assignee, COUNT(*) AS issue_count
                FROM issue_work_assignments
                WHERE assignee <> ''
                GROUP BY assignee
                ORDER BY assignee ASC
                """
            ).fetchall()
        return [
            {
                "username": str(row["assignee"] or ""),
                "issue_count": int(row["issue_count"] or 0),
            }
            for row in rows
            if str(row["assignee"] or "").strip()
        ]

    def apply_work_split(
        self,
        *,
        assignments: list[dict[str, Any]],
        created_by: str,
        seed: int | None = None,
        filter_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a work-split batch and overwrite assignments for its issues."""

        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("均分操作人不能为空。")
        if not assignments:
            raise ValueError("分配结果为空。")
        split_id = f"split-{uuid.uuid4().hex}"
        now = utc_now()
        rows: list[tuple[str, str, str, str, str]] = []
        for item in assignments:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            for issue_id in item.get("issue_ids") or []:
                cleaned = str(issue_id or "").strip()
                if not cleaned:
                    continue
                rows.append((cleaned, name, split_id, actor, now))
        if not rows:
            raise ValueError("没有可写入的 Issue 分配。")
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO issue_work_splits (
                    id, created_by, created_at, seed, total_count, filter_json, assignees_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    split_id,
                    actor,
                    now,
                    seed,
                    len(rows),
                    json.dumps(filter_snapshot or {}, ensure_ascii=False),
                    json.dumps(assignments, ensure_ascii=False),
                ),
            )
            for issue_id, assignee, sid, assigned_by, assigned_at in rows:
                conn.execute(
                    """
                    INSERT INTO issue_work_assignments (
                        issue_id, assignee, split_id, assigned_by, assigned_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(issue_id) DO UPDATE SET
                        assignee = excluded.assignee,
                        split_id = excluded.split_id,
                        assigned_by = excluded.assigned_by,
                        assigned_at = excluded.assigned_at
                    """,
                    (issue_id, assignee, sid, assigned_by, assigned_at),
                )
        return {
            "split_id": split_id,
            "created_by": actor,
            "created_at": now,
            "seed": seed,
            "total": len(rows),
            "assignments": assignments,
        }
