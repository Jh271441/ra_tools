from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from .shared import (
    COMPARISON_STATUSES,
    LABELS,
    MODEL_LABELS,
    _json,
    _json_load,
    model_label_matches_gt,
    model_prediction_match_sql,
    model_prediction_mismatch_sql,
    model_prediction_no_gt_sql,
    model_prediction_none_sql,
    utc_now,
)


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

    def issue_baseline_scopes(self, issue_ids: Sequence[str]) -> dict[str, str]:
        """Return the release scope for each requested Issue in one query batch.

        Trail's direct Issue-ID workflow starts from a remote Issue list, so it
        cannot infer whether an Issue belongs to 0206, 0508, or 0626 from the
        Trail payload.  Keep the lookup local and bounded; this is provenance
        display only and never changes the active baseline scope.
        """

        cleaned = list(dict.fromkeys(
            str(issue_id or "").strip()
            for issue_id in issue_ids
            if str(issue_id or "").strip()
        ))
        if not cleaned:
            return {}
        result: dict[str, str] = {}
        with self.connect() as conn:
            for offset in range(0, len(cleaned), 500):
                batch = cleaned[offset : offset + 500]
                placeholders = ", ".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT issue_id, baseline_scope FROM issues WHERE issue_id IN ({placeholders})",
                    batch,
                ).fetchall()
                for row in rows:
                    issue_id = str(row["issue_id"] or "").strip()
                    if issue_id:
                        result[issue_id] = str(row["baseline_scope"] or "").strip()
        return result

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

    def _gallery_annotation_join(
        self,
        model_run_id: str,
        *,
        projection_authors: Sequence[str] = (),
    ) -> tuple[str, list[Any]]:
        """Project the primary assignment Review without hiding old behavior.

        Multi-review is additive cross-validation. When an Issue has an active
        assignment for the selected Run, the Gallery projects the explicitly
        requested reviewer/assignee, or the base assignee by default. A blind
        member reads their split-scoped annotation; a legacy single assignment
        keeps using its ordinary annotation. Issues without an assignment keep
        the established selected-Run/unbound/history fallback.
        """

        run_id = str(model_run_id or "").strip()
        authors = tuple(
            dict.fromkeys(str(value or "").strip() for value in projection_authors)
        )
        authors = tuple(value for value in authors if value)
        author_clause = ""
        author_params: list[Any] = []
        if authors:
            author_clause = (
                f"AND wa.assignee IN ({', '.join('?' for _ in authors)})"
            )
            author_params.extend(authors)

        assignment_exists = f"""
            EXISTS (
                SELECT 1
                FROM review_work_assignments wa
                JOIN issue_work_splits ws ON ws.id = wa.split_id
                WHERE wa.issue_id = i.issue_id
                  AND ws.model_run_id = ?
                  {author_clause}
            )
        """
        assignment_annotation = f"""
            (
                SELECT a.id
                FROM review_work_assignments wa
                JOIN issue_work_splits ws ON ws.id = wa.split_id
                LEFT JOIN annotations a
                  ON a.issue_id = wa.issue_id
                 AND a.model_run_id = ws.model_run_id
                 AND a.author = wa.assignee
                 AND (
                      (ws.mode = 'blind' AND a.work_split_id = ws.id)
                      OR (ws.mode != 'blind' AND a.work_split_id = '')
                 )
                WHERE wa.issue_id = i.issue_id
                  AND ws.model_run_id = ?
                  {author_clause}
                ORDER BY
                  CASE WHEN a.id IS NULL THEN 1 ELSE 0 END,
                  CASE WHEN wa.assignment_kind = 'base' THEN 0 ELSE 1 END,
                  a.id DESC
                LIMIT 1
            )
        """
        if run_id:
            ordinary_annotation = """
                COALESCE(
                    (
                        SELECT a.id FROM annotations a
                        WHERE a.issue_id = i.issue_id
                          AND a.model_run_id = ?
                          AND a.work_split_id = ''
                        ORDER BY a.id DESC LIMIT 1
                    ),
                    (
                        SELECT a.id FROM annotations a
                        WHERE a.issue_id = i.issue_id
                          AND a.model_run_id = ''
                          AND a.work_split_id = ''
                        ORDER BY a.id DESC LIMIT 1
                    ),
                    (
                        SELECT a.id FROM annotations a
                        WHERE a.issue_id = i.issue_id
                          AND a.model_run_id NOT IN (?, '')
                          AND a.work_split_id = ''
                        ORDER BY a.id DESC LIMIT 1
                    )
                )
            """
            ordinary_params: list[Any] = [run_id, run_id]
        else:
            ordinary_annotation = """
                (
                    SELECT a.id FROM annotations a
                    WHERE a.issue_id = i.issue_id
                      AND a.work_split_id = ''
                    ORDER BY a.id DESC LIMIT 1
                )
            """
            ordinary_params = []
        join = f"""
            LEFT JOIN annotations ann
              ON ann.id = CASE
                  WHEN {assignment_exists} THEN {assignment_annotation}
                  ELSE {ordinary_annotation}
              END
        """
        params = [
            run_id,
            *author_params,
            run_id,
            *author_params,
            *ordinary_params,
        ]
        return join, params

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
        is_excluded: bool | None = None,
    ) -> tuple[str, list[Any], list[Any], str]:
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

        comparison_status = str(comparison_status or "all").strip().lower()
        if failure_only:
            comparison_status = "mismatch"
        raw_comparison_statuses = _multi_values(comparison_status)
        if not raw_comparison_statuses:
            raw_comparison_statuses = ("all",)
        if any(value not in COMPARISON_STATUSES for value in raw_comparison_statuses):
            raise ValueError("unsupported comparison_status")
        comparison_statuses = tuple(
            value for value in raw_comparison_statuses if value != "all"
        )
        if comparison_statuses and not model_run_id:
            raise ValueError("comparison_status requires model_run_id")

        if search.strip():
            term = f"%{search.strip()}%"
            where.append("(i.issue_id LIKE ? OR i.title LIKE ? OR i.scenario LIKE ? OR i.summary LIKE ?)")
            params.extend([term, term, term, term])
        gt_labels = tuple(value for value in _multi_values(gt_label) if value in LABELS)
        if gt_labels:
            where.append(f"i.gt_label IN ({', '.join('?' for _ in gt_labels)})")
            params.extend(gt_labels)
        model_labels = tuple(
            value for value in _multi_values(model_label) if value in MODEL_LABELS
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
        if is_excluded is not None:
            # No local Review is an included case.  COALESCE keeps that
            # intuitive all/included/excluded split while supporting SQLite
            # and PostgreSQL boolean storage.
            where.append("COALESCE(ann.is_excluded, FALSE) = ?")
            params.append(bool(is_excluded))
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
        named: list[str] = []
        if assignees:
            assignee_clauses: list[str] = []
            if any(
                value in {"__none__", "none", "未分配"} for value in assignees
            ):
                assignee_clauses.append(
                    "NOT EXISTS (SELECT 1 FROM review_work_assignments wa_none "
                    "JOIN issue_work_splits ws_none ON ws_none.id = wa_none.split_id "
                    "WHERE wa_none.issue_id = i.issue_id AND ws_none.model_run_id = ?)"
                )
                params.append(model_run_id)
            named = [
                value
                for value in assignees
                if value not in {"__none__", "none", "未分配"}
            ]
            if named:
                assignee_clauses.append(
                    "EXISTS (SELECT 1 FROM review_work_assignments wa_named "
                    "JOIN issue_work_splits ws_named ON ws_named.id = wa_named.split_id "
                    f"WHERE wa_named.issue_id = i.issue_id AND ws_named.model_run_id = ? "
                    f"AND wa_named.assignee IN "
                    f"({', '.join('?' for _ in named)}))"
                )
                params.extend((model_run_id, *named))
            where.append(f"({' OR '.join(assignee_clauses)})")
        if comparison_statuses and set(comparison_statuses) != {
            "match",
            "mismatch",
            "no_gt",
            "none",
        }:
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
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        # The Gallery is the operator's Review-progress surface.  A legacy
        # unbound Review is valid shared human evidence when no Review exists
        # for the selected Run; see ``_latest_annotation_join`` for its
        # selected-Run precedence rule.  This deliberately differs from the
        # strict Trail-writing aggregate.
        annotation_join, annotation_params = self._gallery_annotation_join(
            model_run_id,
            projection_authors=authors or tuple(named),
        )
        common = f"""
            FROM issues i
            {annotation_join}
            LEFT JOIN model_predictions mp
              ON mp.issue_id = i.issue_id
             AND mp.model_run_id = ?
        """
        # The correlated annotation lookup appears before the prediction JOIN
        # in the SQL, so its bind values must precede the prediction Run id.
        model_args = [*annotation_params, model_run_id]
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
        is_excluded: bool | None = None,
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
            is_excluded=is_excluded,
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
                       COALESCE((
                           SELECT MIN(wa.assignee) FROM review_work_assignments wa
                           WHERE wa.issue_id = i.issue_id
                       ), '') AS work_assignee,
                       COALESCE((
                           SELECT MIN(wa.split_id) FROM review_work_assignments wa
                           WHERE wa.issue_id = i.issue_id
                       ), '') AS work_split_id
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
        is_excluded: bool | None = None,
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
            is_excluded=is_excluded,
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

    def list_case_review_candidates(
        self,
        *,
        limit: int = 5000,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Return the minimal projection needed for derived Review status.

        Historical Reviews can omit ``label`` and rely on structured Tags, so
        their effective status still needs Python inference.  Avoid loading the
        full Case/prediction summary for every matching Issue just to derive
        that status; the public route fetches full rows only for the requested
        page after this bounded projection is filtered.
        """

        condition, params, model_args, common = self._case_list_filters(**filters)
        limit = min(max(1, int(limit)), 5000)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT i.issue_id, i.gt_label,
                       ann.id AS annotation_id,
                       ann.label AS annotation_label,
                       ann.tags_json AS annotation_tags_json
                {common}
                {condition}
                ORDER BY i.issue_id ASC
                LIMIT ?
                """,
                (*model_args, *params, limit),
            ).fetchall()
        return [
            {
                "issue_id": str(row["issue_id"] or ""),
                "gt_label": str(row["gt_label"] or ""),
                "annotation": {
                    "id": row["annotation_id"],
                    "label": str(row["annotation_label"] or ""),
                    "tags": _json_load(row["annotation_tags_json"], []),
                },
            }
            for row in rows
        ]

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

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Return only the ``issues`` row for callers that need scope/link fields.

        This is a light alternative to :meth:`get_case` for endpoints that only
        read ``baseline_scope`` (media/asset resolution) or the imported RA link
        fallback (``ra_id``/``ra_event``/``extra``) and never touch annotations,
        predictions, jobs, attachments, or materialized review history.  Those
        five extra queries plus history assembly are pure overhead there.
        """

        with self.connect() as conn:
            issue = conn.execute(
                "SELECT * FROM issues WHERE issue_id = ?", (issue_id,)
            ).fetchone()
        if issue is None:
            return None
        return self._issue_dict(issue)

    def review_clusters(
        self,
        *,
        baseline_scope: str = "",
        baseline_scopes: Sequence[str] | None = None,
        model_run_id: str = "",
        failure_only: bool = True,
        annotation_author: str = "",
        is_excluded: bool | None = None,
    ) -> list[dict[str, Any]]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        scope_clause, scope_params = self._scope_in_sql(scopes)
        where = [scope_clause, "ann.id IS NOT NULL"]
        annotation_params = self._latest_annotation_join_params(
            model_run_id,
            include_unbound_fallback=True,
            include_bound_history_fallback=True,
        )
        params: list[Any] = [*annotation_params, model_run_id, *scope_params]
        if failure_only and model_run_id:
            mismatch_sql, mismatch_params = model_prediction_mismatch_sql()
            where.extend(
                [
                    "i.gt_label IN (?, ?, ?)",
                    mismatch_sql,
                ]
            )
            params.extend((*LABELS, *mismatch_params))
        if annotation_author.strip():
            where.append("ann.author = ?")
            params.append(annotation_author.strip())
        if is_excluded is not None:
            where.append("ann.is_excluded = ?")
            # SQLite stores the legacy flag as INTEGER; PostgreSQL accepts the
            # native bool.  Binding Python bool keeps both backends portable.
            params.append(bool(is_excluded))
        query = f"""
            SELECT ann.missing_evidence_json
            FROM issues i
            {self._latest_annotation_join(
                model_run_id,
                include_unbound_fallback=True,
                include_bound_history_fallback=True,
            )}
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
            annotation_join, annotation_params = self._gallery_annotation_join(
                model_run_id
            )
            labelled = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM issues i
                {annotation_join}
                {base_where} AND ann.id IS NOT NULL
                """,
                (*annotation_params, *scope_params),
            ).fetchone()[0]
            predictions = failures = reviewed_failures = 0
            if model_run_id:
                common = f"""
                    FROM issues i
                    {annotation_join}
                    LEFT JOIN model_predictions mp
                      ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
                    WHERE {scope_clause}
                """
                predictions = conn.execute(
                    f"SELECT COUNT(mp.id) {common}",
                    (*annotation_params, model_run_id, *scope_params),
                ).fetchone()[0]
                mismatch_sql, mismatch_params = model_prediction_mismatch_sql()
                failure_condition = f" AND i.gt_label IN (?, ?, ?) AND {mismatch_sql}"
                failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition}",
                    (
                        *annotation_params,
                        model_run_id,
                        *scope_params,
                        *LABELS,
                        *mismatch_params,
                    ),
                ).fetchone()[0]
                reviewed_failures = conn.execute(
                    f"SELECT COUNT(*) {common}{failure_condition} AND ann.id IS NOT NULL",
                    (
                        *annotation_params,
                        model_run_id,
                        *scope_params,
                        *LABELS,
                        *mismatch_params,
                    ),
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
        comparable = bool(
            data["gt_label"] in LABELS and model_label in MODEL_LABELS
        )
        matches = model_label_matches_gt(model_label, data["gt_label"])
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
                    "mismatch": bool(comparable and not matches),
                },
            }
        )
        return data

    def list_work_assignees(
        self, *, issue_ids: Sequence[str] | None = None, model_run_id: str = ""
    ) -> list[dict[str, Any]]:
        """Distinct assignees, optionally scoped to an exact Review queue."""

        cleaned_ids = (
            list(
                dict.fromkeys(
                    str(issue_id or "").strip()
                    for issue_id in issue_ids
                    if str(issue_id or "").strip()
                )
            )
            if issue_ids is not None
            else None
        )
        if cleaned_ids == []:
            return []

        counts: dict[str, int] = {}
        with self.connect() as conn:
            if cleaned_ids is None:
                batches: list[list[str] | None] = [None]
            else:
                # Stay below conservative SQLite variable limits while using
                # the same query path through the PostgreSQL compatibility adapter.
                batches = [
                    cleaned_ids[offset : offset + 500]
                    for offset in range(0, len(cleaned_ids), 500)
                ]
            for batch in batches:
                issue_clause = ""
                params: list[Any] = []
                if batch is not None:
                    issue_clause = (
                        f"AND assignment.issue_id IN ({', '.join('?' for _ in batch)})"
                    )
                    params.extend(batch)
                rows = conn.execute(
                    f"""
                    SELECT assignment.assignee, COUNT(*) AS issue_count
                    FROM review_work_assignments assignment
                    JOIN issue_work_splits split ON split.id = assignment.split_id
                    WHERE assignment.assignee <> '' AND split.model_run_id = ?
                    {issue_clause}
                    GROUP BY assignment.assignee
                    ORDER BY assignment.assignee ASC
                    """,
                    (str(model_run_id or "").strip(), *params),
                ).fetchall()
                for row in rows:
                    username = str(row["assignee"] or "").strip()
                    if username:
                        counts[username] = counts.get(username, 0) + int(
                            row["issue_count"] or 0
                        )
        return [
            {"username": username, "issue_count": counts[username]}
            for username in sorted(counts)
        ]

    def review_assignment_context(
        self,
        issue_id: str,
        *,
        model_run_id: str = "",
        username: str = "",
    ) -> dict[str, Any] | None:
        """Return the current assignment snapshot for one Issue/Run."""

        with self.connect() as conn:
            split = conn.execute(
                """
                SELECT split.*
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                WHERE assignment.issue_id = ? AND split.model_run_id = ?
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT 1
                """,
                (str(issue_id or "").strip(), str(model_run_id or "").strip()),
            ).fetchone()
            if split is None:
                return None
            rows = conn.execute(
                """
                SELECT assignment.assignee, assignment.assignment_kind,
                       assignment.ordinal,
                       (
                           SELECT annotation.id FROM annotations annotation
                           WHERE annotation.issue_id = assignment.issue_id
                             AND annotation.model_run_id = ?
                             AND annotation.work_split_id = assignment.split_id
                             AND annotation.author = assignment.assignee
                           ORDER BY annotation.id DESC LIMIT 1
                       ) AS annotation_id
                FROM review_work_assignments assignment
                WHERE assignment.issue_id = ? AND assignment.split_id = ?
                ORDER BY assignment.assignee ASC
                """,
                (str(model_run_id or "").strip(), issue_id, split["id"]),
            ).fetchall()
        current = str(username or "").strip().lower()
        members = [
            {
                "username": str(row["assignee"]),
                "assignment_kind": str(row["assignment_kind"]),
                "ordinal": int(row["ordinal"]),
                "submitted": row["annotation_id"] is not None,
            }
            for row in rows
        ]
        own = next(
            (item for item in members if item["username"].lower() == current),
            None,
        )
        return {
            "split_id": str(split["id"]),
            "mode": str(split["mode"] or "single"),
            "model_run_id": str(split["model_run_id"] or ""),
            "reviewers_per_issue": int(split["reviewers_per_issue"] or 1),
            "assigned_count": len(members),
            "submitted_count": sum(bool(item["submitted"]) for item in members),
            "assigned": own is not None,
            "own_assignment": own,
            "members": members,
        }

    def review_multi_rows(
        self,
        *,
        baseline_scopes: Sequence[str],
        model_run_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return one row per current blind assignment member for aggregation."""

        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            return []
        scope_clause, scope_params = self._scope_in_sql(scopes)
        selected_run_id = str(model_run_id or "").strip()
        if selected_run_id:
            split_filter = "split.model_run_id = ?"
            split_params: list[Any] = [selected_run_id]
            prediction_run_id = selected_run_id
        else:
            # No model overlay is a global human-Review view, not the legacy
            # empty-Run namespace. Pick the newest blind split for each Issue
            # across Runs so current cross-validation evidence remains visible
            # without duplicating an Issue from historical assignments.
            split_filter = """
                split.id = (
                    SELECT latest_split.id
                    FROM issue_work_splits latest_split
                    JOIN review_work_assignments latest_assignment
                      ON latest_assignment.split_id = latest_split.id
                    WHERE latest_assignment.issue_id = assignment.issue_id
                      AND latest_split.mode = 'blind'
                    ORDER BY latest_split.created_at DESC, latest_split.id DESC
                    LIMIT 1
                )
            """
            split_params = []
            # A no-overlay response must not silently attach the split's model
            # prediction. The Review retains its own immutable Run binding.
            prediction_run_id = ""
        query = f"""
            SELECT i.issue_id, i.title, i.scenario, i.summary, i.gt_label,
                   i.baseline_scope, assignment.split_id, assignment.assignee,
                   split.model_run_id AS split_model_run_id,
                   annotation.id AS annotation_id,
                   annotation.label AS annotation_label,
                   annotation.review_status AS annotation_review_status,
                   annotation.is_excluded AS annotation_is_excluded,
                   annotation.tags_json AS annotation_tags_json,
                   annotation.missing_evidence_json AS annotation_missing_evidence_json,
                   annotation.note AS annotation_note,
                   annotation.author AS annotation_author,
                   annotation.author_source AS annotation_author_source,
                   annotation.author_verified AS annotation_author_verified,
                   annotation.created_at AS annotation_created_at,
                   prediction.model_run_id, prediction.model_label,
                   prediction.model_reason, prediction.model_confidence
            FROM review_work_assignments assignment
            JOIN issue_work_splits split ON split.id = assignment.split_id
            JOIN issues i ON i.issue_id = assignment.issue_id
            LEFT JOIN annotations annotation ON annotation.id = (
                SELECT candidate.id FROM annotations candidate
                WHERE candidate.issue_id = assignment.issue_id
                  AND candidate.model_run_id = split.model_run_id
                  AND candidate.work_split_id = assignment.split_id
                  AND candidate.author = assignment.assignee
                ORDER BY candidate.id DESC LIMIT 1
            )
            LEFT JOIN model_predictions prediction
              ON prediction.issue_id = i.issue_id
             AND prediction.model_run_id = ?
            WHERE split.mode = 'blind' AND {split_filter}
              AND {scope_clause}
            ORDER BY i.issue_id ASC, assignment.assignee ASC
        """
        with self.connect() as conn:
            rows = conn.execute(
                query,
                (prediction_run_id, *split_params, *scope_params),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            annotation = None
            if row["annotation_id"] is not None:
                annotation = {
                    "id": int(row["annotation_id"]),
                    "model_run_id": str(row["split_model_run_id"] or ""),
                    "work_split_id": str(row["split_id"]),
                    "label": str(row["annotation_label"] or ""),
                    "review_status": str(row["annotation_review_status"] or "pending"),
                    "is_excluded": bool(row["annotation_is_excluded"]),
                    "tags": _json_load(row["annotation_tags_json"], []),
                    "missing_evidence": _json_load(
                        row["annotation_missing_evidence_json"], []
                    ),
                    "note": str(row["annotation_note"] or ""),
                    "author": str(row["annotation_author"] or row["assignee"]),
                    "author_source": str(row["annotation_author_source"] or "legacy"),
                    "author_verified": bool(row["annotation_author_verified"]),
                    "created_at": str(row["annotation_created_at"] or ""),
                }
            results.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "title": str(row["title"] or ""),
                    "scenario": str(row["scenario"] or ""),
                    "summary": str(row["summary"] or ""),
                    "gt_label": str(row["gt_label"] or ""),
                    "split_id": str(row["split_id"]),
                    "assignee": str(row["assignee"]),
                    "annotation": annotation,
                    "prediction": {
                        "model_run_id": str(row["model_run_id"] or ""),
                        "label": str(row["model_label"] or ""),
                        "reason": str(row["model_reason"] or ""),
                        "confidence": row["model_confidence"],
                    },
                }
            )
        return results

    def apply_work_split(
        self,
        *,
        assignments: list[dict[str, Any]],
        created_by: str,
        seed: int | None = None,
        filter_snapshot: dict[str, Any] | None = None,
        reviewers_per_issue: int = 1,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        """Persist a work-split batch and overwrite assignments for its issues."""

        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("均分操作人不能为空。")
        if not assignments:
            raise ValueError("分配结果为空。")
        split_id = f"split-{uuid.uuid4().hex}"
        now = utc_now()
        rows: list[tuple[str, str, str, int, str, str]] = []
        for item in assignments:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            assignment_items = item.get("items") or [
                {
                    "issue_id": issue_id,
                    "assignment_kind": "base",
                    "ordinal": ordinal,
                }
                for ordinal, issue_id in enumerate(item.get("issue_ids") or [], 1)
            ]
            for assignment in assignment_items:
                cleaned = str(assignment.get("issue_id") or "").strip()
                if not cleaned:
                    continue
                rows.append(
                    (
                        cleaned,
                        name,
                        str(assignment.get("assignment_kind") or "base"),
                        int(assignment.get("ordinal") or 1),
                        actor,
                        now,
                    )
                )
        if not rows:
            raise ValueError("没有可写入的 Issue 分配。")
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO issue_work_splits (
                    id, created_by, created_at, seed, total_count, filter_json,
                    assignees_json, mode, reviewers_per_issue, model_run_id,
                    assignment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    split_id,
                    actor,
                    now,
                    seed,
                    len({row[0] for row in rows}),
                    json.dumps(filter_snapshot or {}, ensure_ascii=False),
                    json.dumps(assignments, ensure_ascii=False),
                    "blind" if reviewers_per_issue > 1 else "single",
                    reviewers_per_issue,
                    str(model_run_id or "").strip(),
                    len(rows),
                ),
            )
            issue_ids = sorted({row[0] for row in rows})
            for offset in range(0, len(issue_ids), 500):
                batch = issue_ids[offset : offset + 500]
                conn.execute(
                    "DELETE FROM review_work_assignments WHERE split_id IN "
                    "(SELECT id FROM issue_work_splits WHERE model_run_id = ?) "
                    f"AND issue_id IN ({', '.join('?' for _ in batch)})",
                    (str(model_run_id or "").strip(), *batch),
                )
            for issue_id, assignee, kind, ordinal, assigned_by, assigned_at in rows:
                conn.execute(
                    """
                    INSERT INTO review_work_assignments (
                        split_id, issue_id, assignee, assignment_kind, ordinal,
                        assigned_by, assigned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (split_id, issue_id, assignee, kind, ordinal, assigned_by, assigned_at),
                )
        return {
            "split_id": split_id,
            "created_by": actor,
            "created_at": now,
            "seed": seed,
            "total": len({row[0] for row in rows}),
            "assignment_count": len(rows),
            "reviewers_per_issue": reviewers_per_issue,
            "assignments": assignments,
        }
