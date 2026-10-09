"""Labeling migration storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from typing import Any, Sequence
from .shared import LABELS, _json, _json_load, utc_now
from .labeling_shared import _clean_values


class LabelingMigrationMixin:
    def list_label_import_batches(
        self, baseline_scopes: Sequence[str] = (), source_type: str = ""
    ) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        clauses = ["status = 'imported'"]
        params: list[Any] = []
        if scopes:
            clauses.append(f"baseline_scope IN ({', '.join('?' for _ in scopes)})")
            params.extend(scopes)
        normalized_source = str(source_type or "").strip()
        if normalized_source:
            clauses.append("source_type = ?")
            params.append(normalized_source)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM label_import_batches WHERE {' AND '.join(clauses)} ORDER BY imported_at DESC, id",
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "name": str(row["name"] or ""),
                "source_type": str(row["source_type"] or ""),
                "migration_version": str(row["migration_version"] or ""),
                "status": str(row["status"] or ""),
                "source_inventory_sha256": str(row["source_inventory_sha256"] or ""),
                "stats": _json_load(row["stats_json"], {}),
                "imported_by": str(row["imported_by"] or ""),
                "created_at": str(row["created_at"] or ""),
                "imported_at": str(row["imported_at"] or ""),
            }
            for row in rows
        ]

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

    def get_label_comment_link(self, comment_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM label_comment_links WHERE comment_id = ?",
                (int(comment_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_label_comments(
        self, *, issue_id: str, task_id: str = "", discussion_channel: str = "both"
    ) -> list[dict[str, Any]]:
        task = str(task_id or "").strip()
        issue = str(issue_id or "").strip()
        channel = str(discussion_channel or "both").strip().lower()
        if channel not in {"both", "case", "campaign"}:
            raise ValueError("标注讨论频道不合法。")
        query = """
                SELECT comment.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body,
                       COALESCE(link.task_id, '') AS task_id,
                       COALESCE(link.source_run_id, '') AS source_run_id,
                       COALESCE(link.policy_version, '') AS policy_version
                FROM review_comments comment
                JOIN issues issue ON issue.issue_id = comment.issue_id
                LEFT JOIN label_comment_links link ON link.comment_id = comment.id
                LEFT JOIN review_comments parent ON parent.id = comment.reply_to_id
                WHERE comment.issue_id = ?
                  AND comment.baseline_scope = issue.baseline_scope
                  AND (link.comment_id IS NOT NULL OR comment.discussion_channel = 'case')
                """
        params: tuple[Any, ...] = (issue,)
        if channel == "case":
            query += " AND comment.discussion_channel = 'case'"
        elif channel == "campaign":
            if not task:
                return []
            query += " AND comment.discussion_channel = 'campaign' AND COALESCE(link.task_id, '') = ?"
            params = (issue, task)
        elif task:
            query += " AND (comment.discussion_channel = 'case' OR (comment.discussion_channel = 'campaign' AND COALESCE(link.task_id, '') = ?))"
            params = (issue, task)
        query += " ORDER BY comment.id"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
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
