"""Labeling records storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Sequence
from uuid import uuid4
from .shared import (
    LABELS,
    LabelAnnotationConflictError,
    _json,
    _json_load,
    utc_now,
)
from .labeling_shared import _clean_values


class LabelingRecordsMixin:
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

    def ensure_label_case(
        self,
        *,
        issue_id: str,
        task_id: str = "",
        source_run_id: str = "",
        created_at: str = "",
        allow_missing_source_run: bool = False,
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
                    "SELECT split.task_kind, split.workset_id, split.selection_source_run_id, "
                    "split.purpose, split.lifecycle, split.legacy_read_only, "
                    "workset.selection_source_run_id AS workset_selection_source_run_id "
                    "FROM issue_work_splits split LEFT JOIN review_worksets workset "
                    "ON workset.id = split.workset_id WHERE split.id = ?",
                    (task,),
                ).fetchone()
                if split is None or str(split["task_kind"] or "") != "labeling":
                    raise ValueError("标注任务不存在或尚未启用。")
                if (
                    str(split["lifecycle"] or "active") != "active"
                    or bool(split["legacy_read_only"])
                    or str(split["purpose"] or "labeling") != "labeling"
                ):
                    raise ValueError("该 Campaign 当前只读，不能创建 Label Case。")
                if conn.execute(
                    "SELECT 1 FROM review_workset_items WHERE workset_id = ? AND issue_id = ?",
                    (str(split["workset_id"] or ""), issue_key),
                ).fetchone() is None:
                    raise ValueError("Issue 不在该标注任务的冻结工作集中。")
                if not source_run:
                    source_run = str(
                        split["workset_selection_source_run_id"]
                        or split["selection_source_run_id"] or ""
                    )
            if source_run and not allow_missing_source_run and conn.execute(
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
                campaign = conn.execute(
                    "SELECT purpose, lifecycle, legacy_read_only FROM issue_work_splits WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if (
                    campaign is None
                    or bool(campaign["legacy_read_only"])
                    or str(campaign["lifecycle"] or "active") != "active"
                    or str(campaign["purpose"] or "labeling") != "labeling"
                ):
                    raise ValueError("该 Campaign 当前只读，不能提交标注。")
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
                """
                SELECT attachment.*, label_case.issue_id, label_case.baseline_scope
                FROM label_attachments attachment
                JOIN label_revisions revision ON revision.id = attachment.revision_id
                JOIN label_cases label_case ON label_case.id = revision.label_case_id
                WHERE attachment.id = ?
                """,
                (str(attachment_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return {
            **self._label_attachment_dict(row),
            "issue_id": str(row["issue_id"]),
            "baseline_scope": str(row["baseline_scope"]),
        }
