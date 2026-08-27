from __future__ import annotations

from typing import Any

from .shared import utc_now


class DatabaseNotificationsMixin:
    def claim_comment_notification(self, *, now: str) -> dict[str, Any] | None:
        """Atomically claim one due comment-notification outbox row."""

        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM comment_notifications
                WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            notification_id = int(row["id"])
            cursor = conn.execute(
                """
                UPDATE comment_notifications
                SET status = 'sending', attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE id = ? AND status IN ('pending', 'retry')
                  AND next_attempt_at <= ?
                """,
                (now, notification_id, now),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute(
                """
                SELECT cn.*, comment.model_run_id, comment.body,
                       comment.author, comment.reply_to_id,
                       parent.author AS reply_to_author
                FROM comment_notifications cn
                JOIN review_comments comment ON comment.id = cn.comment_id
                LEFT JOIN review_comments parent ON parent.id = comment.reply_to_id
                WHERE cn.id = ?
                """,
                (notification_id,),
            ).fetchone()
        return {key: claimed[key] for key in claimed.keys()} if claimed else None

    def claim_review_notification(self, *, now: str) -> dict[str, Any] | None:
        """Atomically claim one due outbox row across workers/processes."""

        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM review_notifications
                WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            notification_id = int(row["id"])
            cursor = conn.execute(
                """
                UPDATE review_notifications
                SET status = 'sending', attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE id = ? AND status IN ('pending', 'retry')
                  AND next_attempt_at <= ?
                """,
                (now, notification_id, now),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute(
                """
                SELECT rn.*, ann.model_run_id, ann.note, ann.author
                FROM review_notifications rn
                JOIN annotations ann ON ann.id = rn.annotation_id
                WHERE rn.id = ?
                """,
                (notification_id,),
            ).fetchone()
        return {key: claimed[key] for key in claimed.keys()} if claimed else None

    def complete_review_notification(
        self, notification_id: int, *, trace_id: str, message_unique_id: str
    ) -> None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE review_notifications
                SET status = 'sent', trace_id = ?, message_unique_id = ?,
                    last_error = '', updated_at = ?, sent_at = ?
                WHERE id = ? AND status = 'sending'
                """,
                (trace_id, message_unique_id, now, now, notification_id),
            )

    def complete_comment_notification(
        self, notification_id: int, *, trace_id: str, message_unique_id: str
    ) -> None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE comment_notifications
                SET status = 'sent', trace_id = ?, message_unique_id = ?,
                    last_error = '', updated_at = ?, sent_at = ?
                WHERE id = ? AND status = 'sending'
                """,
                (trace_id, message_unique_id, now, now, notification_id),
            )

    def defer_review_notification(
        self,
        notification_id: int,
        *,
        next_attempt_at: str,
        error: str,
        terminal: bool,
    ) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE review_notifications
                SET status = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'sending'
                """,
                (
                    "failed" if terminal else "retry",
                    next_attempt_at,
                    str(error or "")[:500],
                    utc_now(),
                    notification_id,
                ),
            )

    def defer_comment_notification(
        self,
        notification_id: int,
        *,
        next_attempt_at: str,
        error: str,
        terminal: bool,
    ) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE comment_notifications
                SET status = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'sending'
                """,
                (
                    "failed" if terminal else "retry",
                    next_attempt_at,
                    str(error or "")[:500],
                    utc_now(),
                    notification_id,
                ),
            )

    def recover_review_notifications(self) -> int:
        """Make process-interrupted sends retryable after startup."""

        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE review_notifications
                SET status = 'retry', next_attempt_at = ?,
                    last_error = CASE WHEN TRIM(last_error) = ''
                        THEN '服务重启前发送状态未知，已重新排队。' ELSE last_error END,
                    updated_at = ?
                WHERE status = 'sending'
                """,
                (now, now),
            )
        return cursor.rowcount

    def recover_comment_notifications(self) -> int:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE comment_notifications
                SET status = 'retry', next_attempt_at = ?,
                    last_error = CASE WHEN TRIM(last_error) = ''
                        THEN '服务重启前发送状态未知，已重新排队。' ELSE last_error END,
                    updated_at = ?
                WHERE status = 'sending'
                """,
                (now, now),
            )
        return cursor.rowcount

    def review_notification_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM review_notifications GROUP BY status
                """
            ).fetchall()
        counts = {name: 0 for name in ("pending", "sending", "retry", "sent", "failed")}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts

    def comment_notification_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM comment_notifications GROUP BY status
                """
            ).fetchall()
        counts = {name: 0 for name in ("pending", "sending", "retry", "sent", "failed")}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts
