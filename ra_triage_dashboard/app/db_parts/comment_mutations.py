"""Versioned comment changes; the original text remains in the private audit trail."""
from __future__ import annotations

import re
from typing import Any

from .shared import _json, _json_load, utc_now


class CommentConflictError(ValueError):
    pass


class CommentMissingError(LookupError):
    pass


def comment_metadata(row: Any) -> dict[str, Any]:
    keys = set(row.keys())
    value = lambda key, default=None: row[key] if key in keys else default
    return {
        "version": int(value("version", 1)),
        "edited_at": str(value("edited_at") or ""),
        "deleted_at": str(value("deleted_at") or ""),
        "deleted": bool(value("deleted_at")),
        "reply_to_deleted": bool(value("reply_to_deleted_at")),
        # This prefix is reserved for immutable label-revision evidence.
        "is_label_evidence": bool(value("author_verified") and not value("reply_to_id")
            and re.match(r"\AIssue 标签 #[1-9][0-9]* · 标注依据 / Label rationale\n", str(value("body", "")))),
    }


class DatabaseCommentMutationsMixin:
    @staticmethod
    def _comment_table(kind: str) -> str:
        if kind not in {"review", "intent"}:
            raise ValueError("Unknown comment kind")
        return "review_comments" if kind == "review" else "intent_case_comments"

    def _manageable_comment(self, conn, *, kind: str, comment_id: int, issue_id: str,
                            dataset_id: str, actor: str, actor_verified: bool,
                            is_admin: bool) -> Any:
        table = self._comment_table(kind)
        scope = "issue_id = ?" if kind == "review" else "case_id = ? AND dataset_id = ?"
        args = (comment_id, issue_id) if kind == "review" else (comment_id, issue_id, dataset_id)
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ? AND {scope}", args).fetchone()
        if row is None:
            raise CommentMissingError("评论不存在。 / Comment not found.")
        if not actor_verified or not actor or not (is_admin or (
            bool(row["author_verified"]) and str(row["author"]).lower() == actor.lower()
        )):
            raise PermissionError("只能管理自己的已验证评论；管理员可管理他人评论。 / Only the verified author or an administrator can manage this comment.")
        if kind == "review":
            if comment_metadata(row)["is_label_evidence"]:
                raise CommentConflictError("标注依据是只读审计记录，请通过标注流程修订结论。 / Label evidence is read-only. Revise it through the labeling workflow.")
            if row["discussion_channel"] == "legacy":
                raise CommentConflictError("历史讨论为只读。 / Historical discussion is read-only.")
            issue = conn.execute("SELECT baseline_scope FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
            if issue is None or (row["discussion_channel"] in {"case", "campaign"} and str(row["baseline_scope"] or "") != str(issue["baseline_scope"] or "")):
                raise CommentConflictError("评论所属数据集已变化，请重新打开原讨论。 / The comment dataset changed. Reopen its original discussion.")
            if row["discussion_channel"] == "campaign":
                task = conn.execute("SELECT lifecycle, legacy_read_only FROM issue_work_splits WHERE id = ?", (row["campaign_id"],)).fetchone()
                if task is None or task["lifecycle"] != "active" or task["legacy_read_only"]:
                    raise CommentConflictError("该任务讨论为只读。 / This task discussion is read-only.")
        return row

    def mutate_comment(self, *, kind: str, comment_id: int, issue_id: str,
                       dataset_id: str = "", actor: str, actor_source: str,
                       actor_verified: bool, is_admin: bool, expected_version: int,
                       body: str | None = None, delete: bool = False,
                       mentions: list[str] | None = None) -> dict[str, Any]:
        table = self._comment_table(kind)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("必须提供有效的评论版本。 / A valid comment version is required.")
        if not delete and not isinstance(body, str):
            raise ValueError("评论内容必须为文本。 / Comment body must be text.")
        text = "" if delete else str(body or "").strip()
        if not delete and not 1 <= len(text) <= 3500:
            raise ValueError("评论内容必须为 1 到 3500 个字符。 / Comments must contain 1 to 3500 characters.")
        if not delete and re.match(r"\AIssue 标签 #[1-9][0-9]* · 标注依据 / Label rationale\n", text):
            raise ValueError("标注依据前缀保留给只读审计记录。 / The label-evidence prefix is reserved for read-only audit records.")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            row = self._manageable_comment(conn, kind=kind, comment_id=comment_id,
                issue_id=issue_id, dataset_id=dataset_id, actor=actor,
                actor_verified=actor_verified, is_admin=is_admin)
            if row["deleted_at"] or int(row["version"]) != expected_version:
                raise CommentConflictError("评论已被修改或删除，请重新加载后再操作。 / The comment changed or was deleted. Reload it before continuing.")
            if kind == "review" and not delete:
                attached = conn.execute("SELECT id FROM comment_attachments WHERE comment_id = ?", (comment_id,)).fetchall()
                allowed = {str(item["id"]) for item in attached}
                if any(token not in allowed for token in re.findall(r"attachment:([A-Za-z0-9-]+)", text)):
                    raise ValueError("只能保留当前评论的图片引用。 / Only this comment's image references are allowed.")
            normalized_mentions = [] if delete else list(dict.fromkeys(mentions or []))
            if not delete and text == row["body"]:
                return {"version": expected_version, "changed": False}
            cursor = conn.execute(f"""
                UPDATE {table} SET body = ?, mentions_json = ?, version = version + 1,
                  edited_at = ?, deleted_at = ?, updated_by = ?
                WHERE id = ? AND version = ? AND deleted_at IS NULL
            """, (text, _json(normalized_mentions), row["edited_at"] if delete else now,
                  now if delete else None, actor, comment_id, expected_version))
            if cursor.rowcount != 1:
                raise CommentConflictError("评论已变化，请重新加载。 / The comment changed. Reload it.")
            conn.execute("""
                INSERT INTO comment_changes (comment_kind, comment_id, version_before,
                  version_after, action, body_before, body_after, mentions_before_json,
                  mentions_after_json, actor, actor_source, actor_verified, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (kind, comment_id, expected_version, expected_version + 1,
                  "delete" if delete else "edit", row["body"], text,
                  _json(_json_load(row["mentions_json"], [])), _json(normalized_mentions),
                  actor, actor_source, actor_verified, now))
            # Do not send new notifications or deliver an obsolete pending body.
            # A message already in flight/sent cannot be recalled here.
            outbox = "comment_notifications" if kind == "review" else "intent_comment_notifications"
            conn.execute(f"""UPDATE {outbox} SET status = 'failed',
                last_error = 'Comment changed; delivery cancelled.', updated_at = ?
                WHERE comment_id = ? AND status IN ('pending', 'retry')""", (now, comment_id))
            if self.backend == "postgresql":
                conn.execute("UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = ? WHERE id = 1", (now,))
            self._mark_change_topic(conn, "shared")
        return {"version": expected_version + 1, "changed": True}

    def comment_change_history(self, *, kind: str, comment_id: int, issue_id: str,
                               dataset_id: str = "", actor: str,
                               actor_verified: bool, is_admin: bool) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._manageable_comment(conn, kind=kind, comment_id=comment_id,
                issue_id=issue_id, dataset_id=dataset_id, actor=actor,
                actor_verified=actor_verified, is_admin=is_admin)
            rows = conn.execute("""SELECT version_before, version_after, action,
                body_before, body_after, actor, actor_source, actor_verified, created_at
                FROM comment_changes WHERE comment_kind = ? AND comment_id = ?
                ORDER BY version_after""", (kind, comment_id)).fetchall()
        return [{**dict(row), "created_at": str(row["created_at"])} for row in rows]
