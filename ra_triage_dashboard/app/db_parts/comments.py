from __future__ import annotations

from typing import Any

from .shared import _json, _json_load, utc_now


class DatabaseCommentsMixin:
    """Append-only discussion threads scoped to one Issue and model Run."""

    def list_review_comments(
        self, *, issue_id: str, model_run_id: str = "", limit: int = 200
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body
                FROM review_comments c
                LEFT JOIN review_comments parent ON parent.id = c.reply_to_id
                WHERE c.issue_id = ? AND c.model_run_id = ?
                ORDER BY c.id ASC
                LIMIT ?
                """,
                (issue_id, str(model_run_id or "").strip(), bounded_limit),
            ).fetchall()
            attachments = self._comment_attachments_for_rows(conn, rows)
        return [
            self._review_comment_dict(
                row, attachments=attachments.get(int(row["id"]), [])
            )
            for row in rows
        ]

    def review_comment_count(self, *, issue_id: str, model_run_id: str = "") -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM review_comments
                WHERE issue_id = ? AND model_run_id = ?
                """,
                (issue_id, str(model_run_id or "").strip()),
            ).fetchone()
        return int(row["count"] if row else 0)

    def get_review_comment(self, comment_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body
                FROM review_comments c
                LEFT JOIN review_comments parent ON parent.id = c.reply_to_id
                WHERE c.id = ?
                """,
                (int(comment_id),),
            ).fetchone()
            attachments = self._comment_attachments_for_rows(
                conn, [row] if row else []
            )
        return (
            self._review_comment_dict(
                row, attachments=attachments.get(int(row["id"]), [])
            )
            if row
            else None
        )

    def create_review_comment(
        self,
        *,
        issue_id: str,
        model_run_id: str = "",
        body: str,
        author: str,
        author_source: str = "legacy",
        author_verified: bool = False,
        mentions: list[str] | None = None,
        notification_recipients: list[str] | None = None,
        reply_to_id: int | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_body = str(body or "").strip()
        if not normalized_body:
            raise ValueError("评论内容不能为空。")
        if len(normalized_body) > 3500:
            raise ValueError("评论内容不能超过 3500 个字符。")
        normalized_author = str(author or "").strip()
        if not normalized_author:
            raise ValueError("评论人不能为空。")
        normalized_run_id = str(model_run_id or "").strip()
        normalized_mentions = list(
            dict.fromkeys(
                str(item).strip().lower()
                for item in (mentions or [])
                if str(item).strip()
            )
        )
        recipients = list(
            dict.fromkeys(
                str(item).strip().lower()
                for item in (notification_recipients or [])
                if str(item).strip()
            )
        )
        attachments = attachments or []
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            issue = conn.execute(
                "SELECT issue_id FROM issues WHERE issue_id = ?", (issue_id,)
            ).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在。")
            if normalized_run_id:
                run = conn.execute(
                    "SELECT id FROM model_runs WHERE id = ?", (normalized_run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError("模型 Run 不存在。")
            parent = None
            if reply_to_id is not None:
                parent = conn.execute(
                    "SELECT * FROM review_comments WHERE id = ?", (int(reply_to_id),)
                ).fetchone()
                if parent is None:
                    raise ValueError("回复的评论不存在。")
                if (
                    str(parent["issue_id"]) != issue_id
                    or str(parent["model_run_id"] or "") != normalized_run_id
                ):
                    raise ValueError("只能回复当前 Issue 与 Model Run 下的评论。")
            insert_sql = """
                INSERT INTO review_comments (
                    issue_id, model_run_id, body, author, author_source,
                    author_verified, mentions_json, reply_to_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                insert_sql += " RETURNING id"
            cursor = conn.execute(
                insert_sql,
                (
                    issue_id,
                    normalized_run_id,
                    normalized_body,
                    normalized_author,
                    str(author_source or "legacy").strip() or "legacy",
                    bool(author_verified),
                    _json(normalized_mentions),
                    int(reply_to_id) if reply_to_id is not None else None,
                    now,
                ),
            )
            comment_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            for attachment in attachments:
                conn.execute(
                    """
                    INSERT INTO comment_attachments (
                        id, comment_id, original_name, stored_name, media_type,
                        size_bytes, width, height, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attachment["id"],
                        comment_id,
                        attachment.get("original_name", ""),
                        attachment["stored_name"],
                        attachment["media_type"],
                        int(attachment["size_bytes"]),
                        int(attachment["width"]),
                        int(attachment["height"]),
                        attachment["sha256"],
                        now,
                    ),
                )
            for recipient in recipients:
                conn.execute(
                    """
                    INSERT INTO comment_notifications (
                        comment_id, issue_id, recipient, status, attempt_count,
                        next_attempt_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
                    ON CONFLICT(comment_id, recipient) DO NOTHING
                    """,
                    (comment_id, issue_id, recipient, now, now, now),
                )
            row = conn.execute(
                """
                SELECT c.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body
                FROM review_comments c
                LEFT JOIN review_comments parent ON parent.id = c.reply_to_id
                WHERE c.id = ?
                """,
                (comment_id,),
            ).fetchone()
        return self._review_comment_dict(row, attachments=attachments)

    def get_comment_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM comment_attachments WHERE id = ?",
                (str(attachment_id or "").strip(),),
            ).fetchone()
        return self._comment_attachment_dict(row) if row else None

    def image_attachment_storage_bytes(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM review_attachments) +
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM comment_attachments)
                    AS total
                """
            ).fetchone()
        return int(row["total"] or 0)

    @classmethod
    def _comment_attachments_for_rows(
        cls, conn: Any, rows: list[Any]
    ) -> dict[int, list[dict[str, Any]]]:
        comment_ids = [int(row["id"]) for row in rows if row]
        if not comment_ids:
            return {}
        placeholders = ",".join("?" for _ in comment_ids)
        attachment_rows = conn.execute(
            f"""
            SELECT * FROM comment_attachments
            WHERE comment_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            """,
            comment_ids,
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for attachment in attachment_rows:
            grouped.setdefault(int(attachment["comment_id"]), []).append(
                cls._comment_attachment_dict(attachment)
            )
        return grouped

    @staticmethod
    def _comment_attachment_dict(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "comment_id": int(row["comment_id"]),
            "original_name": str(row["original_name"] or ""),
            "stored_name": str(row["stored_name"]),
            "media_type": str(row["media_type"]),
            "size_bytes": int(row["size_bytes"]),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "sha256": str(row["sha256"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _review_comment_dict(
        row: Any, *, attachments: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": int(row["id"]),
            "issue_id": str(row["issue_id"]),
            "model_run_id": str(row["model_run_id"] or ""),
            "body": str(row["body"] or ""),
            "author": str(row["author"] or ""),
            "author_source": str(row["author_source"] or "legacy"),
            "author_verified": bool(row["author_verified"]),
            "mentions": _json_load(row["mentions_json"], []),
            "reply_to_id": int(row["reply_to_id"]) if row["reply_to_id"] else None,
            "reply_to_author": str(row["reply_to_author"] or "")
            if "reply_to_author" in keys
            else "",
            "reply_to_body": str(row["reply_to_body"] or "")
            if "reply_to_body" in keys
            else "",
            "attachments": list(attachments or []),
            "created_at": str(row["created_at"]),
        }
