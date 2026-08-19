from __future__ import annotations

import unittest

from ra_triage_dashboard.app.trail_writer import (
    attach_trail_operation_id,
    build_manual_exclusion_changes,
    build_trail_changes,
    decorate_trail_comments,
    deep_merge_dict,
    verify_trail_readback,
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

    def test_build_changes_info_only_preserves_top_level_model_label_and_marker_only(self) -> None:
        changes = build_trail_changes(
            [
                {
                    "issue_id": "cn00000001",
                    "model": {"label": "误触发", "reason": "queue", "confidence": 0.8},
                    "target": {"patch": {"ra_triage_dashboard": {"should_exclude": True}}},
                }
            ],
            current_rows=[
                {
                    "issue_id": "cn00000001",
                    "ra_stuck_auto_result": "正确触发",
                    "ra_stuck_auto_result_info": {"keep": 1},
                }
            ],
            write_result_field=False,
        )
        self.assertNotIn("ra_stuck_auto_result", changes[0])
        self.assertEqual(changes[0]["ra_stuck_auto_result_info"]["keep"], 1)
        self.assertEqual(
            changes[0]["ra_stuck_auto_result_info"]["ra_triage_dashboard"],
            {"should_exclude": True},
        )
        self.assertNotIn("model_result", changes[0]["ra_stuck_auto_result_info"])

    def test_build_changes_info_only_does_not_require_model_label(self) -> None:
        changes = build_trail_changes(
            [
                {
                    "issue_id": "cn00000001",
                    "model": {},
                    "target": {"patch": {"ra_triage_dashboard": {"should_exclude": True}}},
                }
            ],
            current_rows=[],
            result_field="ra_stuck_auto_result",
            info_field="ra_stuck_auto_result_info",
            write_result_field=False,
        )
        self.assertEqual(
            changes,
            [{"issue_id": "cn00000001", "ra_stuck_auto_result_info": {"ra_triage_dashboard": {"should_exclude": True}}}],
        )

    def test_info_note_is_part_of_field_update_and_never_a_trail_comment(self) -> None:
        changes = build_trail_changes(
            [
                {
                    "issue_id": "cn00000001",
                    "model": {},
                    "comment": "人工确认：不纳入模型问题范围",
                    "target": {"patch": {"ra_triage_dashboard": {"should_exclude": True}}},
                }
            ],
            write_result_field=False,
        )
        calls = []

        class FakeClient:
            def update_issue_with_changes(self, update, replace=False):
                calls.append(update)
                self.update = update
                return {"msg": "success"}

            def add_issue_comment(self, *_args, **_kwargs):  # pragma: no cover - must never run
                raise AssertionError("info-only exclusion must not call Trail Comment API")

        stats = write_trail_model_results(changes, ra_root="/tmp", client_factory=FakeClient)
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][0]["ra_stuck_auto_result_info"]["ra_triage_dashboard"]["should_exclude_comment"],
            "人工确认：不纳入模型问题范围",
        )
        self.assertNotIn("comment", calls[0][0])

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

    def test_manual_exclusion_preserves_model_label_and_merges_info(self) -> None:
        changes = build_manual_exclusion_changes(
            ["cn00000001"],
            current_rows=[
                {
                    "issue_id": "cn00000001",
                    "ra_stuck_auto_result": "正确触发",
                    "ra_stuck_auto_result_info": {"existing": {"keep": 1}},
                }
            ],
            comment="manual shield",
        )
        self.assertEqual(changes[0]["ra_stuck_auto_result_info"]["existing"], {"keep": 1})
        self.assertTrue(
            changes[0]["ra_stuck_auto_result_info"]["ra_triage_dashboard"]["should_exclude"]
        )
        self.assertEqual(
            changes[0]["ra_stuck_auto_result_info"]["ra_triage_dashboard"]["should_exclude_comment"],
            "manual shield",
        )
        self.assertNotIn("ra_stuck_auto_result", changes[0])
        self.assertNotIn("comment", changes[0])

    def test_manual_exclusion_supports_a_distinct_info_note_per_issue(self) -> None:
        changes = build_manual_exclusion_changes(
            ["cn00000001", "cn00000002"],
            current_rows=[
                {"issue_id": "cn00000001", "ra_stuck_auto_result_info": {"keep": 1}},
                {"issue_id": "cn00000002", "ra_stuck_auto_result_info": {"keep": 2}},
            ],
            comment_by_issue={
                "cn00000001": "红绿灯场景，不纳入模型数据集",
                "cn00000002": "泊入二次寻点，应该排除",
            },
        )
        by_issue = {item["issue_id"]: item for item in changes}
        self.assertEqual(
            by_issue["cn00000001"]["ra_stuck_auto_result_info"]["ra_triage_dashboard"]["should_exclude_comment"],
            "红绿灯场景，不纳入模型数据集",
        )
        self.assertEqual(
            by_issue["cn00000002"]["ra_stuck_auto_result_info"]["ra_triage_dashboard"]["should_exclude_comment"],
            "泊入二次寻点，应该排除",
        )

    def test_writer_separately_reports_comment_result(self) -> None:
        calls = []

        class FakeClient:
            def update_issue_with_changes(self, changes, replace=False):
                calls.append(("fields", changes, replace))
                assert all("comment" not in item for item in changes)
                return {"msg": "success"}

            def add_issue_comment(self, issue_id, comment):
                calls.append(("comment", issue_id, comment))
                return {"msg": "success"}

        stats = write_trail_model_results(
            [{"issue_id": "cn00000001", "ra_stuck_auto_result_info": {}, "comment": "note"}],
            ra_root="/tmp",
            client_factory=FakeClient,
            write_comments_separately=True,
        )
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(stats["comment_total"], 1)
        self.assertEqual(stats["comment_success_count"], 1)
        self.assertEqual(stats["comment_failed_count"], 0)
        self.assertEqual([call[0] for call in calls], ["fields", "comment"])

    def test_operation_marker_is_idempotent_and_readback_is_verified(self) -> None:
        changes = attach_trail_operation_id(
            [{"issue_id": "cn00000001", "ra_stuck_auto_result_info": {}}],
            operation_id="digest-1",
        )
        decorated = decorate_trail_comments(
            [dict(changes[0], comment="人工确认")], operation_id="digest-1"
        )
        self.assertIn("digest-1", decorated[0]["comment"])
        self.assertEqual(decorated[0]["comment"], decorate_trail_comments(decorated, operation_id="digest-1")[0]["comment"])
        verification = verify_trail_readback(
            changes,
            [
                {
                    "issue_id": "cn00000001",
                    "ra_stuck_auto_result_info": {
                        "ra_triage_dashboard": {"operation_id": "digest-1"}
                    },
                }
            ],
        )
        self.assertTrue(verification["ok"])
        self.assertEqual(verification["verified_count"], 1)

    def test_writer_skips_existing_comment_marker(self) -> None:
        calls = []

        class FakeClient:
            def update_issue_with_changes(self, changes, replace=False):
                calls.append("fields")
                return {"msg": "success"}

            def add_issue_comment(self, issue_id, comment):
                calls.append("comment")
                return {"msg": "success"}

        stats = write_trail_model_results(
            [{"issue_id": "cn00000001", "ra_stuck_auto_result_info": {}, "comment": "note"}],
            ra_root="/tmp",
            client_factory=FakeClient,
            write_comments_separately=True,
            comment_skip_issue_ids=["cn00000001"],
        )
        self.assertEqual(calls, ["fields"])
        self.assertEqual(stats["comment_skipped_count"], 1)
        self.assertEqual(stats["comment_success_count"], 0)


if __name__ == "__main__":
    unittest.main()
