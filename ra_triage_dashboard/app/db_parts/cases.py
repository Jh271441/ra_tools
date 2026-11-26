from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter
from typing import Any, Iterable, Iterator, Sequence

from ..work_split import normalize_overlap_ratio
from ..gt_observations import TRAIL_GT_RAW_VALUES
from .task_lifecycle import task_lifecycle_where, task_reviewable
from .assignment_rules import (
    ASSIGNMENT_SUBMITTED_SQL,
    MODEL_ASSIGNMENT_SCOPE_SQL,
    MODEL_SUBMISSION_SQL,
    legacy_batch_source,
    assignment_snapshot_members,
)
from .model_reviews import MODEL_REVIEW_STATUSES, MODEL_REVIEW_PUBLIC_ID_OFFSET
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


from .work_splits import DatabaseWorkSplitsMixin


class DatabaseCasesMixin(DatabaseWorkSplitsMixin):
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
        strict_run: bool = False,
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
                LEFT JOIN review_records a
                  ON a.issue_id = wa.issue_id
                 AND a.model_run_id = ws.model_run_id
                 AND a.author = wa.assignee
                 AND (
                      (ws.purpose = 'model_review' AND a.review_domain = 'model_review'
                       AND a.campaign_id = ws.id AND a.reference_id = ws.reference_id)
                      OR (COALESCE(ws.purpose, '') <> 'model_review'
                          AND ws.mode = 'blind' AND a.work_split_id = ws.id)
                      OR (COALESCE(ws.purpose, '') <> 'model_review'
                          AND ws.mode != 'blind' AND a.work_split_id = '')
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
        if strict_run and not run_id:
            ordinary_annotation = "(SELECT NULL WHERE FALSE)"
            ordinary_params = []
        elif run_id and strict_run:
            ordinary_annotation = """
                (
                    SELECT a.id FROM review_records a
                    WHERE a.issue_id = i.issue_id
                      AND a.model_run_id = ?
                      AND a.work_split_id = ''
                    ORDER BY a.id DESC LIMIT 1
                )
            """
            ordinary_params = [run_id]
        elif run_id:
            ordinary_annotation = """
                COALESCE(
                    (
                        SELECT a.id FROM review_records a
                        WHERE a.issue_id = i.issue_id
                          AND a.model_run_id = ?
                          AND a.work_split_id = ''
                        ORDER BY a.id DESC LIMIT 1
                    ),
                    (
                        SELECT a.id FROM review_records a
                        WHERE a.issue_id = i.issue_id
                          AND a.model_run_id = ''
                          AND a.work_split_id = ''
                        ORDER BY a.id DESC LIMIT 1
                    ),
                    (
                        SELECT a.id FROM review_records a
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
                    SELECT a.id FROM review_records a
                    WHERE a.issue_id = i.issue_id
                      AND a.work_split_id = ''
                    ORDER BY a.id DESC LIMIT 1
                )
            """
            ordinary_params = []
        selected_annotation_id = f"""
            CASE
                WHEN {assignment_exists} THEN {assignment_annotation}
                ELSE {ordinary_annotation}
            END
        """
        if self.backend == "postgresql":
            # Joining the UNION-backed review_records view on a computed id makes
            # PostgreSQL materialize every Review row and re-evaluate the correlated
            # selector once per materialized candidate.  A page of 20 Issues then
            # performs tens of thousands of probes.  LATERAL evaluates the selector
            # once per Issue and fetches at most the chosen Review row.
            join = f"""
                LEFT JOIN LATERAL (
                    SELECT selected_ann.*
                    FROM review_records selected_ann
                    WHERE selected_ann.id = {selected_annotation_id}
                    LIMIT 1
                ) ann ON TRUE
            """
        else:
            # SQLite has no LATERAL support; retain the equivalent scalar-id join.
            join = f"""
                LEFT JOIN review_records ann
                  ON ann.id = {selected_annotation_id}
            """
        if strict_run and not run_id:
            return "LEFT JOIN review_records ann ON 1 = 0", []
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
        model_review_status: str = "",
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
        include_projection: bool = True,
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
        gt_requested = _multi_values(gt_label)
        if gt_requested:
            if any(value not in (*LABELS, *TRAIL_GT_RAW_VALUES) for value in gt_requested):
                raise ValueError("unsupported gt_label")
            canonical = tuple(value for value in gt_requested if value in LABELS)
            raw_values = tuple(value for value in gt_requested if value in TRAIL_GT_RAW_VALUES)
            gt_conditions = []
            if canonical:
                gt_conditions.append(f"i.gt_label IN ({', '.join('?' for _ in canonical)})")
                params.extend(canonical)
            if raw_values:
                gt_conditions.append(f"({self._gt_raw_label_sql()}) IN ({', '.join('?' for _ in raw_values)})")
                params.extend(raw_values)
            where.append('(' + ' OR '.join(gt_conditions) + ')')
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
        model_review_statuses = _multi_values(model_review_status)
        if any(value not in MODEL_REVIEW_STATUSES for value in model_review_statuses):
            raise ValueError("unsupported model_review_status")
        if model_review_statuses:
            # Match the displayed progress: no current-Run record is Not started;
            # persisted drafts/blocked records are Needs review, not unsubmitted.
            from ..review_workflow import model_review_progress_sql
            progress, progress_params = model_review_progress_sql(model_run_id)
            where.append(f"({progress}) IN ({', '.join('?' for _ in model_review_statuses)})")
            params.extend(progress_params)
            params.extend("in_progress" if value == "blocked_by_label" else value for value in model_review_statuses)
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
            comment_run_clause = " AND (rc.model_run_id = ? OR rc.discussion_channel = 'case')" if model_run_id else ""
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
                    f"({', '.join('?' for _ in named)})"
                    + (" AND ws_named.id = ?" if work_split_id else "") + ")"
                )
                params.extend((model_run_id, *named))
                if work_split_id:
                    params.append(str(work_split_id).strip())
            where.append(f"({' OR '.join(assignee_clauses)})")
        normalized_work_split_id = str(work_split_id or "").strip()
        if normalized_work_split_id:
            if model_run_id:
                where.append(
                    "EXISTS (SELECT 1 FROM review_work_assignments wa_split "
                    "JOIN issue_work_splits ws_split ON ws_split.id = wa_split.split_id "
                    "WHERE wa_split.issue_id = i.issue_id AND ws_split.id = ? "
                    "AND COALESCE(NULLIF(ws_split.evaluation_run_id, ''), ws_split.model_run_id, '') = ?)"
                )
                params.extend((normalized_work_split_id, model_run_id))
            else:
                where.append(
                    "EXISTS (SELECT 1 FROM review_work_assignments wa_split "
                    "JOIN issue_work_splits ws_split ON ws_split.id = wa_split.split_id "
                    "WHERE wa_split.issue_id = i.issue_id AND ws_split.id = ? "
                    "AND COALESCE(NULLIF(ws_split.evaluation_run_id, ''), ws_split.model_run_id, '') = '')"
                )
                params.append(normalized_work_split_id)
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
        common = "FROM issues i"
        model_args: list[Any] = []
        # Counts/ID-only reads need a projection only when a generated WHERE
        # predicate uses it. Keep the same predicates and binds as the page;
        # an unfiltered total must not resolve a Review for every Issue.
        if include_projection or "ann." in condition:
            annotation_join, annotation_params = self._gallery_annotation_join(
                model_run_id,
                projection_authors=authors or tuple(named),
                preferred_annotation_author=preferred_annotation_author,
                work_split_id=normalized_work_split_id,
                strict_run=bool(scopes and self.legacy_business_read_mode(scopes) == "canonical"),
            )
            common += f"\n{annotation_join}"
            model_args.extend(annotation_params)
        if include_projection or "mp." in condition:
            common += """
                LEFT JOIN model_predictions mp
                  ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
            """
            model_args.append(model_run_id)
        # The correlated annotation lookup appears before the prediction JOIN
        # in the SQL, so its bind values must precede the prediction Run id.
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
        model_review_status: str = "",
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
        filters = dict(
            baseline_scope=baseline_scope,
            baseline_scopes=baseline_scopes,
            search=search,
            gt_label=gt_label,
            model_label=model_label,
            annotation_label=annotation_label,
            annotation_author=annotation_author,
            model_review_status=model_review_status,
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
        condition, params, model_args, common = self._case_list_filters(**filters)
        count_condition, count_params, count_args, count_common = self._case_list_filters(
            **filters, include_projection=False
        )
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(DISTINCT i.issue_id) {count_common} {count_condition}",
                (*count_args, *count_params),
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
                SELECT i.*, {self._gt_raw_label_sql()} AS gt_raw_label, ann.id AS annotation_id,
                       ann.label AS annotation_label, ann.review_status AS annotation_review_status,
                       ann.is_excluded AS annotation_is_excluded,
                       ann.tags_json AS annotation_tags_json,
                       ann.missing_evidence_json AS annotation_missing_evidence_json,
                       ann.note AS annotation_note, ann.author AS annotation_author,
                       ann.author_source AS annotation_author_source,
                       ann.author_verified AS annotation_author_verified,
                       ann.created_at AS annotation_created_at,
                       ann.model_run_id AS annotation_model_run_id,
                       ann.review_domain AS annotation_review_domain,
                       ann.model_review_status AS annotation_model_review_status,
                       ann.campaign_id AS annotation_campaign_id,
                       ann.reference_id AS annotation_reference_id,
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
        model_review_status: str = "",
        comparison_status: str = "all",
        failure_only: bool = False,
        missing_evidence: str = "",
        issue_ids: list[str] | None = None,
        work_assignee: str = "",
        work_split_id: str = "",
        comment_state: str = "all",
        preferred_annotation_author: str = "",
        is_excluded: bool | None = None,
        limit: int | None = 5000,
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
            model_review_status=model_review_status,
            comparison_status=comparison_status,
            failure_only=failure_only,
            missing_evidence=missing_evidence,
            issue_ids=issue_ids,
            work_assignee=work_assignee,
            work_split_id=work_split_id,
            comment_state=comment_state,
            preferred_annotation_author=preferred_annotation_author,
            is_excluded=is_excluded,
            include_projection=False,
        )
        # Public callers retain the 5000 cap. Internal facet scans may request
        # the complete scope, matching the uncapped derived-filter iterator.
        limit = min(max(1, int(limit)), 5000) if limit is not None else None
        limit_sql = "LIMIT ?" if limit is not None else ""
        limit_args = [limit] if limit is not None else []
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT i.issue_id
                {common}
                {condition}
                ORDER BY i.issue_id ASC
                {limit_sql}
                """,
                (*model_args, *params, *limit_args),
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
        self, *, batch_size: int = 400, include_raw_gt: bool = False, **filters: Any
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield the complete Review candidate set in ordered bounded batches.

        Unlike the legacy convenience method above, this internal scan has no
        result cap. Keyset pagination keeps each SQL parameter set small and
        avoids loading the whole multi-baseline candidate set at once.
        """

        batch_size = min(max(1, int(batch_size)), 1000)
        raw_gt_sql = self._gt_raw_label_sql() if include_raw_gt else "''"
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
                    SELECT DISTINCT i.issue_id, i.baseline_scope, i.gt_label, {raw_gt_sql} AS gt_raw_label,
                           ann.id AS annotation_id,
                           ann.label AS annotation_label,
                           ann.tags_json AS annotation_tags_json,
                           ann.is_excluded AS annotation_is_excluded
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
                        "gt_raw_label": str(row["gt_raw_label"] or ""),
                        "annotation": {
                            "id": row["annotation_id"],
                            "label": str(row["annotation_label"] or ""),
                            "tags": _json_load(row["annotation_tags_json"], []),
                            "is_excluded": bool(row["annotation_is_excluded"]),
                        },
                    }
                    for row in rows
                ]
                last_issue_id = str(rows[-1]["issue_id"] or "")
                if len(rows) < batch_size:
                    break

    def get_case(self, issue_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            issue = conn.execute(
                f"SELECT i.*, {self._gt_raw_label_sql()} AS gt_raw_label FROM issues i WHERE i.issue_id = ?",
                (issue_id,),
            ).fetchone()
            if issue is None:
                return None
            annotations = conn.execute(
                "SELECT * FROM review_records WHERE issue_id = ? ORDER BY id DESC", (issue_id,)
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
                FROM review_record_attachments ra
                JOIN review_records ann ON ann.id = ra.annotation_id
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
        legacy_classes = {
            int(item["source_annotation_id"]): item
            for item in self.legacy_classifications(
                [str(issue["baseline_scope"] or "")]
            )
            if str(item.get("source_annotation_id") or "").isdigit()
            and int(item["source_annotation_id"]) in {int(item["id"]) for item in annotation_items}
        }
        for annotation in annotation_items:
            annotation["attachments"] = attachments_by_annotation.get(int(annotation["id"]), [])
            classification = legacy_classes.get(int(annotation["id"]))
            if classification:
                annotation["legacy_classification"] = str(classification.get("classification") or "")
                annotation["legacy_read_only"] = True
                annotation["legacy_history_label"] = "历史 Review（只读）"
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
        data["label_source_contexts"] = self.label_source_contexts(issue_id, data["label_state"])
        data["gt_snapshot"] = self.get_active_gt_snapshot(
            str(data.get("baseline_scope") or "")
        )
        policies = self.legacy_read_policies([str(data.get("baseline_scope") or "")])
        data["legacy_read_policy"] = policies[0] if policies else {"policy": "legacy", "epoch": 0}
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

    def get_media_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Resolve read-only media without admitting a registry member to Review.

        The version gallery includes published, non-target members that never
        had an ``issues`` row. Their indexed media remains viewable; labels,
        assignments and writable Case lookup still require the ordinary row.
        Do not invent a capture trip or timestamp from registry metadata.
        """
        issue = self.get_issue(issue_id)
        if issue is not None:
            return issue
        with self.connect() as conn:
            families = conn.execute(
                "SELECT DISTINCT d.release_family FROM version_dataset_items i "
                "JOIN version_datasets d ON d.id = i.dataset_id "
                "WHERE i.issue_id = ? AND i.state IN ('inferred', 'published') LIMIT 2",
                (issue_id,),
            ).fetchall()
        if not families:
            return None
        # A shared member has no unambiguous version layout on this unscoped URL.
        reference_scope = ("manual_sidecar_version_" + families[0]["release_family"]
                           if len(families) == 1 else "")
        return {"issue_id": issue_id, "baseline_scope": "", "gt_label": "",
                "reference_media": True, "reference_scope": reference_scope}

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
        issue_ids: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if not scopes:
            raise ValueError("baseline_scopes must not be empty")
        canonical_mode = self.legacy_business_read_mode(scopes) == "canonical"
        scope_clause, scope_params = self._scope_in_sql(scopes)
        where = [scope_clause, "ann.id IS NOT NULL"]
        if issue_ids:
            where.append("i.issue_id IN (" + ",".join("?" for _ in issue_ids) + ")")
            scope_params.extend(issue_ids)
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
            if canonical_mode and not model_run_id:
                annotation_join = "LEFT JOIN review_records ann ON 1 = 0"
                annotation_params = ()
            else:
                annotation_join = self._latest_annotation_join(
                    model_run_id,
                    include_unbound_fallback=not canonical_mode,
                    include_bound_history_fallback=not canonical_mode,
                )
                annotation_params = self._latest_annotation_join_params(
                    model_run_id,
                    include_unbound_fallback=not canonical_mode,
                    include_bound_history_fallback=not canonical_mode,
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
        issue_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes, baseline_scope=baseline_scope)
        if scopes:
            scope_clause, scope_params = self._scope_in_sql(scopes)
            base_where = f"WHERE {scope_clause}"
        else:
            # Legacy empty filter: count all issues (tests / unrestricted callers).
            scope_clause, scope_params = "1=1", []
            base_where = "WHERE 1=1"
        if issue_ids:
            scope_clause += " AND i.issue_id IN (" + ",".join("?" for _ in issue_ids) + ")"
            scope_params.extend(issue_ids)
            base_where = f"WHERE {scope_clause}"
        annotation_join, annotation_params = self._gallery_annotation_join(model_run_id)
        from ..review_workflow import model_review_progress_sql
        progress_sql, progress_params = model_review_progress_sql(model_run_id)
        prediction_join = ""
        prediction_sql = "NULL"
        failure_sql = "0"
        failure_params: list[Any] = []
        prediction_params: list[Any] = []
        if model_run_id:
            prediction_join = """
                LEFT JOIN model_predictions mp
                  ON mp.issue_id = i.issue_id AND mp.model_run_id = ?
            """
            prediction_sql = "mp.id"
            mismatch_sql, mismatch_params = model_prediction_mismatch_sql()
            failure_sql = f"CASE WHEN i.gt_label IN (?, ?, ?) AND {mismatch_sql} THEN 1 ELSE 0 END"
            failure_params = [*LABELS, *mismatch_params]
            prediction_params = [model_run_id]
        model_review_status_counts = {
            "pending": 0, "in_progress": 0, "completed": 0, "blocked_by_label": 0,
        }
        total = labelled = predictions = failures = reviewed_failures = 0
        with self.connect() as conn:
            # One Review projection supplies all overview counters. Separate
            # count queries previously repeated the same correlated lookup up
            # to five times for the entire dataset.
            status_rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS count, COUNT(annotation_id) AS labelled,
                       COUNT(prediction_id) AS predictions, SUM(is_failure) AS failures,
                       SUM(CASE WHEN is_failure = 1 AND is_reviewed = 1 THEN 1 ELSE 0 END) AS reviewed_failures
                FROM (
                    SELECT {progress_sql} AS status, ann.id AS annotation_id,
                           {prediction_sql} AS prediction_id, {failure_sql} AS is_failure,
                           CASE WHEN ann.review_domain = 'model_review'
                                 AND ann.model_review_status = 'completed' THEN 1 ELSE 0 END AS is_reviewed
                    FROM issues i
                    {annotation_join}
                    {prediction_join}
                    {base_where}
                ) progress GROUP BY status
                """,
                (*progress_params, *failure_params, *annotation_params, *prediction_params, *scope_params),
            ).fetchall()
            for row in status_rows:
                count = int(row["count"] or 0)
                model_review_status_counts[str(row["status"])] = count
                total += count
                labelled += int(row["labelled"] or 0)
                predictions += int(row["predictions"] or 0)
                failures += int(row["failures"] or 0)
                reviewed_failures += int(row["reviewed_failures"] or 0)
            running = conn.execute(
                "SELECT COUNT(*) FROM inference_jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            running += conn.execute(
                "SELECT COUNT(*) FROM batch_prediction_jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
        label_state_counts = self.issue_label_state_counts(scopes, issue_ids=issue_ids)
        return {
            "issues": int(total),
            "labelled": int(labelled),
            "unlabelled": max(int(total) - int(labelled), 0),
            "predictions": int(predictions),
            "model_failures": int(failures),
            "reviewed_failures": int(reviewed_failures),
            "model_review_status_counts": model_review_status_counts,
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
            "gt_raw_label": (row["gt_raw_label"] or "") if "gt_raw_label" in row.keys() else "",
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
                    "review_domain": (
                        str(row["annotation_review_domain"] or "legacy")
                        if "annotation_review_domain" in keys
                        else "legacy"
                    ),
                    "model_review_status": (
                        str(row["annotation_model_review_status"] or "")
                        if "annotation_model_review_status" in keys
                        else ""
                    ),
                    "campaign_id": (
                        str(row["annotation_campaign_id"] or "")
                        if "annotation_campaign_id" in keys
                        else ""
                    ),
                    "reference_id": (
                        str(row["annotation_reference_id"] or "")
                        if "annotation_reference_id" in keys
                        else ""
                    ),
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

