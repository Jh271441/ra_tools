from __future__ import annotations

import unittest

from ra_triage_dashboard.app.trail_writer import (
    build_trail_changes,
    deep_merge_dict,
    write_trail_model_results,
)


class TrailWriterTest(unittest.TestCase):
    def test_deep_merge_does_not_mutate_inputs(self) -> None:
        base = {"existing": {"keep": True, "replace": "old"}}
        patch = {"existing": {"replace": "new"}, "added": 1}
        merged = deep_merge_dict(base, patch)
        self.assertEqual(merged, {"existing": {"keep": True, "replace": "new"}, "added": 1})
        self.assertEqual(base["existing"]["replace"], "old")

    def test_build_changes_merges_current_info_and_sets_model_result(self) -> None:
        items = [
            {
                "issue_id": "cn00000001",
                "model": {"label": "MISMATCH", "reason": "queue", "confidence": 0.8},
                "target": {"patch": {"ra_triage_dashboard": {"should_exclude": True}}},
            }
        ]
        changes = build_trail_changes(
            items,
            current_rows=[{"issue_id": "cn00000001", "ra_stuck_auto_result_info": {"keep": 1}}],
        )
        self.assertEqual(changes[0]["ra_stuck_auto_result"], "误触发")
        info = changes[0]["ra_stuck_auto_result_info"]
        self.assertEqual(info["keep"], 1)
        self.assertTrue(info["ra_triage_dashboard"]["should_exclude"])
        self.assertEqual(info["model_result"]["label"], "误触发")

    def test_writer_chunks_and_protects_caller_objects_from_mutating_client(self) -> None:
        original = [{"issue_id": f"cn{i:08d}", "ra_stuck_auto_result": "误触发"} for i in range(3)]
        seen = []

        class FakeClient:
            def update_issue_with_changes(self, changes, replace=False):
                seen.append((changes, replace))
                for change in changes:
                    change.pop("issue_id", None)
                return {"msg": "success"}

        stats = write_trail_model_results(
            original,
            ra_root="/tmp",
            chunk_size=2,
            client_factory=FakeClient,
        )
        self.assertEqual(stats["success_count"], 3)
        self.assertEqual(stats["failed_count"], 0)
        self.assertEqual(len(stats["chunks"]), 2)
        self.assertEqual(original[0]["issue_id"], "cn00000000")
        self.assertTrue(all(replace for _, replace in seen))


if __name__ == "__main__":
    unittest.main()
