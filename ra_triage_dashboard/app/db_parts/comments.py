from __future__ import annotations

from typing import Any

from .shared import _json, _json_load, utc_now


class DatabaseCommentsMixin:
    """Append-only discussion threads scoped to one Issue and model Run."""

    @staticmethod
    def _comment_channel_scope(
        *, discussion_channel: str | None, model_run_id: str = "",
        campaign_id: str = "", baseline_scope: str = "",
    ) -> tuple[str, str, str, str]:
        run_id = str(model_run_id or "").strip()
        channel = str(discussion_channel or ("model_review" if run_id else "case")).strip().lower()
        campaign_key = str(campaign_id or "").strip()
        scope = str(baseline_scope or "").strip()
        if channel not in {"case", "campaign", "model_review", "legacy"}:
            raise ValueError("discussion_channel 不合法。")
        if channel == "model_review":
            if not run_id:
                run_id = str(model_run_id or "").strip()
            if not run_id:
                raise ValueError("Model Review 讨论必须绑定 Model Run。")
            if campaign_key:
                raise ValueError("Model Review 讨论不能绑定 Campaign ID。")
        elif channel == "campaign":
            if not campaign_key or run_id:
                raise ValueError("Campaign 讨论必须绑定 Campaign 且不能绑定 Model Run。")
        elif channel == "case":
            if run_id or campaign_key:
                raise ValueError("Case 讨论只按 baseline scope 与 Issue 隔离。")
        return channel, campaign_key, scope, run_id

    def list_review_comments(
        self, *, issue_id: str, model_run_id: str = "", limit: int = 200,
        discussion_channel: str | None = None, campaign_id: str = "",
        baseline_scope: str = "",
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        channel, campaign_key, scope, run_id = self._comment_channel_scope(
            discussion_channel=discussion_channel, model_run_id=model_run_id,
            campaign_id=campaign_id, baseline_scope=baseline_scope,
        )
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body
                FROM review_comments c
                LEFT JOIN review_comments parent ON parent.id = c.reply_to_id
                WHERE c.issue_id = ? AND c.discussion_channel = ?
                  AND c.campaign_id = ? AND c.evaluation_run_id = ?
                  AND (? = '' OR c.baseline_scope = ?)
                ORDER BY c.id ASC
                LIMIT ?
                """,
                (issue_id, channel, campaign_key, run_id, scope, scope, bounded_limit),
            ).fetchall()
            attachments = self._comment_attachments_for_rows(conn, rows)
        return [
            self._review_comment_dict(
                row, attachments=attachments.get(int(row["id"]), [])
            )
            for row in rows
        ]

    def review_comment_count(
        self, *, issue_id: str, model_run_id: str = "",
        discussion_channel: str | None = None, campaign_id: str = "",
        baseline_scope: str = "",
    ) -> int:
        channel, campaign_key, scope, run_id = self._comment_channel_scope(
            discussion_channel=discussion_channel, model_run_id=model_run_id,
            campaign_id=campaign_id, baseline_scope=baseline_scope,
        )
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM review_comments
                WHERE issue_id = ? AND discussion_channel = ?
                  AND campaign_id = ? AND evaluation_run_id = ?
                  AND (? = '' OR baseline_scope = ?)
                """,
                (issue_id, channel, campaign_key, run_id, scope, scope),
            ).fetchone()
        return int(row["count"] if row else 0)

    def review_comment_issue_ids(
        self,
        *,
        issue_ids: list[str],
        model_run_id: str = "",
        search: str = "",
        discussion_channel: str = "model_review",
    ) -> set[str]:
        """Return bounded Issue ids with a matching comment in one Run."""

        cleaned = list(dict.fromkeys(
            str(issue_id or "").strip() for issue_id in issue_ids
            if str(issue_id or "").strip()
        ))
        if not cleaned:
            return set()
        result: set[str] = set()
        query = str(search or "").strip()[:256]
        with self.connect() as conn:
            for offset in range(0, len(cleaned), 500):
                batch = cleaned[offset : offset + 500]
                where = [
                    f"issue_id IN ({', '.join('?' for _ in batch)})",
                    "discussion_channel = ?",
                    "evaluation_run_id = ?",
                ]
                params: list[Any] = [*batch, discussion_channel, str(model_run_id or "").strip()]
                if query:
                    where.append("body LIKE ?")
                    params.append(f"%{query}%")
                rows = conn.execute(
                    f"SELECT DISTINCT issue_id FROM review_comments WHERE {' AND '.join(where)}",
                    params,
                ).fetchall()
                result.update(str(row["issue_id"] or "") for row in rows)
        return result

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
        discussion_channel: str | None = None,
        campaign_id: str = "",
        baseline_scope: str = "",
        evaluation_run_id: str = "",
        mentions: list[str] | None = None,
        notification_recipients: list[str] | None = None,
        reply_to_id: int | None = None,
        attachments: list[dict[str, Any]] | None = None,
        require_existing_model_run: bool = True,
    ) -> dict[str, Any]:
        normalized_body = str(body or "").strip()
        if not normalized_body:
            raise ValueError("评论内容不能为空。")
        if len(normalized_body) > 3500:
            raise ValueError("评论内容不能超过 3500 个字符。")
        normalized_author = str(author or "").strip()
        if not normalized_author:
            raise ValueError("评论人不能为空。")
        normalized_run_id = str(evaluation_run_id or model_run_id or "").strip()
        channel, campaign_key, scope, normalized_run_id = self._comment_channel_scope(
            discussion_channel=discussion_channel, model_run_id=normalized_run_id,
            campaign_id=campaign_id, baseline_scope=baseline_scope,
        )
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
                "SELECT issue_id, baseline_scope FROM issues WHERE issue_id = ?", (issue_id,)
            ).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在。")
            issue_scope = str(issue["baseline_scope"] or "")
            if channel == "case":
                if scope and scope != issue_scope:
                    raise ValueError("Case 讨论 baseline scope 与 Issue 不匹配。")
                scope = issue_scope
            elif channel == "campaign":
                campaign = conn.execute(
                    "SELECT purpose, lifecycle, legacy_read_only FROM issue_work_splits WHERE id = ?",
                    (campaign_key,),
                ).fetchone()
                member = conn.execute(
                    "SELECT baseline_scope FROM campaign_issue_members WHERE campaign_id = ? AND issue_id = ?",
                    (campaign_key, issue_id),
                ).fetchone()
                if campaign is None or member is None or str(member["baseline_scope"] or "") != issue_scope:
                    raise ValueError("Issue 不属于指定 Campaign。")
                if bool(campaign["legacy_read_only"]) or str(campaign["lifecycle"] or "") != "active":
                    raise ValueError("该 Campaign 当前只读，不能新增讨论。")
                if scope and scope != issue_scope:
                    raise ValueError("Campaign 讨论 baseline scope 与 Issue 不匹配。")
                scope = issue_scope
            if channel == "model_review" and normalized_run_id and require_existing_model_run:
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
                    or str(parent["discussion_channel"] or "legacy") != channel
                    or str(parent["campaign_id"] or "") != campaign_key
                    or str(parent["evaluation_run_id"] or "") != normalized_run_id
                    or (scope and str(parent["baseline_scope"] or "") != scope)
                ):
                    raise ValueError("只能回复当前 Issue 与讨论频道下的评论。")
            insert_sql = """
                INSERT INTO review_comments (
                    issue_id, model_run_id, body, author, author_source,
                    author_verified, mentions_json, reply_to_id, created_at,
                    discussion_channel, campaign_id, baseline_scope,
                    evaluation_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    channel,
                    campaign_key,
                    scope,
                    normalized_run_id,
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
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM comment_attachments) +
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM label_attachments
                     WHERE source_review_attachment_id IS NULL)
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
            "discussion_channel": str(row["discussion_channel"] or "legacy")
            if "discussion_channel" in keys
            else ("model_review" if str(row["model_run_id"] or "") else "case"),
            "campaign_id": str(row["campaign_id"] or "")
            if "campaign_id" in keys
            else "",
            "baseline_scope": str(row["baseline_scope"] or "")
            if "baseline_scope" in keys
            else "",
            "evaluation_run_id": str(row["evaluation_run_id"] or "")
            if "evaluation_run_id" in keys
            else str(row["model_run_id"] or ""),
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
