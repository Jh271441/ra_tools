from __future__ import annotations

from typing import Any, Iterable, Sequence

from .shared import ACCESS_ROLES, utc_now


class DatabaseAccessMixin:
    def bootstrap_access_users(
        self, *, writers: Iterable[str], administrators: Iterable[str]
    ) -> None:
        """Seed the persistent ACL once so UI removals survive restarts."""

        writer_names = {
            str(value).strip().lower() for value in writers if str(value).strip()
        }
        admin_names = {
            str(value).strip().lower()
            for value in administrators
            if str(value).strip()
        }
        names = sorted(writer_names | admin_names)
        if not names:
            return
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS count FROM access_users"
            ).fetchone()
            if existing and int(existing["count"] or 0) > 0:
                return
            conn.executemany(
                """
                INSERT INTO access_users (
                    username, role, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        name,
                        "admin" if name in admin_names else "writer",
                        "bootstrap",
                        now,
                        now,
                    )
                    for name in names
                ],
            )

    def access_role(self, username: str) -> str:
        normalized = str(username or "").strip().lower()
        if not normalized:
            return ""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
        return str(row["role"] or "") if row else ""

    def list_access_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT username, role, created_by, created_at, updated_at
                FROM access_users
                ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                         username ASC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def set_access_user(
        self, *, username: str, role: str, actor: str
    ) -> dict[str, Any]:
        normalized = str(username or "").strip().lower()
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in ACCESS_ROLES:
            raise ValueError("权限角色必须是 writer 或 admin。")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
            if current and current["role"] == "admin" and normalized_role != "admin":
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM access_users WHERE role = 'admin'"
                ).fetchone()
                if count and int(count["count"] or 0) <= 1:
                    raise ValueError("不能降级唯一的管理员。")
            if current:
                conn.execute(
                    "UPDATE access_users SET role = ?, updated_at = ? WHERE username = ?",
                    (normalized_role, now, normalized),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO access_users (
                        username, role, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (normalized, normalized_role, actor, now, now),
                )
        return next(
            item for item in self.list_access_users() if item["username"] == normalized
        )

    def delete_access_user(self, username: str) -> bool:
        normalized = str(username or "").strip().lower()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT role FROM access_users WHERE username = ?",
                (normalized,),
            ).fetchone()
            if not current:
                return False
            if current["role"] == "admin":
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM access_users WHERE role = 'admin'"
                ).fetchone()
                if count and int(count["count"] or 0) <= 1:
                    raise ValueError("不能移除唯一的管理员。")
            cursor = conn.execute(
                "DELETE FROM access_users WHERE username = ?", (normalized,)
            )
            return cursor.rowcount > 0
