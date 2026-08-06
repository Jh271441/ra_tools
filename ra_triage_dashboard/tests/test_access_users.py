from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


class AccessUsersTest(unittest.TestCase):
    def make_database(self, directory: str) -> Database:
        database = Database(Path(directory) / "triage.sqlite3")
        database.init()
        return database

    def test_bootstrap_is_one_time_and_roles_are_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.bootstrap_access_users(
                writers=("jasperchen", "xuhaoxuan_i"),
                administrators=("jasperchen",),
            )
            self.assertEqual(database.access_role("jasperchen"), "admin")
            self.assertEqual(database.access_role("xuhaoxuan_i"), "writer")
            self.assertEqual(database.access_role("unknown"), "")

            database.delete_access_user("xuhaoxuan_i")
            database.bootstrap_access_users(
                writers=("jasperchen", "xuhaoxuan_i"),
                administrators=("jasperchen",),
            )
            self.assertEqual(database.access_role("xuhaoxuan_i"), "")

    def test_admin_can_add_update_and_remove_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.bootstrap_access_users(
                writers=("jasperchen",), administrators=("jasperchen",)
            )
            user = database.set_access_user(
                username="new_user", role="writer", actor="jasperchen"
            )
            self.assertEqual(user["role"], "writer")
            promoted = database.set_access_user(
                username="new_user", role="admin", actor="jasperchen"
            )
            self.assertEqual(promoted["role"], "admin")
            self.assertTrue(database.delete_access_user("new_user"))
            self.assertEqual(database.access_role("new_user"), "")

    def test_last_admin_cannot_be_demoted_or_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.bootstrap_access_users(
                writers=("jasperchen",), administrators=("jasperchen",)
            )
            with self.assertRaisesRegex(ValueError, "唯一的管理员"):
                database.set_access_user(
                    username="jasperchen", role="writer", actor="jasperchen"
                )
            with self.assertRaisesRegex(ValueError, "唯一的管理员"):
                database.delete_access_user("jasperchen")


if __name__ == "__main__":
    unittest.main()
