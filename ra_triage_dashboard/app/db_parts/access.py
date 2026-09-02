from __future__ import annotations

from typing import Any, Iterable, Sequence

from .shared import ACCESS_ROLES, utc_now


_DEFAULT_MENTION_DISPLAY_NAMES = {
    "jasperchen": "陈俊豪",
    "caoliwen_i": "曹立文",
    "xuhaoxuan_i": "徐浩轩",
    "chadyang": "杨超",
    "liangxianghui": "梁祥辉",
}


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
            conn.executemany(
                """
                INSERT INTO mention_users (
                    username, enabled, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username) DO NOTHING
                """,
                [(name, True, "bootstrap", now, now) for name in names],
            )
            conn.executemany(
                "UPDATE mention_users SET display_name = ? WHERE username = ? AND display_name = ''",
                [(display_name, username) for username, display_name in _DEFAULT_MENTION_DISPLAY_NAMES.items()],
            )

    def bootstrap_mention_users(self) -> None:
        """Seed the notification directory from the ACL without overwriting choices."""

        now = utc_now()
        with self._write_lock, self.connect() as conn:
            rows = conn.execute("SELECT username FROM access_users").fetchall()
            conn.executemany(
                """
                INSERT INTO mention_users (
                    username, enabled, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username) DO NOTHING
                """,
                [
                    (str(row["username"]), True, "bootstrap", now, now)
                    for row in rows
                ],
            )
            conn.executemany(
                "UPDATE mention_users SET display_name = ? WHERE username = ? AND display_name = ''",
                [(display_name, username) for username, display_name in _DEFAULT_MENTION_DISPLAY_NAMES.items()],
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
                SELECT username, role, intent_permission, created_by, created_at, updated_at
                FROM access_users
                ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                         username ASC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def intent_permission(self, username: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT intent_permission FROM access_users WHERE username = ?",
                (str(username or "").strip().lower(),),
            ).fetchone()
        return str(row["intent_permission"]) if row else ""

    def set_access_user(
        self, *, username: str, role: str, actor: str, intent_permission: str | None = None
    ) -> dict[str, Any]:
        normalized = str(username or "").strip().lower()
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in ACCESS_ROLES:
            raise ValueError("权限角色必须是 writer 或 admin。")
        if intent_permission is not None and intent_permission not in {"manage", "annotate", "view"}:
            raise ValueError("标注权限必须是 manage、annotate 或 view。")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT role, intent_permission FROM access_users WHERE username = ?",
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
                    "UPDATE access_users SET role = ?, intent_permission = ?, updated_at = ? WHERE username = ?",
                    (normalized_role, intent_permission or current["intent_permission"], now, normalized),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO access_users (
                        username, role, intent_permission, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (normalized, normalized_role, intent_permission or "manage", actor, now, now),
                )
            conn.execute(
                """
                INSERT INTO mention_users (
                    username, enabled, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username) DO NOTHING
                """,
                (normalized, True, actor, now, now),
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

    def list_mention_users(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled = ?"
        parameters: tuple[bool, ...] = () if include_disabled else (True,)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT username, display_name, enabled, created_by, created_at, updated_at
                FROM mention_users
                {where}
                ORDER BY enabled DESC, username ASC
                """,
                parameters,
            ).fetchall()
        return [
            {**{key: row[key] for key in row.keys()}, "enabled": bool(row["enabled"])}
            for row in rows
        ]

    def set_mention_user(
        self, *, username: str, enabled: bool, actor: str, display_name: str = ""
    ) -> dict[str, Any]:
        normalized = str(username or "").strip().lower()
        if not normalized:
            raise ValueError("用户名不能为空。")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mention_users (
                    username, display_name, enabled, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    enabled = excluded.enabled,
                    display_name = CASE WHEN excluded.display_name = ''
                        THEN mention_users.display_name ELSE excluded.display_name END,
                    updated_at = excluded.updated_at
                """,
                (normalized, str(display_name or "").strip()[:80], bool(enabled), actor, now, now),
            )
        return next(
            item
            for item in self.list_mention_users(include_disabled=True)
            if item["username"] == normalized
        )

    def delete_mention_user(self, username: str) -> bool:
        normalized = str(username or "").strip().lower()
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM mention_users WHERE username = ?", (normalized,)
            )
        return cursor.rowcount > 0

    def enabled_mention_recipients(self, usernames: Sequence[str]) -> list[str]:
        normalized = list(dict.fromkeys(
            str(value or "").strip().lower()
            for value in usernames
            if str(value or "").strip()
        ))
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT username FROM mention_users WHERE enabled = ? AND username IN ({placeholders})",
                (True, *normalized),
            ).fetchall()
        allowed = {str(row["username"]) for row in rows}
        return [name for name in normalized if name in allowed]

    def mention_display_names(self, usernames: Sequence[str]) -> dict[str, str]:
        normalized = list(dict.fromkeys(
            str(value or "").strip().lower()
            for value in usernames
            if str(value or "").strip()
        ))
        if not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT username, display_name FROM mention_users WHERE username IN ({placeholders})",
                tuple(normalized),
            ).fetchall()
        return {
            str(row["username"]): str(row["display_name"] or row["username"])
            for row in rows
        }
