"""Labeling queries storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from ..labeling_rules import current_adjudication
from collections import defaultdict
from typing import Any, Sequence
from .shared import LABELS
from .labeling_shared import _clean_values, _filter_values, _parse_labeling_cluster


class LabelingQueriesMixin:
    def labeling_labelers(
        self, baseline_scopes: Sequence[str], task_id: str = ""
    ) -> list[str]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            return []
        params: list[Any] = [*scopes]
        task_clause = ""
        task = str(task_id or "").strip()
        if task:
            task_clause = "AND label_case.task_id = ?"
            params.append(task)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT lower(trim(revision.author)) AS labeler
                FROM label_revisions revision
                JOIN label_cases label_case ON label_case.id = revision.label_case_id
                WHERE label_case.baseline_scope IN ({', '.join('?' for _ in scopes)})
                  AND revision.revision_kind IN ('submission', 'legacy', 'adjudication')
                  AND trim(revision.author) != ''
                  {task_clause}
                ORDER BY labeler
                """,
                params,
            ).fetchall()
            decision_rows = conn.execute(
                f"SELECT DISTINCT lower(trim(created_by)) AS labeler FROM issue_label_decisions WHERE baseline_scope IN ({', '.join('?' for _ in scopes)}) AND trim(created_by) != ''",
                scopes,
            ).fetchall() if not task else []
        return sorted({str(row["labeler"] or "") for row in [*rows, *decision_rows]})

    def labeling_assignees(
        self, baseline_scopes: Sequence[str], task_id: str = ""
    ) -> list[str]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            return []
        params: list[Any] = [*scopes]
        task_clause = ""
        task = str(task_id or "").strip()
        if task:
            task_clause = "AND split.id = ?"
            params.append(task)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT lower(trim(assignment.assignee)) AS assignee
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                JOIN review_worksets workset ON workset.id = split.workset_id
                WHERE workset.baseline_scope IN ({', '.join('?' for _ in scopes)})
                  AND split.task_kind = 'labeling'
                  AND trim(assignment.assignee) != ''
                  {task_clause}
                ORDER BY assignee
                """,
                params,
            ).fetchall()
        return [str(row["assignee"] or "") for row in rows]

    def _labeling_discussion_issue_ids(
        self,
        *,
        baseline_scopes: Sequence[str],
        issue_ids: Sequence[str],
        task_id: str = "",
    ) -> set[str]:
        """Return Issues with a Case-level or applicable task discussion.

        This query runs only when the caller selects a discussion filter.  It is
        kept separate from the main projection so the default gallery path does
        not pay for a comments join.
        """

        scopes = _clean_values(baseline_scopes)
        cleaned = _clean_values(issue_ids)
        if not scopes or not cleaned:
            return set()
        task = str(task_id or "").strip()
        matched: set[str] = set()
        with self.connect() as conn:
            for offset in range(0, len(cleaned), 400):
                batch = cleaned[offset : offset + 400]
                params: list[Any] = [*batch, *scopes]
                campaign_clause = "link.comment_id IS NOT NULL"
                if task:
                    campaign_clause += " AND COALESCE(link.task_id, '') = ?"
                    params.append(task)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT comment.issue_id
                    FROM review_comments comment
                    LEFT JOIN label_comment_links link ON link.comment_id = comment.id
                    WHERE comment.issue_id IN ({', '.join('?' for _ in batch)})
                      AND comment.baseline_scope IN ({', '.join('?' for _ in scopes)})
                      AND (
                        comment.discussion_channel = 'case'
                        OR ({campaign_clause})
                      )
                    """,
                    params,
                ).fetchall()
                matched.update(str(row["issue_id"] or "") for row in rows)
        return matched

    def _project_labeling_cases(
        self,
        *,
        baseline_scopes: Sequence[str],
        task_id: str = "",
        search: str = "",
        issue_ids: Sequence[str] = (),
        status: str = "all",
        author: str = "",
        assignee: str = "",
        exclusion: str = "all",
        expected_output: str = "",
        gt_label: str = "",
        comment_state: str = "all",
        cluster: str = "",
    ) -> tuple[list[dict[str, Any]], str]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            return [], ""
        task = str(task_id or "").strip()
        parameters: list[Any] = []
        if task:
            from_sql = """
                FROM review_workset_items member
                JOIN issue_work_splits task ON task.workset_id = member.workset_id
                JOIN review_worksets workset ON workset.id = member.workset_id
                JOIN issues issue ON issue.issue_id = member.issue_id
            """
            where = (
                "task.id = ? AND task.task_kind = 'labeling'"
                f" AND issue.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            )
            parameters.extend([task, *scopes])
        else:
            from_sql = "FROM issues issue"
            where = f"issue.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            parameters.extend(scopes)
        normalized_search = str(search or "").strip()
        if normalized_search:
            where += " AND (issue.issue_id LIKE ? OR issue.title LIKE ? OR issue.scenario LIKE ?)"
            needle = f"%{normalized_search}%"
            parameters.extend((needle, needle, needle))
        selected_issue_ids = set(_clean_values(issue_ids))
        normalized_assignees = {
            value.lower() for value in _filter_values(assignee)
        }
        if normalized_assignees:
            assignee_placeholders = ", ".join("?" for _ in normalized_assignees)
            where += (
                " AND EXISTS (SELECT 1 FROM review_work_assignments wa"
                " JOIN issue_work_splits wa_split ON wa_split.id = wa.split_id"
                " WHERE wa.issue_id = issue.issue_id"
                " AND wa_split.task_kind = 'labeling'"
                f" AND lower(wa.assignee) IN ({assignee_placeholders})"
                + (" AND wa_split.id = ?" if task else "")
                + ")"
            )
            parameters.extend(sorted(normalized_assignees))
            if task:
                parameters.append(task)
        normalized_authors = {value.lower() for value in _filter_values(author)}
        normalized_statuses = set(_filter_values(status)) - {"all"}
        if normalized_statuses - {"pending", "resolved", "conflict"}:
            raise ValueError("标注状态不合法。")
        normalized_expected_outputs = set(_filter_values(expected_output)) - {"all"}
        if normalized_expected_outputs - set(LABELS):
            raise ValueError("标注结果类别不合法。")
        normalized_gt_labels = set(_filter_values(gt_label)) - {"all"}
        if normalized_gt_labels - set(LABELS):
            raise ValueError("GT 类别不合法。")
        normalized_comment_states = {
            value.lower() for value in _filter_values(comment_state)
        } - {"all"}
        if normalized_comment_states - {"with", "without"}:
            raise ValueError("讨论筛选不合法。")
        normalized_exclusions = {
            value.lower() for value in _filter_values(exclusion)
        } - {"all"}
        if normalized_exclusions - {"excluded", "active"}:
            raise ValueError("排除筛选不合法。")
        normalized_cluster = _parse_labeling_cluster(cluster)
        selected_source_sql = ", workset.selection_source_run_id AS task_source_run_id" if task else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT issue.issue_id, issue.baseline_scope, issue.gt_label,
                       issue.gt_source, issue.title, issue.scenario{selected_source_sql}
                {from_sql}
                WHERE {where}
                ORDER BY issue.issue_id
                """,
                parameters,
            ).fetchall()
        if selected_issue_ids:
            rows = [row for row in rows if str(row["issue_id"] or "") in selected_issue_ids]
        if normalized_gt_labels:
            rows = [
                row for row in rows
                if str(row["gt_label"] or "") in normalized_gt_labels
            ]
        if len(normalized_comment_states) == 1:
            discussion_issue_ids = self._labeling_discussion_issue_ids(
                baseline_scopes=scopes,
                issue_ids=[str(row["issue_id"] or "") for row in rows],
                task_id=task,
            )
            rows = [
                row
                for row in rows
                if (str(row["issue_id"] or "") in discussion_issue_ids)
                == ("with" in normalized_comment_states)
            ]
        task_source_run_id = str(rows[0]["task_source_run_id"] or "") if task and rows else ""
        cases_by_issue = self._batch_label_cases(
            [str(row["issue_id"]) for row in rows], task,
            source_run_id=task_source_run_id,
        )
        shared_by_issue: dict[str, dict[str, Any]] = {}
        if not task:
            issue_ids_by_scope: dict[str, list[str]] = defaultdict(list)
            for row in rows:
                issue_ids_by_scope[str(row["baseline_scope"] or "")].append(
                    str(row["issue_id"])
                )
            for scope, scope_issue_ids in issue_ids_by_scope.items():
                shared_by_issue.update(
                    self.project_issue_label_states(
                        scope,
                        scope_issue_ids,
                        include_sources=False,
                        preloaded_cases=cases_by_issue,
                    )
                )
        projected: list[dict[str, Any]] = []
        for row in rows:
            cases = cases_by_issue.get(str(row["issue_id"]), [])
            resolved_outputs = {
                item["resolution"]["expected_output"]
                for item in cases
                if item["resolution"]["state"] == "resolved"
                and item["resolution"]["expected_output"] in LABELS
            }
            if len(resolved_outputs) > 1:
                aggregate_state = "conflict"
                expected_output_value = ""
            elif len(resolved_outputs) == 1:
                aggregate_state = "resolved"
                expected_output_value = next(iter(resolved_outputs))
            elif any(item["resolution"]["state"] in {"conflict", "stale"} for item in cases):
                aggregate_state = "conflict"
                expected_output_value = ""
            else:
                aggregate_state = "pending"
                expected_output_value = ""
            shared_state = shared_by_issue.get(str(row["issue_id"])) if not task else None
            if shared_state:
                aggregate_state = str(shared_state.get("state") or "pending")
                if aggregate_state == "none":
                    aggregate_state = "pending"
                elif aggregate_state == "stale":
                    aggregate_state = "conflict"
                expected_output_value = str(shared_state.get("expected_output") or "")
            if normalized_statuses and aggregate_state not in normalized_statuses:
                continue
            if normalized_authors:
                result_authors = {
                    str(head.get("author") or "").strip().lower()
                    for item in cases for head in item["resolution"].get("heads") or []
                }
                for item in cases:
                    decision = item["resolution"].get("adjudication") or {}
                    if decision and not decision.get("stale"):
                        result_authors.add(str(decision.get("created_by") or "").strip().lower())
                decision = (shared_state or {}).get("decision") or {}
                if decision and not decision.get("stale"):
                    result_authors.add(str(decision.get("created_by") or "").strip().lower())
                if not result_authors.intersection(normalized_authors):
                    continue
            if (
                normalized_expected_outputs
                and expected_output_value not in normalized_expected_outputs
            ):
                continue
            if normalized_cluster is not None:
                if normalized_cluster[0] == "adjudicated":
                    if not current_adjudication({
                        "label_state": aggregate_state,
                        "expected_output": expected_output_value,
                        "decision": (shared_state or {}).get("decision"),
                        "label_cases": cases,
                    }):
                        continue
                elif normalized_cluster[0] == "pair":
                    if (
                        aggregate_state != "resolved"
                        or str(row["gt_label"] or "") != normalized_cluster[1]
                        or expected_output_value != normalized_cluster[2]
                    ):
                        continue
                elif str(row["scenario"] or "") != normalized_cluster[1]:
                    continue
            if len(normalized_exclusions) == 1:
                resolved_excluded = any(
                    (item["resolution"].get("result_revision") or {}).get("is_excluded")
                    for item in cases
                    if item["resolution"]["state"] == "resolved"
                )
                if "excluded" in normalized_exclusions and not resolved_excluded:
                    continue
                if "active" in normalized_exclusions and resolved_excluded:
                    continue
            projected.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "gt_label": str(row["gt_label"] or ""),
                    "gt_source": str(row["gt_source"] or ""),
                    "title": str(row["title"] or ""),
                    "scenario": str(row["scenario"] or ""),
                    "label_state": aggregate_state,
                    "expected_output": expected_output_value,
                    "source_count": len(cases),
                    "decision": (shared_state or {}).get("decision") if shared_state else None,
                    "label_cases": cases,
                }
            )
        return projected, task

    def list_labeling_cases(
        self,
        *,
        baseline_scopes: Sequence[str],
        task_id: str = "",
        search: str = "",
        issue_ids: Sequence[str] = (),
        status: str = "all",
        author: str = "",
        assignee: str = "",
        exclusion: str = "all",
        expected_output: str = "",
        gt_label: str = "",
        comment_state: str = "all",
        cluster: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            return {"items": [], "total": 0, "page": 1, "page_size": page_size, "pages": 0}
        projected, task = self._project_labeling_cases(
            baseline_scopes=baseline_scopes,
            task_id=task_id,
            search=search,
            issue_ids=issue_ids,
            status=status,
            author=author,
            assignee=assignee,
            exclusion=exclusion,
            expected_output=expected_output,
            gt_label=gt_label,
            comment_state=comment_state,
            cluster=cluster,
        )
        safe_page_size = min(100, max(1, int(page_size)))
        total = len(projected)
        pages = (total + safe_page_size - 1) // safe_page_size if total else 0
        safe_page = min(max(1, int(page)), pages or 1)
        start = (safe_page - 1) * safe_page_size
        return {
            "items": projected[start : start + safe_page_size],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "pages": pages,
            "labelers": self.labeling_labelers(scopes, task),
            "assignees": self.labeling_assignees(scopes, task),
        }

    def labeling_case_issue_ids(
        self,
        *,
        baseline_scopes: Sequence[str],
        task_id: str = "",
        search: str = "",
        issue_ids: Sequence[str] = (),
        status: str = "all",
        author: str = "",
        assignee: str = "",
        exclusion: str = "all",
        expected_output: str = "",
        gt_label: str = "",
        comment_state: str = "all",
        cluster: str = "",
    ) -> list[str]:
        projected, _ = self._project_labeling_cases(
            baseline_scopes=baseline_scopes,
            task_id=task_id,
            search=search,
            issue_ids=issue_ids,
            status=status,
            author=author,
            assignee=assignee,
            exclusion=exclusion,
            expected_output=expected_output,
            gt_label=gt_label,
            comment_state=comment_state,
            cluster=cluster,
        )
        return [item["issue_id"] for item in projected]

    def labeling_clusters(
        self,
        *,
        baseline_scopes: Sequence[str],
        task_id: str = "",
        search: str = "",
        issue_ids: Sequence[str] = (),
        status: str = "all",
        author: str = "",
        assignee: str = "",
        exclusion: str = "all",
        expected_output: str = "",
        gt_label: str = "",
        comment_state: str = "all",
    ) -> list[dict[str, Any]]:
        projected, _ = self._project_labeling_cases(
            baseline_scopes=baseline_scopes,
            task_id=task_id,
            search=search,
            issue_ids=issue_ids,
            status=status,
            author=author,
            assignee=assignee,
            exclusion=exclusion,
            expected_output=expected_output,
            gt_label=gt_label,
            comment_state=comment_state,
        )
        pair_counts: dict[tuple[str, str], int] = {}
        scenario_counts: dict[str, int] = {}
        for item in projected:
            scenario = str(item["scenario"] or "").strip()
            if scenario:
                scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
            if item["label_state"] != "resolved":
                continue
            gt = str(item["gt_label"] or "").strip()
            output = str(item["expected_output"] or "").strip()
            if gt in LABELS and output in LABELS:
                pair_counts[(gt, output)] = pair_counts.get((gt, output), 0) + 1
        clusters: list[dict[str, Any]] = [
            {
                "kind": "pair",
                "key": f"pair:{gt}|{output}",
                "label": f"{gt} → {output}",
                "count": count,
            }
            for (gt, output), count in sorted(
                pair_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]
        clusters.extend(
            {
                "kind": "scenario",
                "key": f"scenario:{name}",
                "label": name,
                "count": count,
            }
            for name, count in sorted(
                scenario_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )
        return clusters
