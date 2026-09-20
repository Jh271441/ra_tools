from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Iterator, Sequence

from ..work_split import normalize_overlap_ratio
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
        preferred_annotation_author: str = "",
        work_split_id: str = "",
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
        preferred_author = str(preferred_annotation_author or "").strip()
        split_id = str(work_split_id or "").strip()
        # An explicit reviewer/assignee filter owns the projection. The signed-
        # in user's Review is only the default preference when no such filter
        # was requested.
        if authors:
            preferred_author = ""
        author_clause = ""
        author_params: list[Any] = []
        if authors:
            author_clause = (
                f"AND wa.assignee IN ({', '.join('?' for _ in authors)})"
            )
            author_params.extend(authors)
        split_clause = "AND ws.id = ?" if split_id else ""
        split_params: list[Any] = [split_id] if split_id else []
        preferred_order = (
            "CASE WHEN a.author = ? THEN 0 ELSE 1 END,"
            if preferred_author
            else ""
        )

        assignment_exists = f"""
            EXISTS (
                SELECT 1
                FROM review_work_assignments wa
                JOIN issue_work_splits ws ON ws.id = wa.split_id
                WHERE wa.issue_id = i.issue_id
                  AND ws.model_run_id = ?
                  {author_clause}
                  {split_clause}
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
                  {split_clause}
                ORDER BY
                  CASE WHEN a.id IS NULL THEN 1 ELSE 0 END,
                  {preferred_order}
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
            *split_params,
            run_id,
            *author_params,
            *split_params,
            *([preferred_author] if preferred_author else []),
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
        work_split_id: str = "",
        comment_state: str = "all",
        preferred_annotation_author: str = "",
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

        normalized_comment_state = str(comment_state or "all").strip().lower()
        if normalized_comment_state not in {"all", "with", "without"}:
            raise ValueError("unsupported comment_state")

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
        if normalized_comment_state != "all":
            comment_run_clause = " AND rc.model_run_id = ?" if model_run_id else ""
            comment_exists = (
                "EXISTS (SELECT 1 FROM review_comments rc "
                "WHERE rc.issue_id = i.issue_id"
                f"{comment_run_clause})"
            )
            where.append(
                comment_exists
                if normalized_comment_state == "with"
                else f"NOT {comment_exists}"
            )
            if model_run_id:
                params.append(model_run_id)
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
        normalized_work_split_id = str(work_split_id or "").strip()
        if normalized_work_split_id:
            if not model_run_id:
                raise ValueError("work_split_id requires model_run_id")
            where.append(
                "EXISTS (SELECT 1 FROM review_work_assignments wa_split "
                "JOIN issue_work_splits ws_split ON ws_split.id = wa_split.split_id "
                "WHERE wa_split.issue_id = i.issue_id AND ws_split.id = ? "
                "AND ws_split.model_run_id = ?)"
            )
            params.extend((normalized_work_split_id, model_run_id))
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
            preferred_annotation_author=preferred_annotation_author,
            work_split_id=normalized_work_split_id,
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
        work_split_id: str = "",
        comment_state: str = "all",
        preferred_annotation_author: str = "",
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
            work_split_id=work_split_id,
            comment_state=comment_state,
            preferred_annotation_author=preferred_annotation_author,
            is_excluded=is_excluded,
        )
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(DISTINCT i.issue_id) {common} {condition}", (*model_args, *params)
            ).fetchone()[0]
            assignment_summary_join = """
                LEFT JOIN (
                    SELECT issue_id,
                           MIN(assignee) AS work_assignee,
                           MIN(split_id) AS work_split_id
                    FROM review_work_assignments
                    GROUP BY issue_id
                ) work_summary
                  ON work_summary.issue_id = i.issue_id
            """
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
                       COALESCE(work_summary.work_assignee, '') AS work_assignee,
                       COALESCE(work_summary.work_split_id, '') AS work_split_id
                {common}
                {assignment_summary_join}
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
            "gt_snapshots": self.active_gt_snapshots(
                self._normalize_baseline_scopes(
                    baseline_scopes, baseline_scope=baseline_scope
                )
            ),
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
        work_split_id: str = "",
        comment_state: str = "all",
        preferred_annotation_author: str = "",
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
            work_split_id=work_split_id,
            comment_state=comment_state,
            preferred_annotation_author=preferred_annotation_author,
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
                SELECT DISTINCT i.issue_id, i.baseline_scope, i.gt_label,
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
                "baseline_scope": str(row["baseline_scope"] or ""),
                "gt_label": str(row["gt_label"] or ""),
                "annotation": {
                    "id": row["annotation_id"],
                    "label": str(row["annotation_label"] or ""),
                    "tags": _json_load(row["annotation_tags_json"], []),
                },
            }
            for row in rows
        ]

    def iter_case_review_candidate_batches(
        self, *, batch_size: int = 400, **filters: Any
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield the complete Review candidate set in ordered bounded batches.

        Unlike the legacy convenience method above, this internal scan has no
        result cap. Keyset pagination keeps each SQL parameter set small and
        avoids loading the whole multi-baseline candidate set at once.
        """

        batch_size = min(max(1, int(batch_size)), 1000)
        condition, params, model_args, common = self._case_list_filters(**filters)
        last_issue_id = ""
        with self.connect() as conn:
            while True:
                batch_condition = (
                    f"{condition} AND i.issue_id > ?"
                    if condition
                    else "WHERE i.issue_id > ?"
                )
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT i.issue_id, i.baseline_scope, i.gt_label,
                           ann.id AS annotation_id,
                           ann.label AS annotation_label,
                           ann.tags_json AS annotation_tags_json
                    {common}
                    {batch_condition}
                    ORDER BY i.issue_id ASC
                    LIMIT ?
                    """,
                    (*model_args, *params, last_issue_id, batch_size),
                ).fetchall()
                if not rows:
                    break
                yield [
                    {
                        "issue_id": str(row["issue_id"] or ""),
                        "baseline_scope": str(row["baseline_scope"] or ""),
                        "gt_label": str(row["gt_label"] or ""),
                        "annotation": {
                            "id": row["annotation_id"],
                            "label": str(row["annotation_label"] or ""),
                            "tags": _json_load(row["annotation_tags_json"], []),
                        },
                    }
                    for row in rows
                ]
                last_issue_id = str(rows[-1]["issue_id"] or "")
                if len(rows) < batch_size:
                    break

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
        label_states = self.project_issue_label_states(
            str(data.get("baseline_scope") or ""),
            [issue_id],
        )
        data["label_state"] = label_states.get(
            issue_id,
            {
                "state": "none",
                "expected_output": "",
                "gt_relation": "unknown",
                "method": "single",
                "source_task_ids": [],
                "source_revision_ids": [],
                "sources": [],
            },
        )
        data["gt_snapshot"] = self.get_active_gt_snapshot(
            str(data.get("baseline_scope") or "")
        )
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
        work_split_id: str = "",
        is_excluded: bool | None = None,
    ) -> list[dict[str, Any]]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        scope_clause, scope_params = self._scope_in_sql(scopes)
        where = [scope_clause, "ann.id IS NOT NULL"]
        normalized_work_split_id = str(work_split_id or "").strip()
        if normalized_work_split_id:
            annotation_join, annotation_params = self._gallery_annotation_join(
                model_run_id,
                work_split_id=normalized_work_split_id,
            )
            where.append(
                "EXISTS (SELECT 1 FROM review_work_assignments wa_split "
                "WHERE wa_split.issue_id = i.issue_id AND wa_split.split_id = ?)"
            )
        else:
            annotation_join = self._latest_annotation_join(
                model_run_id,
                include_unbound_fallback=True,
                include_bound_history_fallback=True,
            )
            annotation_params = self._latest_annotation_join_params(
                model_run_id,
                include_unbound_fallback=True,
                include_bound_history_fallback=True,
            )
        params: list[Any] = [*annotation_params, model_run_id, *scope_params]
        if normalized_work_split_id:
            params.append(normalized_work_split_id)
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
            {annotation_join}
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
        label_state_counts = self.issue_label_state_counts(scopes)
        return {
            "issues": int(total),
            "labelled": int(labelled),
            "unlabelled": max(int(total) - int(labelled), 0),
            "predictions": int(predictions),
            "model_failures": int(failures),
            "reviewed_failures": int(reviewed_failures),
            "running_jobs": int(running),
            "label_state_counts": label_state_counts,
            "gt_snapshots": self.active_gt_snapshots(scopes),
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

    @staticmethod
    def _work_split_snapshot_members(value: Any) -> list[dict[str, Any]]:
        """Normalize the original split payload for history/fallback views."""

        raw_members = _json_load(value, [])
        if not isinstance(raw_members, list):
            return []
        members: list[dict[str, Any]] = []
        for raw_member in raw_members:
            if not isinstance(raw_member, dict):
                continue
            name = str(raw_member.get("name") or "").strip()
            if not name:
                continue
            raw_items = raw_member.get("items")
            items: list[dict[str, Any]] = []
            if isinstance(raw_items, list):
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict):
                        continue
                    issue_id = str(raw_item.get("issue_id") or "").strip()
                    if not issue_id:
                        continue
                    items.append(
                        {
                            "issue_id": issue_id,
                            "assignment_kind": str(
                                raw_item.get("assignment_kind") or "base"
                            ),
                            "ordinal": int(raw_item.get("ordinal") or len(items) + 1),
                        }
                    )
            if not items:
                items = [
                    {
                        "issue_id": str(issue_id).strip(),
                        "assignment_kind": "base",
                        "ordinal": index,
                    }
                    for index, issue_id in enumerate(raw_member.get("issue_ids") or [], 1)
                    if str(issue_id or "").strip()
                ]
            members.append(
                {
                    "name": name,
                    "count": len(items),
                    "requested_count": raw_member.get("requested_count"),
                    "mode": str(raw_member.get("mode") or "share"),
                    "items": items,
                }
            )
        return members

    def list_review_work_splits(
        self, *, limit: int = 50, model_run_id: str = ""
    ) -> list[dict[str, Any]]:
        """Return assignment batches with current completion statistics."""

        safe_limit = max(1, min(int(limit or 50), 100))
        run_id = str(model_run_id or "").strip()
        where = "WHERE split.task_kind != 'labeling'"
        parameters: list[Any] = []
        if run_id:
            where += " AND split.model_run_id = ?"
            parameters.append(run_id)
        with self.connect() as conn:
            split_rows = conn.execute(
                f"""
                SELECT split.*,
                       COALESCE(current.assignment_count, 0) AS current_assignment_count,
                       COALESCE(current.issue_count, 0) AS current_issue_count
                FROM issue_work_splits split
                LEFT JOIN (
                    SELECT split_id,
                           COUNT(*) AS assignment_count,
                           COUNT(DISTINCT issue_id) AS issue_count
                    FROM review_work_assignments
                    GROUP BY split_id
                ) current ON current.split_id = split.id
                {where}
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT ?
                """,
                (*parameters, safe_limit),
            ).fetchall()
            if not split_rows:
                return []

            split_ids = [str(row["id"]) for row in split_rows]
            placeholders = ", ".join("?" for _ in split_ids)
            progress_rows = conn.execute(
                f"""
                SELECT assignment.split_id,
                       assignment.assignee,
                       COUNT(*) AS assigned_count,
                       SUM(CASE WHEN EXISTS (
                           SELECT 1
                           FROM annotations annotation
                           WHERE annotation.issue_id = assignment.issue_id
                             AND annotation.model_run_id = split.model_run_id
                             AND annotation.author = assignment.assignee
                             AND (
                               (split.mode = 'blind' AND annotation.work_split_id = assignment.split_id)
                               OR (split.mode <> 'blind' AND annotation.work_split_id = '')
                             )
                       ) THEN 1 ELSE 0 END) AS completed_count
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                WHERE assignment.split_id IN ({placeholders})
                GROUP BY assignment.split_id, assignment.assignee
                ORDER BY assignment.split_id, assignment.assignee
                """,
                split_ids,
            ).fetchall()
            change_rows = conn.execute(
                f"""
                SELECT split_id, COUNT(*) AS change_count
                FROM review_work_assignment_changes
                WHERE split_id IN ({placeholders})
                GROUP BY split_id
                """,
                split_ids,
            ).fetchall()
            historical_progress: dict[str, list[dict[str, Any]]] = {}
            for split in split_rows:
                if int(split["current_assignment_count"] or 0) > 0:
                    continue
                split_id = str(split["id"])
                snapshot_members = self._work_split_snapshot_members(
                    split["assignees_json"]
                )
                for member in snapshot_members:
                    issue_ids = list(
                        dict.fromkeys(
                            str(item["issue_id"])
                            for item in member.get("items") or []
                            if str(item.get("issue_id") or "").strip()
                        )
                    )
                    completed_ids: set[str] = set()
                    for offset in range(0, len(issue_ids), 500):
                        batch = issue_ids[offset : offset + 500]
                        if not batch:
                            continue
                        batch_placeholders = ", ".join("?" for _ in batch)
                        work_split_clause = (
                            "annotation.work_split_id = ?"
                            if str(split["mode"] or "") == "blind"
                            else "annotation.work_split_id = ''"
                        )
                        query_parameters: list[Any] = [
                            str(split["model_run_id"] or ""),
                            str(member["name"]),
                        ]
                        if str(split["mode"] or "") == "blind":
                            query_parameters.append(split_id)
                        query_parameters.extend(batch)
                        rows = conn.execute(
                            f"""
                            SELECT DISTINCT annotation.issue_id
                            FROM annotations annotation
                            WHERE annotation.model_run_id = ?
                              AND annotation.author = ?
                              AND {work_split_clause}
                              AND annotation.issue_id IN ({batch_placeholders})
                            """,
                            query_parameters,
                        ).fetchall()
                        completed_ids.update(str(item["issue_id"]) for item in rows)
                    historical_progress.setdefault(split_id, []).append(
                        {
                            "username": str(member["name"]),
                            "assigned_count": len(issue_ids),
                            "completed_count": len(completed_ids),
                        }
                    )

        progress_by_split: dict[str, list[dict[str, Any]]] = {}
        for row in progress_rows:
            split_id = str(row["split_id"])
            progress_by_split.setdefault(split_id, []).append(
                {
                    "username": str(row["assignee"] or ""),
                    "assigned_count": int(row["assigned_count"] or 0),
                    "completed_count": int(row["completed_count"] or 0),
                }
            )
        changes_by_split = {
            str(row["split_id"]): int(row["change_count"] or 0)
            for row in change_rows
        }
        result: list[dict[str, Any]] = []
        for row in split_rows:
            split_id = str(row["id"])
            snapshot_members = self._work_split_snapshot_members(row["assignees_json"])
            snapshot_by_name = {
                str(item["name"]): item for item in snapshot_members
            }
            current_members = progress_by_split.get(split_id, [])
            if not current_members:
                current_members = historical_progress.get(split_id, [])
            current_by_name = {item["username"]: item for item in current_members}
            member_names = [item["name"] for item in snapshot_members]
            member_names.extend(
                item["username"]
                for item in current_members
                if item["username"] not in member_names
            )
            members: list[dict[str, Any]] = []
            for name in member_names:
                current = current_by_name.get(name, {})
                snapshot = snapshot_by_name.get(name, {})
                assigned_count = int(
                    current.get("assigned_count")
                    or snapshot.get("count")
                    or 0
                )
                completed_count = int(current.get("completed_count") or 0)
                members.append(
                    {
                        "username": name,
                        "assigned_count": assigned_count,
                        "completed_count": completed_count,
                        "pending_count": max(0, assigned_count - completed_count),
                        "requested_count": snapshot.get("requested_count"),
                        "completion_ratio": (
                            round(completed_count / assigned_count, 4)
                            if assigned_count
                            else 0.0
                        ),
                    }
                )
            current_assignment_count = int(row["current_assignment_count"] or 0)
            current_issue_count = int(row["current_issue_count"] or 0)
            assignment_count = int(row["assignment_count"] or 0) or current_assignment_count
            total_count = int(row["total_count"] or 0) or current_issue_count
            completed_count = sum(item["completed_count"] for item in members)
            result.append(
                {
                    "split_id": split_id,
                    "created_by": str(row["created_by"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "seed": row["seed"],
                    "total_count": total_count,
                    "assignment_count": assignment_count,
                    "mode": str(row["mode"] or "single"),
                    "reviewers_per_issue": int(row["reviewers_per_issue"] or 1),
                    "model_run_id": str(row["model_run_id"] or ""),
                    "overlap_ratio": float(row["overlap_ratio"] or 0),
                    "filter_snapshot": _json_load(row["filter_json"], {}),
                    "members": members,
                    "completed_count": completed_count,
                    "pending_count": max(0, assignment_count - completed_count),
                    "completion_ratio": (
                        round(completed_count / assignment_count, 4)
                        if assignment_count
                        else 0.0
                    ),
                    "change_count": changes_by_split.get(split_id, 0),
                    "is_current": current_assignment_count > 0,
                }
            )
        return result

    def get_review_work_split(
        self,
        split_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        assignee: str = "",
        status: str = "all",
        query: str = "",
    ) -> dict[str, Any] | None:
        """Return one split and a paginated task/progress detail."""

        normalized_split_id = str(split_id or "").strip()
        if not normalized_split_id:
            return None
        normalized_status = str(status or "all").strip().lower()
        if normalized_status not in {"all", "completed", "pending"}:
            raise ValueError("任务状态筛选不合法。")
        safe_page = max(1, int(page or 1))
        safe_page_size = max(10, min(int(page_size or 50), 100))
        normalized_assignee = str(assignee or "").strip().lower()
        normalized_query = str(query or "").strip()[:128]
        submitted_condition = """
            EXISTS (
                SELECT 1
                FROM annotations annotation
                WHERE annotation.issue_id = assignment.issue_id
                  AND annotation.model_run_id = split.model_run_id
                  AND annotation.author = assignment.assignee
                  AND (
                    (split.mode = 'blind' AND annotation.work_split_id = assignment.split_id)
                    OR (split.mode <> 'blind' AND annotation.work_split_id = '')
                  )
            )
        """
        conditions = ["assignment.split_id = ?"]
        parameters: list[Any] = [normalized_split_id]
        if normalized_assignee:
            conditions.append("assignment.assignee = ?")
            parameters.append(normalized_assignee)
        if normalized_query:
            like = f"%{normalized_query}%"
            conditions.append("(assignment.issue_id LIKE ? OR issue.title LIKE ? OR issue.scenario LIKE ?)")
            parameters.extend([like, like, like])
        if normalized_status == "completed":
            conditions.append(submitted_condition)
        elif normalized_status == "pending":
            conditions.append(f"NOT ({submitted_condition})")
        where = " AND ".join(conditions)
        with self.connect() as conn:
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?",
                (normalized_split_id,),
            ).fetchone()
            if split is None:
                return None
            from_sql = """
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                JOIN issues issue ON issue.issue_id = assignment.issue_id
            """
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count {from_sql} WHERE {where}",
                parameters,
            ).fetchone()
            offset = (safe_page - 1) * safe_page_size
            item_rows = conn.execute(
                f"""
                SELECT assignment.issue_id,
                       assignment.assignee,
                       assignment.assignment_kind,
                       assignment.ordinal,
                       assignment.assigned_by,
                       assignment.assigned_at,
                       issue.title,
                       issue.scenario,
                       issue.gt_label,
                       issue.baseline_scope,
                       CASE WHEN {submitted_condition} THEN 1 ELSE 0 END AS submitted,
                       (
                           SELECT annotation.created_at
                           FROM annotations annotation
                           WHERE annotation.issue_id = assignment.issue_id
                             AND annotation.model_run_id = split.model_run_id
                             AND annotation.author = assignment.assignee
                             AND (
                               (split.mode = 'blind' AND annotation.work_split_id = assignment.split_id)
                               OR (split.mode <> 'blind' AND annotation.work_split_id = '')
                             )
                           ORDER BY annotation.id DESC
                           LIMIT 1
                       ) AS submitted_at,
                       (
                           SELECT annotation.review_status
                           FROM annotations annotation
                           WHERE annotation.issue_id = assignment.issue_id
                             AND annotation.model_run_id = split.model_run_id
                             AND annotation.author = assignment.assignee
                             AND (
                               (split.mode = 'blind' AND annotation.work_split_id = assignment.split_id)
                               OR (split.mode <> 'blind' AND annotation.work_split_id = '')
                             )
                           ORDER BY annotation.id DESC
                           LIMIT 1
                       ) AS review_status
                {from_sql}
                WHERE {where}
                ORDER BY assignment.assignee ASC, assignment.ordinal ASC, assignment.issue_id ASC
                LIMIT ? OFFSET ?
                """,
                (*parameters, safe_page_size, offset),
            ).fetchall()
            change_rows = conn.execute(
                """
                SELECT id, issue_id, from_assignee, to_assignee, changed_by, changed_at
                FROM review_work_assignment_changes
                WHERE split_id = ?
                ORDER BY changed_at DESC, id DESC
                LIMIT 100
                """,
                (normalized_split_id,),
            ).fetchall()
        total = int(total_row["count"] or 0)
        items = [
            {
                "issue_id": str(row["issue_id"]),
                "assignee": str(row["assignee"]),
                "assignment_kind": str(row["assignment_kind"] or "base"),
                "ordinal": int(row["ordinal"] or 1),
                "assigned_by": str(row["assigned_by"] or ""),
                "assigned_at": str(row["assigned_at"] or ""),
                "title": str(row["title"] or ""),
                "scenario": str(row["scenario"] or ""),
                "gt_label": str(row["gt_label"] or ""),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "submitted": bool(row["submitted"]),
                "submitted_at": str(row["submitted_at"] or ""),
                "review_status": str(row["review_status"] or ""),
            }
            for row in item_rows
        ]
        changes = [
            {
                "id": int(row["id"]),
                "issue_id": str(row["issue_id"]),
                "from_assignee": str(row["from_assignee"]),
                "to_assignee": str(row["to_assignee"]),
                "changed_by": str(row["changed_by"]),
                "changed_at": str(row["changed_at"]),
            }
            for row in change_rows
        ]
        snapshot_members = self._work_split_snapshot_members(split["assignees_json"])
        current_assignment_count = 0
        current_issue_count = 0
        with self.connect() as conn:
            current = conn.execute(
                """
                SELECT COUNT(*) AS assignment_count, COUNT(DISTINCT issue_id) AS issue_count
                FROM review_work_assignments
                WHERE split_id = ?
                """,
                (normalized_split_id,),
            ).fetchone()
            if current:
                current_assignment_count = int(current["assignment_count"] or 0)
                current_issue_count = int(current["issue_count"] or 0)
        if not item_rows and current_assignment_count == 0 and snapshot_members:
            snapshot_issue_ids = list(
                dict.fromkeys(
                    str(assignment["issue_id"])
                    for member in snapshot_members
                    for assignment in member.get("items") or []
                    if str(assignment.get("issue_id") or "").strip()
                )
            )
            issue_by_id: dict[str, dict[str, Any]] = {}
            annotation_by_key: dict[tuple[str, str], dict[str, Any]] = {}
            with self.connect() as conn:
                for offset in range(0, len(snapshot_issue_ids), 500):
                    batch = snapshot_issue_ids[offset : offset + 500]
                    if not batch:
                        continue
                    batch_placeholders = ", ".join("?" for _ in batch)
                    issue_rows = conn.execute(
                        f"""
                        SELECT issue_id, title, scenario, gt_label, baseline_scope
                        FROM issues
                        WHERE issue_id IN ({batch_placeholders})
                        """,
                        batch,
                    ).fetchall()
                    for row in issue_rows:
                        issue_by_id[str(row["issue_id"])] = {
                            "title": str(row["title"] or ""),
                            "scenario": str(row["scenario"] or ""),
                            "gt_label": str(row["gt_label"] or ""),
                            "baseline_scope": str(row["baseline_scope"] or ""),
                        }
                    annotation_work_split = (
                        "annotation.work_split_id = ?"
                        if str(split["mode"] or "") == "blind"
                        else "annotation.work_split_id = ''"
                    )
                    annotation_parameters: list[Any] = [
                        str(split["model_run_id"] or "")
                    ]
                    if str(split["mode"] or "") == "blind":
                        annotation_parameters.append(normalized_split_id)
                    annotation_parameters.extend(batch)
                    annotation_rows = conn.execute(
                        f"""
                        SELECT annotation.issue_id, annotation.author, annotation.id,
                               annotation.created_at, annotation.review_status
                        FROM annotations annotation
                        WHERE annotation.model_run_id = ?
                          AND {annotation_work_split}
                          AND annotation.issue_id IN ({batch_placeholders})
                        ORDER BY annotation.id DESC
                        """,
                        annotation_parameters,
                    ).fetchall()
                    for row in annotation_rows:
                        key = (str(row["issue_id"]), str(row["author"] or ""))
                        annotation_by_key.setdefault(
                            key,
                            {
                                "created_at": str(row["created_at"] or ""),
                                "review_status": str(row["review_status"] or ""),
                            },
                        )
            snapshot_rows: list[dict[str, Any]] = []
            for member in snapshot_members:
                member_name = str(member["name"])
                for assignment in member.get("items") or []:
                    assignment_issue_id = str(assignment["issue_id"])
                    issue = issue_by_id.get(assignment_issue_id, {})
                    annotation = annotation_by_key.get(
                        (assignment_issue_id, member_name)
                    )
                    row = {
                        "issue_id": assignment_issue_id,
                        "assignee": member_name,
                        "assignment_kind": str(
                            assignment.get("assignment_kind") or "base"
                        ),
                        "ordinal": int(assignment.get("ordinal") or 1),
                        "assigned_by": str(split["created_by"] or ""),
                        "assigned_at": str(split["created_at"] or ""),
                        "title": str(issue.get("title") or ""),
                        "scenario": str(issue.get("scenario") or ""),
                        "gt_label": str(issue.get("gt_label") or ""),
                        "baseline_scope": str(issue.get("baseline_scope") or ""),
                        "submitted": bool(annotation),
                        "submitted_at": str((annotation or {}).get("created_at") or ""),
                        "review_status": str((annotation or {}).get("review_status") or ""),
                    }
                    if normalized_assignee and member_name.lower() != normalized_assignee:
                        continue
                    if normalized_query:
                        haystack = " ".join(
                            [assignment_issue_id, row["title"], row["scenario"]]
                        ).casefold()
                        if normalized_query.casefold() not in haystack:
                            continue
                    if normalized_status == "completed" and not row["submitted"]:
                        continue
                    if normalized_status == "pending" and row["submitted"]:
                        continue
                    snapshot_rows.append(row)
            snapshot_rows.sort(
                key=lambda item: (
                    item["assignee"],
                    item["ordinal"],
                    item["issue_id"],
                )
            )
            total = len(snapshot_rows)
            items = snapshot_rows[offset : offset + safe_page_size]
        summary = next(
            (
                item
                for item in self.list_review_work_splits(limit=100)
                if item["split_id"] == normalized_split_id
            ),
            None,
        )
        if summary is None:
            summary = {
                "members": [
                    {
                        "username": str(item["name"]),
                        "assigned_count": int(item.get("count") or 0),
                        "completed_count": 0,
                        "pending_count": int(item.get("count") or 0),
                        "requested_count": item.get("requested_count"),
                        "completion_ratio": 0.0,
                    }
                    for item in snapshot_members
                ],
                "completed_count": 0,
                "pending_count": int(split["assignment_count"] or 0),
                "completion_ratio": 0.0,
                "change_count": len(changes),
                "is_current": current_assignment_count > 0,
            }
        return {
            "split_id": normalized_split_id,
            "created_by": str(split["created_by"] or ""),
            "created_at": str(split["created_at"] or ""),
            "seed": split["seed"],
            "total_count": int(split["total_count"] or 0) or current_issue_count,
            "assignment_count": int(split["assignment_count"] or 0) or current_assignment_count,
            "mode": str(split["mode"] or "single"),
            "reviewers_per_issue": int(split["reviewers_per_issue"] or 1),
            "model_run_id": str(split["model_run_id"] or ""),
            "overlap_ratio": float(split["overlap_ratio"] or 0),
            "filter_snapshot": _json_load(split["filter_json"], {}),
            "members": summary.get("members", []),
            "completed_count": int(summary.get("completed_count") or 0),
            "pending_count": int(summary.get("pending_count") or 0),
            "completion_ratio": float(summary.get("completion_ratio") or 0),
            "change_count": int(summary.get("change_count") or len(changes)),
            "is_current": bool(summary.get("is_current")),
            "changes": changes,
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "page_count": max(1, (total + safe_page_size - 1) // safe_page_size),
            "filters": {
                "assignee": normalized_assignee,
                "status": normalized_status,
                "q": normalized_query,
            },
        }

    def reassign_review_work_assignment(
        self,
        *,
        split_id: str,
        issue_id: str,
        assignee: str,
        changed_by: str,
    ) -> dict[str, Any]:
        """Transfer one unfinished task and retain a change audit row."""

        normalized_split_id = str(split_id or "").strip()
        normalized_issue_id = str(issue_id or "").strip()
        normalized_assignee = str(assignee or "").strip().lower()
        actor = str(changed_by or "").strip()
        if not normalized_split_id or not normalized_issue_id:
            raise ValueError("任务分配标识不能为空。")
        if not normalized_assignee:
            raise ValueError("新负责人不能为空。")
        if not actor:
            raise ValueError("任务调整人不能为空。")
        with self._write_lock, self.connect() as conn:
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?",
                (normalized_split_id,),
            ).fetchone()
            if split is None:
                raise ValueError("分配批次不存在。")
            current = conn.execute(
                """
                SELECT assignee, assignment_kind, ordinal
                FROM review_work_assignments
                WHERE split_id = ? AND issue_id = ?
                ORDER BY ordinal ASC, assignee ASC
                LIMIT 1
                """,
                (normalized_split_id, normalized_issue_id),
            ).fetchone()
            if current is None:
                raise ValueError("当前分配批次中找不到这条任务；它可能已被后续分配覆盖。")
            old_assignee = str(current["assignee"] or "").strip().lower()
            if old_assignee == normalized_assignee:
                return {
                    "split_id": normalized_split_id,
                    "issue_id": normalized_issue_id,
                    "changed": False,
                }
            duplicate = conn.execute(
                """
                SELECT 1 FROM review_work_assignments
                WHERE split_id = ? AND issue_id = ? AND assignee = ?
                LIMIT 1
                """,
                (normalized_split_id, normalized_issue_id, normalized_assignee),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("该 Issue 已经分配给目标负责人。")
            submitted = conn.execute(
                """
                SELECT annotation.id
                FROM annotations annotation
                WHERE annotation.issue_id = ?
                  AND annotation.model_run_id = ?
                  AND annotation.author = ?
                  AND (
                    ( ? = 'blind' AND annotation.work_split_id = ? )
                    OR ( ? <> 'blind' AND annotation.work_split_id = '' )
                  )
                ORDER BY annotation.id DESC
                LIMIT 1
                """,
                (
                    normalized_issue_id,
                    str(split["model_run_id"] or ""),
                    old_assignee,
                    str(split["mode"] or "single"),
                    normalized_split_id,
                    str(split["mode"] or "single"),
                ),
            ).fetchone()
            if submitted is not None:
                raise ValueError("已提交的 Review 不能直接转派；请保留原记录后再新建分配。")
            next_ordinal = conn.execute(
                """
                SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                FROM review_work_assignments
                WHERE split_id = ? AND assignee = ?
                """,
                (normalized_split_id, normalized_assignee),
            ).fetchone()
            now = utc_now()
            conn.execute(
                """
                UPDATE review_work_assignments
                SET assignee = ?, ordinal = ?, assigned_by = ?, assigned_at = ?
                WHERE split_id = ? AND issue_id = ? AND assignee = ?
                """,
                (
                    normalized_assignee,
                    int(next_ordinal["ordinal"] or 1),
                    actor,
                    now,
                    normalized_split_id,
                    normalized_issue_id,
                    old_assignee,
                ),
            )
            conn.execute(
                """
                INSERT INTO review_work_assignment_changes (
                    split_id, issue_id, from_assignee, to_assignee, changed_by, changed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_split_id,
                    normalized_issue_id,
                    old_assignee,
                    normalized_assignee,
                    actor,
                    now,
                ),
            )
            rows = conn.execute(
                """
                SELECT assignee, assignment_kind, ordinal, issue_id
                FROM review_work_assignments
                WHERE split_id = ?
                ORDER BY assignee ASC, ordinal ASC, issue_id ASC
                """,
                (normalized_split_id,),
            ).fetchall()
            previous = {
                str(item["name"]): item
                for item in self._work_split_snapshot_members(split["assignees_json"])
            }
            groups: dict[str, dict[str, Any]] = {}
            order: list[str] = []
            for row in rows:
                name = str(row["assignee"] or "").strip()
                if not name:
                    continue
                if name not in groups:
                    old = previous.get(name, {})
                    groups[name] = {
                        "name": name,
                        "count": 0,
                        "requested_count": old.get("requested_count"),
                        "mode": old.get("mode") or (
                            "blind" if str(split["mode"] or "") == "blind" else "share"
                        ),
                        "issue_ids": [],
                        "items": [],
                    }
                    order.append(name)
                group = groups[name]
                item = {
                    "issue_id": str(row["issue_id"]),
                    "assignment_kind": str(row["assignment_kind"] or "base"),
                    "ordinal": int(row["ordinal"] or 1),
                }
                group["items"].append(item)
                group["issue_ids"].append(item["issue_id"])
                group["count"] += 1
            snapshot = [groups[name] for name in order]
            conn.execute(
                """
                UPDATE issue_work_splits
                SET assignees_json = ?, total_count = ?, assignment_count = ?
                WHERE id = ?
                """,
                (
                    _json(snapshot),
                    len({str(row["issue_id"]) for row in rows}),
                    len(rows),
                    normalized_split_id,
                ),
            )
        return {
            "split_id": normalized_split_id,
            "issue_id": normalized_issue_id,
            "from_assignee": old_assignee,
            "to_assignee": normalized_assignee,
            "changed": True,
        }

    def review_assignment_context(
        self,
        issue_id: str,
        *,
        model_run_id: str = "",
        username: str = "",
        work_split_id: str = "",
    ) -> dict[str, Any] | None:
        """Return the current assignment snapshot for one Issue/Run."""

        with self.connect() as conn:
            normalized_split_id = str(work_split_id or "").strip()
            split_condition = "AND split.id = ?" if normalized_split_id else ""
            split_parameters: tuple[Any, ...] = (
                (str(issue_id or "").strip(), str(model_run_id or "").strip(), normalized_split_id)
                if normalized_split_id
                else (str(issue_id or "").strip(), str(model_run_id or "").strip())
            )
            split = conn.execute(
                f"""
                SELECT split.*
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                WHERE assignment.issue_id = ? AND split.model_run_id = ?
                  {split_condition}
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT 1
                """,
                split_parameters,
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
        reviewer_count = int(split["reviewers_per_issue"] or 1)
        return {
            "split_id": str(split["id"]),
            "mode": str(split["mode"] or "single"),
            "model_run_id": str(split["model_run_id"] or ""),
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": (
                float(split["overlap_ratio"] or 0)
                if reviewer_count > 1
                else 0.0
            ),
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
        work_split_id: str = "",
        issue_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return one row per current blind assignment member for aggregation."""

        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            return []
        scope_clause, scope_params = self._scope_in_sql(scopes)
        selected_issue_ids = tuple(
            dict.fromkeys(
                str(issue_id or "").strip()
                for issue_id in (issue_ids or ())
                if str(issue_id or "").strip()
            )
        )
        issue_clause = ""
        selected_run_id = str(model_run_id or "").strip()
        selected_work_split_id = str(work_split_id or "").strip()
        if selected_work_split_id:
            split_filter = "split.id = ?"
            split_params = [selected_work_split_id]
            if selected_run_id:
                split_filter += " AND split.model_run_id = ?"
                split_params.append(selected_run_id)
            prediction_run_id = selected_run_id
        elif selected_run_id:
            split_filter = """
                split.model_run_id = ?
                AND split.id = (
                    SELECT latest_split.id
                    FROM issue_work_splits latest_split
                    JOIN review_work_assignments latest_assignment
                      ON latest_assignment.split_id = latest_split.id
                    WHERE latest_assignment.issue_id = assignment.issue_id
                      AND latest_split.model_run_id = ?
                      AND latest_split.mode = 'blind'
                    ORDER BY latest_split.created_at DESC, latest_split.id DESC
                    LIMIT 1
                )
            """
            split_params = [selected_run_id, selected_run_id]
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
        mode_filter = "TRUE" if selected_work_split_id else "split.mode = 'blind'"
        query = f"""
            SELECT i.issue_id, i.title, i.scenario, i.summary, i.gt_label,
                   i.baseline_scope, assignment.split_id, assignment.assignee,
                   split.mode AS split_mode,
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
                  AND (
                    (split.mode = 'blind' AND candidate.work_split_id = assignment.split_id)
                    OR (split.mode <> 'blind' AND candidate.work_split_id = '')
                  )
                  AND candidate.author = assignment.assignee
                ORDER BY candidate.id DESC LIMIT 1
            )
            LEFT JOIN model_predictions prediction
              ON prediction.issue_id = i.issue_id
             AND prediction.model_run_id = ?
            WHERE {mode_filter} AND {split_filter}
              AND {scope_clause}
              {{issue_clause}}
            ORDER BY i.issue_id ASC, assignment.assignee ASC
        """
        with self.connect() as conn:
            rows: list[Any] = []
            if selected_issue_ids:
                for offset in range(0, len(selected_issue_ids), 400):
                    batch = selected_issue_ids[offset : offset + 400]
                    issue_clause = (
                        "AND assignment.issue_id IN "
                        f"({', '.join('?' for _ in batch)})"
                    )
                    chunk_query = query.replace("{issue_clause}", issue_clause)
                    rows.extend(
                        conn.execute(
                            chunk_query,
                            (prediction_run_id, *split_params, *scope_params, *batch),
                        ).fetchall()
                    )
            else:
                rows = conn.execute(
                    query.replace("{issue_clause}", ""),
                    (prediction_run_id, *split_params, *scope_params),
                ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            annotation = None
            if row["annotation_id"] is not None:
                annotation = {
                    "id": int(row["annotation_id"]),
                    "model_run_id": str(row["split_model_run_id"] or ""),
                    "work_split_id": (
                        str(row["split_id"])
                        if str(row["split_mode"] or "") == "blind"
                        else ""
                    ),
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
                    "split_model_run_id": str(row["split_model_run_id"] or ""),
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
        overlap_ratio: float | None = None,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        """Persist a work-split batch and overwrite assignments for its issues."""

        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("均分操作人不能为空。")
        if not assignments:
            raise ValueError("分配结果为空。")
        try:
            reviewer_count = int(reviewers_per_issue or 1)
        except (TypeError, ValueError) as exc:
            raise ValueError("每个 Issue 的复核人数必须是整数。") from exc
        if reviewer_count < 1:
            raise ValueError("每个 Issue 的复核人数至少为 1。")
        resolved_overlap_ratio = normalize_overlap_ratio(
            overlap_ratio,
            reviewers_per_issue=reviewer_count,
        )
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
                    overlap_ratio, assignment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    split_id,
                    actor,
                    now,
                    seed,
                    len({row[0] for row in rows}),
                    json.dumps(filter_snapshot or {}, ensure_ascii=False),
                    json.dumps(assignments, ensure_ascii=False),
                    "blind" if reviewer_count > 1 else "single",
                    reviewer_count,
                    str(model_run_id or "").strip(),
                    resolved_overlap_ratio,
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
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": resolved_overlap_ratio,
            "assignments": assignments,
        }
