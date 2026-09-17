"""Independent RA Case-labeling storage and projection helpers."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Sequence
from uuid import uuid4

from .shared import (
    LABELS,
    LabelAnnotationConflictError,
    _json,
    _json_load,
    utc_now,
)


LABEL_TASK_KINDS = ("labeling", "model_review", "legacy")


def _clean_values(values: Iterable[Any]) -> list[str]:
    return sorted({str(value or "").strip() for value in values if str(value or "").strip()})


def _source_fingerprint(values: Iterable[int]) -> str:
    payload = ",".join(str(value) for value in sorted({int(value) for value in values}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DatabaseLabelingMixin:
    def _mark_labeling_change(self, conn: Any) -> None:
        # SQLite tables have the standard row triggers installed by init().
        # PostgreSQL migration 042 deliberately stays within the guarded
        # additive-DDL release contract, so these writes advance the shared
        # revision explicitly in the same transaction.
        if self.backend == "postgresql":
            conn.execute(
                "UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = now() WHERE id = 1"
            )
        self._mark_change_topic(conn, "labeling")

    @staticmethod
    def _label_revision_dict(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "label_case_id": str(row["label_case_id"] or ""),
            "expected_output": str(row["expected_output"] or ""),
            "tags": _json_load(row["tags_json"], []),
            "evidence_gaps": _json_load(row["evidence_gaps_json"], []),
            "rationale": str(row["rationale"] or ""),
            "is_excluded": bool(row["is_excluded"]),
            "author": str(row["author"] or ""),
            "author_source": str(row["author_source"] or "legacy"),
            "author_verified": bool(row["author_verified"]),
            "revision_kind": str(row["revision_kind"] or "submission"),
            "supersedes_id": (
                int(row["supersedes_id"])
                if row["supersedes_id"] not in (None, "")
                else None
            ),
            "source_annotation_id": (
                int(row["source_annotation_id"])
                if row["source_annotation_id"] not in (None, "")
                else None
            ),
            "created_at": str(row["created_at"] or ""),
            "attachments": [],
        }

    @staticmethod
    def _label_case_dict(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"] or ""),
            "baseline_scope": str(row["baseline_scope"] or ""),
            "issue_id": str(row["issue_id"] or ""),
            "task_id": str(row["task_id"] or ""),
            "source_run_id": str(row["source_run_id"] or ""),
            "seen_gt_label": str(row["seen_gt_label"] or ""),
            "seen_gt_source": str(row["seen_gt_source"] or ""),
            "created_at": str(row["created_at"] or ""),
        }

    @staticmethod
    def _label_attachment_dict(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "revision_id": int(row["revision_id"]),
            "source_review_attachment_id": str(
                row["source_review_attachment_id"] or ""
            ),
            "original_name": str(row["original_name"] or ""),
            "stored_name": str(row["stored_name"] or ""),
            "media_type": str(row["media_type"] or "application/octet-stream"),
            "size_bytes": int(row["size_bytes"] or 0),
            "width": int(row["width"] or 0),
            "height": int(row["height"] or 0),
            "sha256": str(row["sha256"] or ""),
            "created_at": str(row["created_at"] or ""),
        }

    def create_review_workset(
        self,
        *,
        baseline_scope: str,
        issue_ids: Sequence[str],
        name: str = "",
        selection_source_run_id: str = "",
        source_filter: dict[str, Any] | None = None,
        created_by: str = "",
        created_by_source: str = "legacy",
        created_by_verified: bool = False,
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        ordered = list(dict.fromkeys(str(value or "").strip() for value in issue_ids))
        ordered = [value for value in ordered if value]
        if not scope or not ordered:
            raise ValueError("工作集必须包含数据集和至少一个 Issue。")
        digest = hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()
        source_run = str(selection_source_run_id or "").strip()
        with self._write_lock, self.connect() as conn:
            placeholders = ", ".join("?" for _ in ordered)
            rows = conn.execute(
                f"SELECT issue_id, baseline_scope FROM issues WHERE issue_id IN ({placeholders})",
                ordered,
            ).fetchall()
            by_id = {str(row["issue_id"]): str(row["baseline_scope"] or "") for row in rows}
            missing = [item for item in ordered if item not in by_id]
            wrong_scope = [item for item in ordered if by_id.get(item) != scope]
            if missing:
                raise ValueError("工作集包含不存在的 Issue：" + "、".join(missing[:10]))
            if wrong_scope:
                raise ValueError("工作集包含其他数据集的 Issue：" + "、".join(wrong_scope[:10]))
            existing = conn.execute(
                """
                SELECT * FROM review_worksets
                WHERE baseline_scope = ? AND selection_source_run_id = ?
                  AND members_sha256 = ? AND member_count = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (scope, source_run, digest, len(ordered)),
            ).fetchone()
            if existing is not None:
                return self.get_review_workset(str(existing["id"])) or {}
            workset_id = f"workset-{uuid4().hex}"
            now = utc_now()
            conn.execute(
                """
                INSERT INTO review_worksets (
                    id, baseline_scope, name, selection_source_run_id,
                    source_filter_json, member_count, members_sha256,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workset_id,
                    scope,
                    str(name or "").strip()[:160],
                    source_run,
                    _json(source_filter or {}),
                    len(ordered),
                    digest,
                    str(created_by or "").strip(),
                    str(created_by_source or "legacy").strip() or "legacy",
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, ?)",
                [(workset_id, issue_id, ordinal) for ordinal, issue_id in enumerate(ordered, 1)],
            )
            self._mark_labeling_change(conn)
        return self.get_review_workset(workset_id) or {}

    def get_review_workset(self, workset_id: str) -> dict[str, Any] | None:
        normalized = str(workset_id or "").strip()
        if not normalized:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM review_worksets WHERE id = ?", (normalized,)).fetchone()
            items = conn.execute(
                "SELECT issue_id, ordinal FROM review_workset_items WHERE workset_id = ? ORDER BY ordinal",
                (normalized,),
            ).fetchall()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "baseline_scope": str(row["baseline_scope"]),
            "name": str(row["name"] or ""),
            "selection_source_run_id": str(row["selection_source_run_id"] or ""),
            "source_filter": _json_load(row["source_filter_json"], {}),
            "member_count": int(row["member_count"] or 0),
            "members_sha256": str(row["members_sha256"] or ""),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "items": [
                {"issue_id": str(item["issue_id"]), "ordinal": int(item["ordinal"])}
                for item in items
            ],
        }

    def bind_labeling_task(self, *, task_id: str, workset_id: str) -> None:
        task = str(task_id or "").strip()
        workset = str(workset_id or "").strip()
        with self._write_lock, self.connect() as conn:
            split = conn.execute("SELECT model_run_id FROM issue_work_splits WHERE id = ?", (task,)).fetchone()
            if split is None:
                raise ValueError("标注任务不存在。")
            if conn.execute("SELECT 1 FROM review_worksets WHERE id = ?", (workset,)).fetchone() is None:
                raise ValueError("工作集不存在。")
            conn.execute(
                """
                UPDATE issue_work_splits
                SET task_kind = 'labeling', workset_id = ?,
                    selection_source_run_id = model_run_id
                WHERE id = ?
                """,
                (workset, task),
            )
            self._mark_labeling_change(conn)

    def create_labeling_task(
        self,
        *,
        workset_id: str,
        assignments: Sequence[dict[str, Any]],
        created_by: str,
        seed: int | None,
        reviewers_per_issue: int,
        overlap_ratio: float,
    ) -> dict[str, Any]:
        workset = self.get_review_workset(workset_id)
        if workset is None:
            raise ValueError("工作集不存在。")
        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("任务创建人不能为空。")
        allowed = {item["issue_id"] for item in workset["items"]}
        rows: list[tuple[str, str, str, int, str, str]] = []
        now = utc_now()
        for member in assignments:
            assignee = str(member.get("name") or "").strip().lower()
            if not assignee:
                continue
            items = member.get("items") or [
                {"issue_id": issue_id, "assignment_kind": "base", "ordinal": ordinal}
                for ordinal, issue_id in enumerate(member.get("issue_ids") or (), 1)
            ]
            for item in items:
                issue_id = str(item.get("issue_id") or "").strip()
                if issue_id not in allowed:
                    raise ValueError(f"任务分配包含工作集外 Issue：{issue_id}")
                rows.append(
                    (
                        issue_id,
                        assignee,
                        str(item.get("assignment_kind") or "base"),
                        int(item.get("ordinal") or 1),
                        actor,
                        now,
                    )
                )
        if not rows:
            raise ValueError("任务分配不能为空。")
        task_id = f"split-{uuid4().hex}"
        reviewer_count = max(1, int(reviewers_per_issue))
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO issue_work_splits (
                    id, created_by, created_at, seed, total_count, filter_json,
                    assignees_json, mode, reviewers_per_issue, model_run_id,
                    overlap_ratio, assignment_count, task_kind, workset_id,
                    selection_source_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, 'labeling', ?, ?)
                """,
                (
                    task_id,
                    actor,
                    now,
                    seed,
                    len({row[0] for row in rows}),
                    _json(workset.get("source_filter") or {}),
                    _json(list(assignments)),
                    "blind" if reviewer_count > 1 else "single",
                    reviewer_count,
                    float(overlap_ratio),
                    len(rows),
                    workset_id,
                    str(workset.get("selection_source_run_id") or ""),
                ),
            )
            conn.executemany(
                """
                INSERT INTO review_work_assignments (
                    split_id, issue_id, assignee, assignment_kind, ordinal,
                    assigned_by, assigned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [(task_id, *row) for row in rows],
            )
            self._mark_labeling_change(conn)
        return {
            "id": task_id,
            "workset_id": workset_id,
            "member_count": len({row[0] for row in rows}),
            "assignment_count": len(rows),
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": float(overlap_ratio),
            "created_by": actor,
            "created_at": now,
        }

    def list_labeling_tasks(self, baseline_scopes: Sequence[str] = ()) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        where = "WHERE split.task_kind = 'labeling'"
        params: list[Any] = []
        if scopes:
            where += f" AND workset.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            params.extend(scopes)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT split.id, split.created_by, split.created_at, split.mode,
                       split.reviewers_per_issue, split.overlap_ratio,
                       split.assignment_count, split.workset_id,
                       split.selection_source_run_id,
                       workset.baseline_scope, workset.name, workset.member_count,
                       workset.members_sha256
                FROM issue_work_splits split
                JOIN review_worksets workset ON workset.id = split.workset_id
                {where}
                ORDER BY split.created_at DESC, split.id DESC
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"] or ""),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "workset_id": str(row["workset_id"] or ""),
                "member_count": int(row["member_count"] or 0),
                "members_sha256": str(row["members_sha256"] or ""),
                "selection_source_run_id": str(row["selection_source_run_id"] or ""),
                "mode": str(row["mode"] or "single"),
                "reviewers_per_issue": int(row["reviewers_per_issue"] or 1),
                "overlap_ratio": float(row["overlap_ratio"] or 0),
                "assignment_count": int(row["assignment_count"] or 0),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def ensure_label_case(
        self,
        *,
        issue_id: str,
        task_id: str = "",
        source_run_id: str = "",
        created_at: str = "",
    ) -> dict[str, Any]:
        issue_key = str(issue_id or "").strip()
        task = str(task_id or "").strip()
        source_run = str(source_run_id or "").strip()
        with self._write_lock, self.connect() as conn:
            issue = conn.execute(
                "SELECT issue_id, baseline_scope, gt_label, gt_source FROM issues WHERE issue_id = ?",
                (issue_key,),
            ).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在。")
            if task:
                split = conn.execute(
                    "SELECT task_kind, workset_id, selection_source_run_id FROM issue_work_splits WHERE id = ?",
                    (task,),
                ).fetchone()
                if split is None or str(split["task_kind"] or "") != "labeling":
                    raise ValueError("标注任务不存在或尚未启用。")
                if conn.execute(
                    "SELECT 1 FROM review_workset_items WHERE workset_id = ? AND issue_id = ?",
                    (str(split["workset_id"] or ""), issue_key),
                ).fetchone() is None:
                    raise ValueError("Issue 不在该标注任务的冻结工作集中。")
                if not source_run:
                    source_run = str(split["selection_source_run_id"] or "")
            if source_run and conn.execute(
                "SELECT 1 FROM model_runs WHERE id = ?", (source_run,)
            ).fetchone() is None:
                raise ValueError("选样来源 Run 不存在。")
            existing = conn.execute(
                """
                SELECT * FROM label_cases
                WHERE baseline_scope = ? AND issue_id = ? AND task_id = ? AND source_run_id = ?
                """,
                (str(issue["baseline_scope"] or ""), issue_key, task, source_run),
            ).fetchone()
            if existing is not None:
                return self._label_case_dict(existing)
            case_id = f"label-{uuid4().hex}"
            conn.execute(
                """
                INSERT INTO label_cases (
                    id, baseline_scope, issue_id, task_id, source_run_id,
                    seen_gt_label, seen_gt_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope, issue_id, task_id, source_run_id)
                DO NOTHING
                """,
                (
                    case_id,
                    str(issue["baseline_scope"] or ""),
                    issue_key,
                    task,
                    source_run,
                    str(issue["gt_label"] or ""),
                    str(issue["gt_source"] or ""),
                    str(created_at or "").strip() or utc_now(),
                ),
            )
            self._mark_labeling_change(conn)
            row = conn.execute(
                """
                SELECT * FROM label_cases
                WHERE baseline_scope = ? AND issue_id = ?
                  AND task_id = ? AND source_run_id = ?
                """,
                (str(issue["baseline_scope"] or ""), issue_key, task, source_run),
            ).fetchone()
        return self._label_case_dict(row)

    def _label_case_heads(self, conn: Any, label_case_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT revision.* FROM label_revisions revision
            WHERE revision.label_case_id = ?
              AND revision.revision_kind IN ('submission', 'legacy')
              AND revision.id = (
                  SELECT MAX(candidate.id) FROM label_revisions candidate
                  WHERE candidate.label_case_id = revision.label_case_id
                    AND lower(candidate.author) = lower(revision.author)
                    AND candidate.revision_kind IN ('submission', 'legacy')
              )
            ORDER BY lower(revision.author), revision.id
            """,
            (label_case_id,),
        ).fetchall()
        return [self._label_revision_dict(row) for row in rows]

    def _resolve_label_case_with_conn(self, conn: Any, case_row: Any) -> dict[str, Any]:
        case_id = str(case_row["id"])
        task_id = str(case_row["task_id"] or "")
        heads = self._label_case_heads(conn, case_id)
        assigned_authors: list[str] = []
        if task_id:
            assignment_rows = conn.execute(
                """
                SELECT assignee FROM review_work_assignments
                WHERE split_id = ? AND issue_id = ?
                ORDER BY assignee
                """,
                (task_id, str(case_row["issue_id"])),
            ).fetchall()
            assigned_authors = [str(row["assignee"] or "").strip().lower() for row in assignment_rows]
            heads = [item for item in heads if item["author"].strip().lower() in assigned_authors]
        latest_resolution = conn.execute(
            "SELECT * FROM label_resolutions WHERE label_case_id = ? ORDER BY id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        result_row = None
        if latest_resolution is not None:
            result_row = conn.execute(
                "SELECT * FROM label_revisions WHERE id = ? AND label_case_id = ?",
                (int(latest_resolution["result_revision_id"]), case_id),
            ).fetchone()
        return self._resolve_loaded_label_case(
            heads=heads,
            assigned_authors=assigned_authors,
            latest_resolution=latest_resolution,
            result_revision=(
                self._label_revision_dict(result_row) if result_row is not None else None
            ),
        )

    def _resolve_loaded_label_case(
        self,
        *,
        heads: Sequence[dict[str, Any]],
        assigned_authors: Sequence[str],
        latest_resolution: Any = None,
        result_revision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        heads = list(heads)
        assigned_authors = list(assigned_authors)
        source_ids = sorted(int(item["id"]) for item in heads)
        adjudication = None
        if latest_resolution is not None:
            expected_sources = sorted(
                int(value) for value in _json_load(latest_resolution["source_revision_ids_json"], [])
            )
            adjudication = {
                "id": int(latest_resolution["id"]),
                "created_by": str(latest_resolution["created_by"] or ""),
                "created_by_source": str(latest_resolution["created_by_source"] or "legacy"),
                "created_by_verified": bool(latest_resolution["created_by_verified"]),
                "created_at": str(latest_resolution["created_at"] or ""),
                "source_revision_ids": expected_sources,
                "stale": expected_sources != source_ids or result_revision is None,
                "result": result_revision,
            }
            if not adjudication["stale"]:
                output = str(adjudication["result"].get("expected_output") or "")
                return {
                    "state": "resolved",
                    "method": "adjudication",
                    "expected_output": output,
                    "result_revision": adjudication["result"],
                    "heads": heads,
                    "assigned_count": len(assigned_authors) if assigned_authors else len(heads),
                    "submitted_count": len(heads),
                    "adjudication": adjudication,
                }
        assigned_count = len(assigned_authors) if assigned_authors else (1 if heads else 0)
        submitted_count = len(heads)
        valid_outputs = [item["expected_output"] for item in heads if item["expected_output"] in LABELS]
        if adjudication and adjudication["stale"]:
            state = "stale"
            method = "adjudication"
            output = ""
            result_revision = None
        elif not heads or (assigned_authors and submitted_count < assigned_count):
            state = "pending"
            method = "consensus" if assigned_count > 1 else "single"
            output = ""
            result_revision = heads[-1] if heads else None
        elif len(valid_outputs) < submitted_count:
            state = "pending"
            method = "consensus" if assigned_count > 1 else "single"
            output = ""
            result_revision = heads[-1]
        elif len(set(valid_outputs)) > 1:
            state = "conflict"
            method = "consensus"
            output = ""
            result_revision = None
        else:
            state = "resolved"
            method = "consensus" if assigned_count > 1 else "single"
            output = valid_outputs[0] if valid_outputs else ""
            result_revision = max(heads, key=lambda item: int(item["id"]))
        return {
            "state": state,
            "method": method,
            "expected_output": output,
            "result_revision": result_revision,
            "heads": heads,
            "assigned_count": assigned_count,
            "submitted_count": submitted_count,
            "adjudication": adjudication,
        }

    def get_label_case(self, label_case_id: str) -> dict[str, Any] | None:
        normalized = str(label_case_id or "").strip()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM label_cases WHERE id = ?", (normalized,)).fetchone()
            if row is None:
                return None
            revisions = conn.execute(
                "SELECT * FROM label_revisions WHERE label_case_id = ? ORDER BY id DESC",
                (normalized,),
            ).fetchall()
            attachment_rows = conn.execute(
                """
                SELECT attachment.* FROM label_attachments attachment
                JOIN label_revisions revision ON revision.id = attachment.revision_id
                WHERE revision.label_case_id = ?
                ORDER BY attachment.created_at, attachment.id
                """,
                (normalized,),
            ).fetchall()
            resolution = self._resolve_label_case_with_conn(conn, row)
        result = self._label_case_dict(row)
        attachments: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for attachment in attachment_rows:
            attachments[int(attachment["revision_id"])].append(
                self._label_attachment_dict(attachment)
            )
        result["revisions"] = [self._label_revision_dict(item) for item in revisions]
        for revision in result["revisions"]:
            revision["attachments"] = attachments.get(int(revision["id"]), [])
        by_id = {int(item["id"]): item for item in result["revisions"]}
        result["resolution"] = resolution
        if result["resolution"].get("result_revision"):
            resolved_id = int(result["resolution"]["result_revision"]["id"])
            result["resolution"]["result_revision"] = by_id.get(
                resolved_id, result["resolution"]["result_revision"]
            )
        for head_index, head in enumerate(result["resolution"].get("heads") or []):
            result["resolution"]["heads"][head_index] = by_id.get(int(head["id"]), head)
        return result

    def label_cases_for_issue(self, issue_id: str, task_id: str = "") -> list[dict[str, Any]]:
        issue_key = str(issue_id or "").strip()
        task = str(task_id or "").strip()
        clause = "AND task_id = ?" if task else ""
        params: list[Any] = [issue_key]
        if task:
            params.append(task)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM label_cases WHERE issue_id = ? {clause} ORDER BY created_at, id",
                params,
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                item = self._label_case_dict(row)
                item["resolution"] = self._resolve_label_case_with_conn(conn, row)
                results.append(item)
        return results

    def _batch_label_cases(
        self, issue_ids: Sequence[str], task_id: str = ""
    ) -> dict[str, list[dict[str, Any]]]:
        cleaned = list(dict.fromkeys(str(value or "").strip() for value in issue_ids))
        cleaned = [value for value in cleaned if value]
        if not cleaned:
            return {}
        task = str(task_id or "").strip()
        case_rows: list[Any] = []
        revision_rows: list[Any] = []
        resolution_rows: list[Any] = []
        assignment_rows: list[Any] = []
        with self.connect() as conn:
            for offset in range(0, len(cleaned), 400):
                batch = cleaned[offset : offset + 400]
                clause = f"issue_id IN ({', '.join('?' for _ in batch)})"
                params: list[Any] = list(batch)
                if task:
                    clause += " AND task_id = ?"
                    params.append(task)
                case_rows.extend(
                    conn.execute(
                        f"SELECT * FROM label_cases WHERE {clause} ORDER BY created_at, id",
                        params,
                    ).fetchall()
                )
            case_ids = [str(row["id"]) for row in case_rows]
            for offset in range(0, len(case_ids), 400):
                batch = case_ids[offset : offset + 400]
                placeholders = ", ".join("?" for _ in batch)
                revision_rows.extend(
                    conn.execute(
                        f"SELECT * FROM label_revisions WHERE label_case_id IN ({placeholders}) ORDER BY id",
                        batch,
                    ).fetchall()
                )
                resolution_rows.extend(
                    conn.execute(
                        f"SELECT * FROM label_resolutions WHERE label_case_id IN ({placeholders}) ORDER BY id",
                        batch,
                    ).fetchall()
                )
            task_ids = sorted({str(row["task_id"] or "") for row in case_rows if str(row["task_id"] or "")})
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
        revisions_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        revisions_by_id: dict[int, dict[str, Any]] = {}
        for row in revision_rows:
            item = self._label_revision_dict(row)
            revisions_by_case[item["label_case_id"]].append(item)
            revisions_by_id[int(item["id"])] = item
        latest_resolution_by_case: dict[str, Any] = {}
        for row in resolution_rows:
            latest_resolution_by_case[str(row["label_case_id"])] = row
        assigned_by_case: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in assignment_rows:
            assigned_by_case[(str(row["split_id"]), str(row["issue_id"]))].append(
                str(row["assignee"] or "").strip().lower()
            )
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in case_rows:
            case_id = str(row["id"])
            latest_by_author: dict[str, dict[str, Any]] = {}
            for revision in revisions_by_case.get(case_id, []):
                if revision["revision_kind"] not in {"submission", "legacy"}:
                    continue
                latest_by_author[revision["author"].strip().lower()] = revision
            assigned = assigned_by_case.get(
                (str(row["task_id"] or ""), str(row["issue_id"])), []
            )
            heads = list(latest_by_author.values())
            if assigned:
                heads = [item for item in heads if item["author"].strip().lower() in assigned]
            heads.sort(key=lambda item: (item["author"].lower(), int(item["id"])))
            latest_resolution = latest_resolution_by_case.get(case_id)
            result_revision = (
                revisions_by_id.get(int(latest_resolution["result_revision_id"]))
                if latest_resolution is not None
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

    def create_label_revision(
        self,
        *,
        issue_id: str,
        expected_output: str,
        tags: Sequence[str],
        evidence_gaps: Sequence[str],
        rationale: str,
        is_excluded: bool,
        author: str,
        author_source: str,
        author_verified: bool,
        task_id: str = "",
        source_run_id: str = "",
        expected_previous_revision_id: int | None = None,
        attachments: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        label = str(expected_output or "").strip()
        if label and label not in LABELS:
            raise ValueError("期望输出仅支持：误触发、正确触发、无需协助。")
        actor = str(author or "").strip()
        if not actor:
            raise ValueError("标注人不能为空。")
        normalized_rationale = str(rationale or "").strip()
        if len(normalized_rationale) > 8000:
            raise ValueError("标注依据不能超过 8000 个字符。")
        label_case = self.ensure_label_case(
            issue_id=issue_id,
            task_id=task_id,
            source_run_id=source_run_id,
        )
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute(
                    "SELECT id FROM label_cases WHERE id = ? FOR UPDATE",
                    (label_case["id"],),
                ).fetchone()
            if task_id:
                assigned = conn.execute(
                    """
                    SELECT 1 FROM review_work_assignments
                    WHERE split_id = ? AND issue_id = ? AND lower(assignee) = lower(?)
                    """,
                    (task_id, issue_id, actor),
                ).fetchone()
                if assigned is None:
                    raise PermissionError("当前账号不在该标注任务中。")
            previous = conn.execute(
                """
                SELECT id FROM label_revisions
                WHERE label_case_id = ? AND lower(author) = lower(?)
                  AND revision_kind IN ('submission', 'legacy')
                ORDER BY id DESC LIMIT 1
                """,
                (label_case["id"], actor),
            ).fetchone()
            current_id = int(previous["id"]) if previous is not None else None
            if current_id != expected_previous_revision_id:
                raise LabelAnnotationConflictError("标注已被更新，请刷新后再保存。")
            sql = """
                INSERT INTO label_revisions (
                    label_case_id, expected_output, tags_json, evidence_gaps_json,
                    rationale, is_excluded, author, author_source,
                    author_verified, revision_kind, supersedes_id,
                    source_annotation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'submission', ?, NULL, ?)
            """
            if self.backend == "postgresql":
                sql += " RETURNING id"
            cursor = conn.execute(
                sql,
                (
                    label_case["id"],
                    label or None,
                    _json(_clean_values(tags)),
                    _json(_clean_values(evidence_gaps)),
                    normalized_rationale,
                    bool(is_excluded),
                    actor,
                    str(author_source or "legacy").strip() or "legacy",
                    bool(author_verified),
                    current_id,
                    now,
                ),
            )
            revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
            for attachment in attachments:
                conn.execute(
                    """
                    INSERT INTO label_attachments (
                        id, revision_id, source_review_attachment_id,
                        original_name, stored_name, media_type, size_bytes,
                        width, height, sha256, created_at
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(attachment["id"]),
                        revision_id,
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
            self._mark_labeling_change(conn)
            row = conn.execute("SELECT * FROM label_revisions WHERE id = ?", (revision_id,)).fetchone()
        result = self._label_revision_dict(row)
        result["label_case"] = self.get_label_case(label_case["id"])
        return result

    def get_label_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM label_attachments WHERE id = ?",
                (str(attachment_id or "").strip(),),
            ).fetchone()
        return self._label_attachment_dict(row) if row is not None else None

    def adjudicate_label_case(
        self,
        *,
        label_case_id: str,
        source_revision_ids: Sequence[int],
        expected_output: str,
        tags: Sequence[str],
        evidence_gaps: Sequence[str],
        rationale: str,
        is_excluded: bool,
        actor: str,
        actor_source: str,
        actor_verified: bool,
        expected_previous_resolution_id: int | None = None,
    ) -> dict[str, Any]:
        label = str(expected_output or "").strip()
        if label not in LABELS:
            raise ValueError("裁决必须选择有效的期望输出。")
        normalized_rationale = str(rationale or "").strip()
        if len(normalized_rationale) > 8000:
            raise ValueError("裁决依据不能超过 8000 个字符。")
        normalized_sources = sorted({int(value) for value in source_revision_ids})
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            case_row = conn.execute(
                "SELECT * FROM label_cases WHERE id = ?"
                + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                (label_case_id,),
            ).fetchone()
            if case_row is None:
                raise ValueError("标注 Case 不存在。")
            current = self._resolve_label_case_with_conn(conn, case_row)
            if not str(case_row["task_id"] or ""):
                raise ValueError("自由标注无需任务冲突裁决。")
            if current["state"] not in {"conflict", "stale"}:
                raise ValueError("当前任务标注没有需要裁决的冲突。")
            current_sources = sorted(int(item["id"]) for item in current["heads"])
            if normalized_sources != current_sources or not normalized_sources:
                raise LabelAnnotationConflictError("参与裁决的标注版本已变化，请刷新后重新裁决。")
            previous_resolution = conn.execute(
                "SELECT id FROM label_resolutions WHERE label_case_id = ? ORDER BY id DESC LIMIT 1",
                (label_case_id,),
            ).fetchone()
            previous_resolution_id = int(previous_resolution["id"]) if previous_resolution else None
            if previous_resolution_id != expected_previous_resolution_id:
                raise LabelAnnotationConflictError("该 Case 已有更新的裁决，请刷新后重试。")
            previous_actor_revision = conn.execute(
                """
                SELECT id FROM label_revisions
                WHERE label_case_id = ? AND lower(author) = lower(?)
                ORDER BY id DESC LIMIT 1
                """,
                (label_case_id, actor),
            ).fetchone()
            revision_sql = """
                INSERT INTO label_revisions (
                    label_case_id, expected_output, tags_json, evidence_gaps_json,
                    rationale, is_excluded, author, author_source,
                    author_verified, revision_kind, supersedes_id,
                    source_annotation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'adjudication', ?, NULL, ?)
            """
            if self.backend == "postgresql":
                revision_sql += " RETURNING id"
            revision_cursor = conn.execute(
                revision_sql,
                (
                    label_case_id,
                    label,
                    _json(_clean_values(tags)),
                    _json(_clean_values(evidence_gaps)),
                    normalized_rationale,
                    bool(is_excluded),
                    str(actor or "").strip(),
                    str(actor_source or "legacy").strip() or "legacy",
                    bool(actor_verified),
                    int(previous_actor_revision["id"]) if previous_actor_revision else None,
                    now,
                ),
            )
            revision_id = int(revision_cursor.fetchone()["id"]) if self.backend == "postgresql" else int(revision_cursor.lastrowid)
            resolution_sql = """
                INSERT INTO label_resolutions (
                    label_case_id, method, result_revision_id,
                    source_revision_ids_json, source_fingerprint, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, 'adjudication', ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                resolution_sql += " RETURNING id"
            resolution_cursor = conn.execute(
                resolution_sql,
                (
                    label_case_id,
                    revision_id,
                    _json(normalized_sources),
                    _source_fingerprint(normalized_sources),
                    previous_resolution_id,
                    str(actor or "").strip(),
                    str(actor_source or "legacy").strip() or "legacy",
                    bool(actor_verified),
                    now,
                ),
            )
            resolution_id = int(resolution_cursor.fetchone()["id"]) if self.backend == "postgresql" else int(resolution_cursor.lastrowid)
            self._mark_labeling_change(conn)
        result = self.get_label_case(label_case_id)
        if result is None:
            raise RuntimeError("裁决保存后无法读取。")
        result["saved_resolution_id"] = resolution_id
        return result

    def list_labeling_cases(
        self,
        *,
        baseline_scopes: Sequence[str],
        task_id: str = "",
        search: str = "",
        status: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            return {"items": [], "total": 0, "page": 1, "page_size": page_size, "pages": 0}
        task = str(task_id or "").strip()
        parameters: list[Any] = []
        if task:
            from_sql = """
                FROM review_workset_items member
                JOIN issue_work_splits task ON task.workset_id = member.workset_id
                JOIN issues issue ON issue.issue_id = member.issue_id
            """
            where = "task.id = ?"
            parameters.append(task)
        else:
            from_sql = "FROM issues issue"
            where = f"issue.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            parameters.extend(scopes)
        normalized_search = str(search or "").strip()
        if normalized_search:
            where += " AND (issue.issue_id LIKE ? OR issue.title LIKE ? OR issue.scenario LIKE ?)"
            needle = f"%{normalized_search}%"
            parameters.extend((needle, needle, needle))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT issue.issue_id, issue.baseline_scope, issue.gt_label,
                       issue.gt_source, issue.title, issue.scenario
                {from_sql}
                WHERE {where}
                ORDER BY issue.issue_id
                """,
                parameters,
            ).fetchall()
        cases_by_issue = self._batch_label_cases(
            [str(row["issue_id"]) for row in rows], task
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
                expected_output = ""
            elif len(resolved_outputs) == 1:
                aggregate_state = "resolved"
                expected_output = next(iter(resolved_outputs))
            elif any(item["resolution"]["state"] in {"conflict", "stale"} for item in cases):
                aggregate_state = "conflict"
                expected_output = ""
            else:
                aggregate_state = "pending"
                expected_output = ""
            if status != "all" and aggregate_state != status:
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
                    "expected_output": expected_output,
                    "source_count": len(cases),
                    "label_cases": cases,
                }
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
        }

    def label_gt_candidates(self, baseline_scopes: Sequence[str]) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT issue_id, gt_label FROM issues WHERE baseline_scope IN ({', '.join('?' for _ in scopes)}) ORDER BY issue_id",
                scopes,
            ).fetchall() if scopes else []
        cases_by_issue = self._batch_label_cases([str(row["issue_id"]) for row in rows])
        gt_by_issue = {str(row["issue_id"]): str(row["gt_label"] or "") for row in rows}
        by_issue: dict[str, list[dict[str, Any]]] = {}
        blocked_by_issue: dict[str, list[dict[str, Any]]] = {}
        for issue_id, label_cases in cases_by_issue.items():
            for row in label_cases:
                resolution = row["resolution"]
                if resolution["state"] == "resolved" and resolution["expected_output"] in LABELS:
                    by_issue.setdefault(issue_id, []).append(
                        {
                            "label_case_id": str(row["id"]),
                            "task_id": str(row["task_id"] or ""),
                            "source_run_id": str(row["source_run_id"] or ""),
                            "expected_output": resolution["expected_output"],
                            "method": resolution["method"],
                            "result_revision_id": int(resolution["result_revision"]["id"]),
                        }
                    )
                else:
                    blocked_by_issue.setdefault(issue_id, []).append(
                        {
                            "label_case_id": str(row["id"]),
                            "task_id": str(row["task_id"] or ""),
                            "source_run_id": str(row["source_run_id"] or ""),
                            "state": str(resolution["state"] or "pending"),
                            "submitted_count": int(resolution["submitted_count"] or 0),
                            "assigned_count": int(resolution["assigned_count"] or 0),
                        }
                    )
        output: list[dict[str, Any]] = []
        for issue_id in sorted(set(by_issue) | set(blocked_by_issue)):
            sources = by_issue.get(issue_id, [])
            labels = {item["expected_output"] for item in sources}
            gt_label = gt_by_issue.get(issue_id, "")
            blockers = blocked_by_issue.get(issue_id, [])
            if blockers:
                output.append(
                    {
                        "issue_id": issue_id,
                        "status": "unresolved",
                        "gt_label": gt_label,
                        "sources": sources,
                        "blocked_sources": blockers,
                    }
                )
                continue
            if len(labels) > 1:
                output.append(
                    {"issue_id": issue_id, "status": "source_conflict", "gt_label": gt_label, "sources": sources}
                )
                continue
            expected = next(iter(labels))
            if expected == gt_label:
                continue
            output.append(
                {
                    "issue_id": issue_id,
                    "status": "ready",
                    "gt_label": gt_label,
                    "expected_output": expected,
                    "sources": sources,
                }
            )
        return output

    @staticmethod
    def _gt_candidate_fingerprint(candidate: dict[str, Any]) -> str:
        payload = {
            "issue_id": str(candidate.get("issue_id") or ""),
            "gt_label": str(candidate.get("gt_label") or ""),
            "expected_output": str(candidate.get("expected_output") or ""),
            "source_revision_ids": sorted(
                int(item.get("result_revision_id") or 0)
                for item in candidate.get("sources") or []
                if int(item.get("result_revision_id") or 0) > 0
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def create_label_gt_export_preview(
        self,
        *,
        baseline_scopes: Sequence[str],
        issue_ids: Sequence[str] = (),
        created_by: str,
        created_by_source: str,
        created_by_verified: bool,
    ) -> dict[str, Any]:
        scopes = _clean_values(baseline_scopes)
        selected = set(_clean_values(issue_ids))
        candidates = [
            item for item in self.label_gt_candidates(scopes)
            if item.get("status") == "ready"
            and (not selected or str(item.get("issue_id") or "") in selected)
        ]
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            fingerprint = self._gt_candidate_fingerprint(candidate)
            items.append(
                {
                    "issue_id": str(candidate["issue_id"]),
                    "old_gt_label": str(candidate.get("gt_label") or ""),
                    "expected_output": str(candidate["expected_output"]),
                    "source_revision_ids": sorted(
                        int(source["result_revision_id"])
                        for source in candidate.get("sources") or []
                    ),
                    "source_fingerprint": fingerprint,
                }
            )
        batch_fingerprint = hashlib.sha256(
            "\n".join(item["source_fingerprint"] for item in items).encode("utf-8")
        ).hexdigest()
        batch_id = f"gt-export-{uuid4().hex}"
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO label_gt_export_batches (
                    id, baseline_scopes_json, source_fingerprint, status,
                    item_count, file_sha256, created_by, created_by_source,
                    created_by_verified, created_at, exported_at
                ) VALUES (?, ?, ?, 'preview', ?, '', ?, ?, ?, ?, NULL)
                """,
                (
                    batch_id,
                    _json(scopes),
                    batch_fingerprint,
                    len(items),
                    str(created_by or ""),
                    str(created_by_source or "legacy"),
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO label_gt_export_items (
                    batch_id, issue_id, old_gt_label, expected_output,
                    source_revision_ids_json, source_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        batch_id,
                        item["issue_id"],
                        item["old_gt_label"],
                        item["expected_output"],
                        _json(item["source_revision_ids"]),
                        item["source_fingerprint"],
                    )
                    for item in items
                ],
            )
            self._mark_labeling_change(conn)
        return {
            "id": batch_id,
            "status": "preview",
            "baseline_scopes": scopes,
            "source_fingerprint": batch_fingerprint,
            "item_count": len(items),
            "items": items,
            "created_by": str(created_by or ""),
            "created_at": now,
        }

    def get_label_gt_export_batch(self, batch_id: str) -> dict[str, Any] | None:
        normalized = str(batch_id or "").strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM label_gt_export_batches WHERE id = ?", (normalized,)
            ).fetchone()
            if row is None:
                return None
            item_rows = conn.execute(
                "SELECT * FROM label_gt_export_items WHERE batch_id = ? ORDER BY issue_id",
                (normalized,),
            ).fetchall()
        return {
            "id": str(row["id"]),
            "baseline_scopes": _json_load(row["baseline_scopes_json"], []),
            "source_fingerprint": str(row["source_fingerprint"] or ""),
            "status": str(row["status"] or "preview"),
            "item_count": int(row["item_count"] or 0),
            "file_sha256": str(row["file_sha256"] or ""),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "exported_at": str(row["exported_at"] or ""),
            "items": [
                {
                    "issue_id": str(item["issue_id"]),
                    "old_gt_label": str(item["old_gt_label"] or ""),
                    "expected_output": str(item["expected_output"] or ""),
                    "source_revision_ids": _json_load(item["source_revision_ids_json"], []),
                    "source_fingerprint": str(item["source_fingerprint"] or ""),
                }
                for item in item_rows
            ],
        }

    def validate_label_gt_export_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.get_label_gt_export_batch(batch_id)
        if batch is None:
            raise ValueError("GT 更新导出批次不存在。")
        current = {
            str(item["issue_id"]): item
            for item in self.label_gt_candidates(batch["baseline_scopes"])
            if item.get("status") == "ready"
        }
        stale: list[str] = []
        for item in batch["items"]:
            candidate = current.get(item["issue_id"])
            if candidate is None or self._gt_candidate_fingerprint(candidate) != item["source_fingerprint"]:
                stale.append(item["issue_id"])
        if stale:
            with self._write_lock, self.connect() as conn:
                conn.execute(
                    "UPDATE label_gt_export_batches SET status = 'stale' WHERE id = ?",
                    (batch["id"],),
                )
                self._mark_labeling_change(conn)
            batch["status"] = "stale"
        batch["stale_issue_ids"] = stale
        return batch

    def mark_label_gt_exported(self, *, batch_id: str, file_sha256: str) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE label_gt_export_batches
                SET status = 'exported', file_sha256 = ?, exported_at = ?
                WHERE id = ? AND status = 'preview'
                """,
                (str(file_sha256 or ""), now, str(batch_id or "")),
            )
            self._mark_labeling_change(conn)
        return self.get_label_gt_export_batch(batch_id) or {}

    def record_label_migration_map(
        self,
        *,
        source_table: str,
        source_id: str,
        target_table: str,
        target_id: str,
        policy_version: str,
    ) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO label_migration_map (
                    source_table, source_id, target_table, target_id,
                    policy_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_table, source_id, target_table, policy_version)
                DO UPDATE SET target_id = excluded.target_id
                """,
                (
                    str(source_table), str(source_id), str(target_table), str(target_id),
                    str(policy_version), utc_now(),
                ),
            )

    def link_label_comment(
        self,
        *,
        comment_id: int,
        task_id: str = "",
        source_run_id: str = "",
        policy_version: str,
    ) -> None:
        with self._write_lock, self.connect() as conn:
            comment = conn.execute(
                """
                SELECT comment.issue_id, issue.baseline_scope
                FROM review_comments comment
                JOIN issues issue ON issue.issue_id = comment.issue_id
                WHERE comment.id = ?
                """,
                (int(comment_id),),
            ).fetchone()
            if comment is None:
                raise ValueError("讨论消息不存在。")
            conn.execute(
                """
                INSERT INTO label_comment_links (
                    comment_id, baseline_scope, issue_id, task_id,
                    source_run_id, policy_version, linked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(comment_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    source_run_id = excluded.source_run_id,
                    policy_version = excluded.policy_version
                """,
                (
                    int(comment_id),
                    str(comment["baseline_scope"] or ""),
                    str(comment["issue_id"] or ""),
                    str(task_id or ""),
                    str(source_run_id or ""),
                    str(policy_version or ""),
                    utc_now(),
                ),
            )
            self._mark_labeling_change(conn)

    def list_label_comments(self, *, issue_id: str, task_id: str = "") -> list[dict[str, Any]]:
        task = str(task_id or "").strip()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT comment.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body, link.task_id,
                       link.source_run_id, link.policy_version
                FROM label_comment_links link
                JOIN review_comments comment ON comment.id = link.comment_id
                LEFT JOIN review_comments parent ON parent.id = comment.reply_to_id
                WHERE link.issue_id = ? AND link.task_id = ?
                ORDER BY comment.id
                """,
                (str(issue_id or "").strip(), task),
            ).fetchall()
            attachments = self._comment_attachments_for_rows(conn, rows)
        comments: list[dict[str, Any]] = []
        for row in rows:
            item = self._review_comment_dict(
                row, attachments=attachments.get(int(row["id"]), [])
            )
            item["label_task_id"] = str(row["task_id"] or "")
            item["source_run_id"] = str(row["source_run_id"] or "")
            item["migration_policy_version"] = str(row["policy_version"] or "")
            comments.append(item)
        return comments

    def migrate_legacy_label_revision(
        self,
        *,
        label_case_id: str,
        source_annotation_id: int,
        expected_output: str,
        tags: Sequence[str],
        evidence_gaps: Sequence[str],
        rationale: str,
        is_excluded: bool,
        author: str,
        author_source: str,
        author_verified: bool,
        supersedes_source_annotation_id: int | None,
        created_at: str,
        policy_version: str,
    ) -> int:
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM label_revisions WHERE source_annotation_id = ?",
                (int(source_annotation_id),),
            ).fetchone()
            if existing is not None:
                revision_id = int(existing["id"])
            else:
                supersedes_id = None
                if supersedes_source_annotation_id:
                    predecessor = conn.execute(
                        "SELECT id FROM label_revisions WHERE source_annotation_id = ?",
                        (int(supersedes_source_annotation_id),),
                    ).fetchone()
                    supersedes_id = int(predecessor["id"]) if predecessor else None
                sql = """
                    INSERT INTO label_revisions (
                        label_case_id, expected_output, tags_json, evidence_gaps_json,
                        rationale, is_excluded, author, author_source,
                        author_verified, revision_kind, supersedes_id,
                        source_annotation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', ?, ?, ?)
                """
                if self.backend == "postgresql":
                    sql += " RETURNING id"
                cursor = conn.execute(
                    sql,
                    (
                        label_case_id,
                        expected_output if expected_output in LABELS else None,
                        _json(_clean_values(tags)),
                        _json(_clean_values(evidence_gaps)),
                        str(rationale or ""),
                        bool(is_excluded),
                        str(author or ""),
                        str(author_source or "legacy"),
                        bool(author_verified),
                        supersedes_id,
                        int(source_annotation_id),
                        str(created_at or "") or utc_now(),
                    ),
                )
                revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO label_migration_map (
                    source_table, source_id, target_table, target_id,
                    policy_version, created_at
                ) VALUES ('annotations', ?, 'label_revisions', ?, ?, ?)
                ON CONFLICT(source_table, source_id, target_table, policy_version)
                DO UPDATE SET target_id = excluded.target_id
                """,
                (str(source_annotation_id), str(revision_id), str(policy_version), utc_now()),
            )
            source_attachments = conn.execute(
                "SELECT * FROM review_attachments WHERE annotation_id = ? ORDER BY created_at, id",
                (int(source_annotation_id),),
            ).fetchall()
            for attachment in source_attachments:
                conn.execute(
                    """
                    INSERT INTO label_attachments (
                        id, revision_id, source_review_attachment_id,
                        original_name, stored_name, media_type, size_bytes,
                        width, height, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_review_attachment_id) DO NOTHING
                    """,
                    (
                        str(attachment["id"]),
                        revision_id,
                        str(attachment["id"]),
                        str(attachment["original_name"] or ""),
                        str(attachment["stored_name"] or ""),
                        str(attachment["media_type"] or ""),
                        int(attachment["size_bytes"] or 0),
                        int(attachment["width"] or 0),
                        int(attachment["height"] or 0),
                        str(attachment["sha256"] or ""),
                        str(attachment["created_at"] or "") or utc_now(),
                    ),
                )
            self._mark_labeling_change(conn)
        return revision_id
