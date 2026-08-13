from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class WorkSplitTest(unittest.TestCase):
    def test_even_share_when_no_fixed_counts(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(10)],
            [{"name": "a"}, {"name": "b"}],
            seed=1,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(sum(item["count"] for item in result), 10)
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[0]["mode"], "share")

    def test_fixed_plus_remaining_share(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(10)],
            [
                {"name": "alice", "count": 3},
                {"name": "bob"},
                {"name": "carol"},
            ],
            seed=7,
        )
        by_name = {item["name"]: item for item in result}
        self.assertEqual(by_name["alice"]["count"], 3)
        self.assertEqual(by_name["alice"]["mode"], "fixed")
        self.assertEqual(by_name["bob"]["count"] + by_name["carol"]["count"], 7)
        self.assertTrue(abs(by_name["bob"]["count"] - by_name["carol"]["count"]) <= 1)
        all_ids = []
        for item in result:
            all_ids.extend(item["issue_ids"])
        self.assertEqual(sorted(all_ids), sorted([f"id{i}" for i in range(10)]))

    def test_rejects_over_allocated_fixed_counts(self) -> None:
        with self.assertRaises(ValueError):
            distribute_issue_ids(
                ["a", "b", "c"],
                [{"name": "x", "count": 2}, {"name": "y", "count": 2}],
                seed=1,
            )

    def test_apply_work_split_persists_filterable_assignee(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "work-split.sqlite")
            db.init()
            now = "2026-08-04T00:00:00+00:00"
            with db._write_lock, db.connect() as conn:
                for index in range(5):
                    conn.execute(
                        """
                        INSERT INTO issues (
                            issue_id, trip_id, title, scenario, summary, review_note,
                            trail_url, gt_label, gt_source, source, baseline_scope,
                            extra_json, created_at, updated_at
                        ) VALUES (?, '', '', '', '', '', '', '误触发', 'test', 'test',
                                  'scope', '{}', ?, ?)
                        """,
                        (f"cn{index}", now, now),
                    )
            assignments = distribute_issue_ids(
                [f"cn{i}" for i in range(4)],
                [{"name": "alice", "count": 1}, {"name": "bob"}],
                seed=3,
            )
            saved = db.apply_work_split(
                assignments=assignments,
                created_by="admin.user",
                seed=3,
                filter_snapshot={"gt_label": "误触发"},
            )
            db.apply_work_split(
                assignments=[
                    {
                        "name": "carol",
                        "count": 1,
                        "requested_count": 1,
                        "mode": "fixed",
                        "issue_ids": ["cn4"],
                    }
                ],
                created_by="admin.user",
            )
            self.assertTrue(saved["split_id"].startswith("split-"))
            alice = db.list_cases(
                baseline_scope="scope", work_assignee="alice", page_size=20
            )
            bob = db.list_cases(
                baseline_scope="scope", work_assignee="bob", page_size=20
            )
            none = db.list_cases(
                baseline_scope="scope", work_assignee="__none__", page_size=20
            )
            self.assertEqual(alice["total"], 1)
            self.assertEqual(bob["total"], 3)
            self.assertEqual(none["total"], 0)
            self.assertEqual(alice["items"][0]["work_assignee"], "alice")
            names = {item["username"] for item in db.list_work_assignees()}
            self.assertEqual(names, {"alice", "bob", "carol"})
            scoped = db.list_work_assignees(
                issue_ids=[f"cn{i}" for i in range(4)]
            )
            self.assertEqual(
                {item["username"] for item in scoped}, {"alice", "bob"}
            )
            self.assertEqual(sum(item["issue_count"] for item in scoped), 4)
            self.assertEqual(db.list_work_assignees(issue_ids=[]), [])


if __name__ == "__main__":
    unittest.main()
