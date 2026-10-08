"""Labeling projection storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Sequence
from .shared import LABELS, _json_load
from .snapshots import _sha256_json
from .labeling_shared import ISSUE_LABEL_GT_RELATIONS, ISSUE_LABEL_STATES, _clean_values, _issue_decision_source_payload, _issue_label_gt_relation


class LabelingProjectionMixin:
    def _batch_label_cases(
        self,
        issue_ids: Sequence[str],
        task_id: str = "",
        baseline_scope: str = "",
        source_run_id: str = "",
        connection: Any | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Resolve current Label Case heads in bounded SQL batches.

        Read only the current per-author heads, latest resolution and any
        adjudication result revision. Historical revisions are not materialized
        for gallery filters or Overview projections.
        """

        cleaned = list(dict.fromkeys(str(value or "").strip() for value in issue_ids))
        cleaned = [value for value in cleaned if value]
        if not cleaned:
            return {}
        task = str(task_id or "").strip()
        scope = str(baseline_scope or "").strip()
        selected_source_run = str(source_run_id or "").strip()
        case_rows: list[Any] = []
        head_rows: list[Any] = []
        result_revision_rows: list[Any] = []
        resolution_rows: list[Any] = []
        assignment_rows: list[Any] = []
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            for offset in range(0, len(cleaned), 400):
                batch = cleaned[offset : offset + 400]
                clause = f"issue_id IN ({', '.join('?' for _ in batch)})"
                params: list[Any] = list(batch)
                if scope:
                    clause += " AND baseline_scope = ?"
                    params.append(scope)
                if task:
                    clause += " AND task_id = ?"
                    params.append(task)
                if selected_source_run:
                    clause += " AND source_run_id = ?"
                    params.append(selected_source_run)
                case_rows.extend(
                    conn.execute(
                        f"SELECT * FROM label_cases WHERE {clause} ORDER BY created_at, id",
                        params,
                    ).fetchall()
                )
            case_ids = [str(row["id"]) for row in case_rows]
            if case_ids:
                fully_suppressed: set[str] = set()
                for offset in range(0, len(case_ids), 400):
                    batch = case_ids[offset : offset + 400]
                    placeholders = ", ".join("?" for _ in batch)
                    rows = conn.execute(
                        f"""
                        SELECT revision.label_case_id,
                               COUNT(*) AS revision_count,
                               SUM(CASE WHEN suppressed.revision_id IS NOT NULL THEN 1 ELSE 0 END) AS suppressed_count
                        FROM label_revisions revision
                        LEFT JOIN label_import_suppressed_revisions suppressed
                          ON suppressed.revision_id = revision.id
                        WHERE revision.label_case_id IN ({placeholders})
                          AND revision.revision_kind IN ('submission', 'legacy')
                        GROUP BY revision.label_case_id
                        """,
                        batch,
                    ).fetchall()
                    fully_suppressed.update(
                        str(row["label_case_id"])
                        for row in rows
                        if int(row["revision_count"] or 0) > 0
                        and int(row["revision_count"] or 0) == int(row["suppressed_count"] or 0)
                    )
                if fully_suppressed:
                    case_rows = [row for row in case_rows if str(row["id"]) not in fully_suppressed]
                    case_ids = [str(row["id"]) for row in case_rows]
            for offset in range(0, len(case_ids), 400):
                batch = case_ids[offset : offset + 400]
                placeholders = ", ".join("?" for _ in batch)
                head_rows.extend(
                    conn.execute(
                        f"""
                        SELECT revision.* FROM label_revisions revision
                        WHERE revision.label_case_id IN ({placeholders})
                          AND revision.revision_kind IN ('submission', 'legacy')
                          AND NOT EXISTS (
                              SELECT 1 FROM label_import_suppressed_revisions suppressed
                              WHERE suppressed.revision_id = revision.id
                          )
                          AND revision.id = (
                              SELECT MAX(candidate.id) FROM label_revisions candidate
                              WHERE candidate.label_case_id = revision.label_case_id
                                AND lower(candidate.author) = lower(revision.author)
                                AND candidate.revision_kind IN ('submission', 'legacy')
                                AND NOT EXISTS (
                                    SELECT 1 FROM label_import_suppressed_revisions suppressed
                                    WHERE suppressed.revision_id = candidate.id
                                )
                          )
                        ORDER BY revision.label_case_id, lower(revision.author), revision.id
                        """,
                        batch,
                    ).fetchall()
                )
                resolution_rows.extend(
                    conn.execute(
                        f"""
                        SELECT resolution.* FROM label_resolutions resolution
                        WHERE resolution.label_case_id IN ({placeholders})
                          AND resolution.id = (
                              SELECT MAX(candidate.id) FROM label_resolutions candidate
                              WHERE candidate.label_case_id = resolution.label_case_id
                          )
                        ORDER BY resolution.label_case_id, resolution.id
                        """,
                        batch,
                    ).fetchall()
                )
            latest_resolutions = {
                str(row["label_case_id"]): row for row in resolution_rows
            }
            result_revision_ids = list(
                dict.fromkeys(
                    int(row["result_revision_id"])
                    for row in resolution_rows
                    if row["result_revision_id"] not in (None, "")
                )
            )
            for offset in range(0, len(result_revision_ids), 400):
                batch = result_revision_ids[offset : offset + 400]
                result_revision_rows.extend(
                    conn.execute(
                        f"SELECT * FROM label_revisions WHERE id IN ({', '.join('?' for _ in batch)})",
                        batch,
                    ).fetchall()
                )
            task_ids = sorted(
                {str(row["task_id"] or "") for row in case_rows if str(row["task_id"] or "")}
            )
            for offset in range(0, len(task_ids), 200):
                batch = task_ids[offset : offset + 200]
                assignment_rows.extend(
                    conn.execute(
                        f"""
                        SELECT split_id, issue_id, assignee
                        FROM review_work_assignments
                        WHERE split_id IN ({', '.join('?' for _ in batch)})
                        ORDER BY split_id, issue_id, assignee
                        """,
                        batch,
                    ).fetchall()
                )

        heads_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        revisions_by_id: dict[int, dict[str, Any]] = {}
        for row in head_rows:
            item = self._label_revision_dict(row)
            heads_by_case[item["label_case_id"]].append(item)
            revisions_by_id[int(item["id"])] = item
        for row in result_revision_rows:
            item = self._label_revision_dict(row)
            revisions_by_id[int(item["id"])] = item
        assigned_by_case: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in assignment_rows:
            assigned_by_case[(str(row["split_id"]), str(row["issue_id"]))].append(
                str(row["assignee"] or "").strip().lower()
            )
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in case_rows:
            case_id = str(row["id"])
            assigned = assigned_by_case.get(
                (str(row["task_id"] or ""), str(row["issue_id"])), []
            )
            heads = list(heads_by_case.get(case_id, []))
            if assigned:
                heads = [item for item in heads if item["author"].strip().lower() in assigned]
            heads.sort(key=lambda item: (item["author"].lower(), int(item["id"])))
            latest_resolution = latest_resolutions.get(case_id)
            result_revision = (
                revisions_by_id.get(int(latest_resolution["result_revision_id"]))
                if latest_resolution is not None
                and latest_resolution["result_revision_id"] not in (None, "")
                else None
            )
            item = self._label_case_dict(row)
            item["resolution"] = self._resolve_loaded_label_case(
                heads=heads,
                assigned_authors=assigned,
                latest_resolution=latest_resolution,
                result_revision=result_revision,
            )
            result[str(row["issue_id"])].append(item)
        return dict(result)

    def project_issue_label_states(
        self,
        baseline_scope: str,
        issue_ids: Sequence[str],
        *,
        include_sources: bool = True,
        connection: Any | None = None,
        preloaded_cases: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Resolve shared Labeling state for a bounded set of baseline Issues.

        Model Run identity is intentionally absent from this projection. Every
        source Label Case in the requested baseline scope participates, and an
        unresolved source blocks a resolved-looking aggregate.
        """

        scope = str(baseline_scope or "").strip()
        cleaned = list(dict.fromkeys(str(value or "").strip() for value in issue_ids))
        cleaned = [value for value in cleaned if value]

        def empty_state() -> dict[str, Any]:
            return {
                "state": "none",
                "expected_output": "",
                "gt_relation": "unknown",
                "gt_review_pending": False,
                "method": "single",
                "source_task_ids": [],
                "source_revision_ids": [],
                "source_fingerprint": "",
                "sources": [],
                "decision": None,
            }

        projected = {issue_id: empty_state() for issue_id in cleaned}
        if not scope or not cleaned:
            return projected

        gt_by_issue: dict[str, str] = {}
        imported_by_issue: dict[str, dict[str, Any]] = {}
        imported_sources_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        decision_by_issue: dict[str, Any] = {}
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            wanted_issue_ids = set(cleaned)
            for offset in range(0, len(cleaned), 400):
                batch = cleaned[offset : offset + 400]
                rows = conn.execute(
                    f"""
                    SELECT issue_id, gt_label FROM issues
                    WHERE baseline_scope = ?
                      AND issue_id IN ({', '.join('?' for _ in batch)})
                    """,
                    (scope, *batch),
                ).fetchall()
                gt_by_issue.update(
                    {
                        str(row["issue_id"]): str(row["gt_label"] or "")
                        for row in rows
                    }
                )
                imported_rows = conn.execute(
                    f"""
                    SELECT state.*, batch.name AS batch_name,
                           batch.source_type, batch.migration_version,
                           batch.status AS batch_status
                    FROM label_import_case_states state
                    JOIN label_import_batches batch ON batch.id = state.batch_id
                    WHERE state.baseline_scope = ?
                      AND state.issue_id IN ({', '.join('?' for _ in batch)})
                      AND batch.status = 'imported'
                    ORDER BY batch.imported_at DESC
                    """,
                    (scope, *batch),
                ).fetchall()
                for row in imported_rows:
                    issue_key = str(row["issue_id"])
                    imported_by_issue.setdefault(
                        issue_key,
                        {
                            key: (_json_load(row[key], []) if key == "source_ids_json" else row[key])
                            for key in row.keys()
                        },
                    )
                source_rows = conn.execute(
                    f"""
                    SELECT source.*, label_case.issue_id,
                           vote.state AS vote_state,
                           vote.expected_output AS vote_expected_output
                    FROM label_import_sources source
                    JOIN label_cases label_case ON label_case.id = source.label_case_id
                    LEFT JOIN label_import_votes vote ON vote.id = source.vote_id
                    JOIN label_import_batches batch ON batch.id = source.batch_id
                    WHERE label_case.baseline_scope = ?
                      AND label_case.issue_id IN ({', '.join('?' for _ in batch)})
                      AND batch.status = 'imported'
                    ORDER BY label_case.issue_id, source.source_annotation_id
                    """,
                    (scope, *batch),
                ).fetchall()
                for row in source_rows:
                    imported_sources_by_case[str(row["label_case_id"])].append(
                        {key: row[key] for key in row.keys()}
                    )
            cases_by_issue = (
                {
                    issue_id: list(preloaded_cases.get(issue_id) or [])
                    for issue_id in cleaned
                }
                if preloaded_cases is not None
                else self._batch_label_cases(
                    cleaned, baseline_scope=scope, connection=conn
                )
            )
            if cases_by_issue:
                decision_rows = conn.execute(
                    """
                    SELECT decision.* FROM issue_label_decisions decision
                    WHERE decision.baseline_scope = ?
                      AND decision.id = (
                          SELECT MAX(candidate.id)
                          FROM issue_label_decisions candidate
                          WHERE candidate.baseline_scope = decision.baseline_scope
                            AND candidate.issue_id = decision.issue_id
                      )
                    ORDER BY decision.issue_id
                    """,
                    (scope,),
                ).fetchall()
                for row in decision_rows:
                    issue_key = str(row["issue_id"])
                    if issue_key in wanted_issue_ids:
                        decision_by_issue[issue_key] = row
        for issue_id in cleaned:
            cases = cases_by_issue.get(issue_id, [])
            if not cases or issue_id not in gt_by_issue:
                continue
            cases = sorted(
                cases,
                key=lambda item: (
                    str(item.get("task_id") or ""),
                    str(item.get("id") or ""),
                ),
            )
            resolutions = [item.get("resolution") or {} for item in cases]
            source_states = [str(item.get("state") or "pending") for item in resolutions]
            resolved_outputs = [
                str(item.get("expected_output") or "")
                for item in resolutions
                if item.get("state") == "resolved"
            ]
            distinct_outputs = {value for value in resolved_outputs if value in LABELS}

            if "stale" in source_states:
                aggregate_state = "stale"
            elif "conflict" in source_states or len(distinct_outputs) > 1:
                aggregate_state = "conflict"
            elif (
                any(item != "resolved" for item in source_states)
                or len(resolved_outputs) != len(cases)
                or any(value not in LABELS for value in resolved_outputs)
                or len(distinct_outputs) != 1
            ):
                aggregate_state = "pending"
            else:
                aggregate_state = "resolved"

            imported_state = imported_by_issue.get(issue_id) or {}
            if str(imported_state.get("state") or "") == "conflict":
                aggregate_state = "conflict"

            expected_output = (
                next(iter(distinct_outputs)) if aggregate_state == "resolved" else ""
            )
            method = "consensus" if len(cases) > 1 else str(
                resolutions[0].get("method") or "single"
            )
            if method not in {"single", "consensus", "adjudication"}:
                method = "single"

            source_task_ids: set[str] = set()
            source_revision_ids: set[int] = set()
            sources: list[dict[str, Any]] = []
            for case, resolution in zip(cases, resolutions):
                task_id = str(case.get("task_id") or "").strip()
                if task_id:
                    source_task_ids.add(task_id)
                heads = list(resolution.get("heads") or [])
                adjudication = resolution.get("adjudication") or {}
                revisions_by_id: dict[int, dict[str, Any]] = {}
                for revision in heads:
                    try:
                        revision_id = int(revision.get("id"))
                    except (TypeError, ValueError):
                        continue
                    source_revision_ids.add(revision_id)
                    revisions_by_id[revision_id] = {
                        "id": revision_id,
                        "expected_output": str(revision.get("expected_output") or ""),
                        "author": str(revision.get("author") or ""),
                        "rationale": str(revision.get("rationale") or ""),
                        "created_at": str(revision.get("created_at") or ""),
                    }
                adjudication_source_ids: list[int] = []
                for value in adjudication.get("source_revision_ids") or []:
                    try:
                        revision_id = int(value)
                    except (TypeError, ValueError):
                        continue
                    source_revision_ids.add(revision_id)
                    adjudication_source_ids.append(revision_id)
                result_revision = resolution.get("result_revision") or {}
                try:
                    result_revision_id = int(result_revision.get("id"))
                except (TypeError, ValueError):
                    result_revision_id = 0
                if result_revision_id:
                    source_revision_ids.add(result_revision_id)
                    revisions_by_id.setdefault(
                        result_revision_id,
                        {
                            "id": result_revision_id,
                            "expected_output": str(
                                result_revision.get("expected_output") or ""
                            ),
                            "author": str(result_revision.get("author") or ""),
                            "rationale": str(result_revision.get("rationale") or ""),
                            "created_at": str(result_revision.get("created_at") or ""),
                        },
                    )
                sources.append(
                    {
                        "label_case_id": str(case.get("id") or ""),
                        "task_id": task_id,
                        "source_run_id": str(case.get("source_run_id") or ""),
                        "state": str(resolution.get("state") or "pending"),
                        "expected_output": (
                            str(resolution.get("expected_output") or "")
                            if resolution.get("state") == "resolved"
                            else ""
                        ),
                        "method": str(resolution.get("method") or "single"),
                        "assigned_count": int(resolution.get("assigned_count") or 0),
                        "submitted_count": int(resolution.get("submitted_count") or 0),
                        "result_revision_id": result_revision_id or None,
                        "source_revision_ids": sorted(revisions_by_id),
                        "revision_summaries": [
                            revisions_by_id[key] for key in sorted(revisions_by_id)
                        ],
                        "adjudication": (
                            {
                                "id": adjudication.get("id"),
                                "stale": bool(adjudication.get("stale")),
                                "result_revision_id": result_revision_id or None,
                                "source_revision_ids": sorted(set(adjudication_source_ids)),
                            }
                            if adjudication
                            else None
                        ),
                        "resolution_id": (
                            adjudication.get("id") if adjudication else None
                        ),
                        "source_type": (
                            "legacy_model_review"
                            if imported_sources_by_case.get(str(case.get("id") or ""))
                            else "case_labeling"
                        ),
                        "source_scope": "task" if task_id else "free",
                        "import_batch_id": (
                            str(imported_state.get("batch_id") or "")
                            if imported_sources_by_case.get(str(case.get("id") or ""))
                            else ""
                        ),
                        "import_batch_name": (
                            str(imported_state.get("batch_name") or "")
                            if imported_sources_by_case.get(str(case.get("id") or ""))
                            else ""
                        ),
                        "frozen_gt_snapshot_id": (
                            str(imported_state.get("frozen_gt_snapshot_id") or "")
                            if imported_sources_by_case.get(str(case.get("id") or ""))
                            else ""
                        ),
                        "frozen_gt_label": (
                            str(imported_state.get("frozen_gt_label") or "")
                            if imported_sources_by_case.get(str(case.get("id") or ""))
                            else ""
                        ),
                        "legacy_sources": [
                            {
                                "source_annotation_id": int(item["source_annotation_id"]),
                                "source_run_id": str(item["source_run_id"] or ""),
                                "source_work_split_id": str(item["source_work_split_id"] or ""),
                                "source_label": str(item["source_label"] or ""),
                                "source_review_status": str(item["source_review_status"] or ""),
                                "source_reviewer": str(item["source_reviewer"] or ""),
                                "source_created_at": str(item["source_created_at"] or ""),
                                "migration_version": str(item["migration_version"] or ""),
                            }
                            for item in imported_sources_by_case.get(str(case.get("id") or ""), [])
                        ],
                    }
                )

            source_payload = _issue_decision_source_payload(sources)
            source_fingerprint = _sha256_json(source_payload) if source_payload else ""
            decision_row = decision_by_issue.get(issue_id)
            decision = None
            if decision_row is not None:
                decision = self._issue_label_decision_dict(decision_row)
                decision["stale"] = (
                    not source_fingerprint
                    or decision["source_fingerprint"] != source_fingerprint
                    or sorted(decision["source_case_ids"])
                    != sorted(item["label_case_id"] for item in source_payload)
                )
                if decision["stale"]:
                    aggregate_state = "stale"
                    expected_output = ""
                else:
                    aggregate_state = "resolved"
                    expected_output = decision["expected_output"]
                method = "adjudication"

            relation = (
                _issue_label_gt_relation(
                    expected_output,
                    str(imported_state.get("frozen_gt_label") or gt_by_issue[issue_id]),
                )
                if aggregate_state == "resolved"
                else "unknown"
            )
            gt_review_pending = bool(imported_state.get("gt_review_pending"))
            if not include_sources:
                projected[issue_id] = {
                    "state": aggregate_state,
                    "expected_output": expected_output,
                    "gt_relation": relation,
                    "gt_review_pending": gt_review_pending,
                    "method": method,
                    "source_task_ids": [],
                    "source_revision_ids": [],
                    "source_fingerprint": source_fingerprint,
                    "sources": [],
                    "decision": decision,
                }
                continue
            projected[issue_id] = {
                "state": aggregate_state,
                "expected_output": expected_output,
                "gt_relation": relation,
                "gt_review_pending": gt_review_pending,
                "method": method,
                "source_task_ids": sorted(source_task_ids),
                "source_revision_ids": sorted(source_revision_ids),
                "source_fingerprint": source_fingerprint,
                "sources": sources,
                "decision": decision,
            }
        return projected

    def issue_label_state_counts(
        self, baseline_scopes: Sequence[str] = ()
    ) -> dict[str, int]:
        """Count the shared Issue-label projection without mixing Run Reviews."""

        scopes = _clean_values(baseline_scopes)
        issue_where = (
            f"WHERE baseline_scope IN ({', '.join('?' for _ in scopes)})"
            if scopes
            else ""
        )
        label_where = (
            f"WHERE label_case.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            if scopes
            else ""
        )
        with self.connect() as conn:
            issue_rows = conn.execute(
                f"""
                SELECT baseline_scope, COUNT(*) AS issue_count
                FROM issues {issue_where}
                GROUP BY baseline_scope
                """,
                list(scopes),
            ).fetchall()
            label_rows = conn.execute(
                f"""
                SELECT label_case.baseline_scope, label_case.issue_id
                FROM label_cases label_case
                JOIN issues issue
                  ON issue.issue_id = label_case.issue_id
                 AND issue.baseline_scope = label_case.baseline_scope
                {label_where}
                GROUP BY label_case.baseline_scope, label_case.issue_id
                ORDER BY label_case.baseline_scope, label_case.issue_id
                """,
                list(scopes),
            ).fetchall()

        totals_by_scope = {
            str(row["baseline_scope"] or ""): int(row["issue_count"] or 0)
            for row in issue_rows
        }
        ids_by_scope: dict[str, list[str]] = defaultdict(list)
        for row in label_rows:
            ids_by_scope[str(row["baseline_scope"] or "")].append(
                str(row["issue_id"] or "")
            )
        counts = {
            **{state: 0 for state in ISSUE_LABEL_STATES},
            **{relation: 0 for relation in ISSUE_LABEL_GT_RELATIONS},
            "gt_review_pending": 0,
        }
        for scope, total in totals_by_scope.items():
            issue_ids = ids_by_scope.get(scope, [])
            counts["none"] += max(total - len(issue_ids), 0)
            if not issue_ids:
                continue
            projections = self.project_issue_label_states(
                scope, issue_ids, include_sources=False
            )
            for item in projections.values():
                state = str(item.get("state") or "none")
                if state not in ISSUE_LABEL_STATES:
                    state = "pending"
                counts[state] += 1
                relation = str(item.get("gt_relation") or "unknown")
                if relation not in ISSUE_LABEL_GT_RELATIONS:
                    relation = "unknown"
                counts[relation] += 1
        counts["gt_review_pending"] = (
            counts["differs_from_gt"] + counts["fills_missing_gt"]
        )
        return counts
