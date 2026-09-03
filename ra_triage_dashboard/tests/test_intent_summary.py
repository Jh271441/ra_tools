from __future__ import annotations

import unittest

from ra_triage_dashboard.app.intent_summary import intent_frame_counts, summarize_intent


class IntentSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = {
            "assignments": [
                {"experiment_id": "active", "status": "active", "case_id": "c1", "username": "alice"},
                {"experiment_id": "active", "status": "active", "case_id": "c1", "username": "bob"},
                {"experiment_id": "closed", "status": "closed", "case_id": "c2", "username": "alice"},
                {"experiment_id": "closed", "status": "closed", "case_id": "c2", "username": "bob"},
            ],
            "heads": [
                {"case_id": "c1", "username": "alice", "routing_default": "straight", "lane_change_default": "no_lane_change", "overrides": [], "updated_at": "1"},
                {"case_id": "c1", "username": "bob", "routing_default": "left_turn", "lane_change_default": "lane_change", "overrides": [], "updated_at": "2"},
                {"case_id": "c2", "username": "alice", "routing_default": "straight", "lane_change_default": "no_lane_change", "overrides": [], "updated_at": "3"},
                {"case_id": "c2", "username": "bob", "routing_default": "straight", "lane_change_default": "no_lane_change", "overrides": [], "updated_at": "4"},
            ],
        }

    def test_active_blind_experiment_only_exposes_current_user(self) -> None:
        report = summarize_intent(self.data, ("c1", "c2"), username="alice")
        self.assertNotIn(("c1", "bob"), {(row["case_id"], row["username"]) for row in report["items"]})
        self.assertIn(("c1", "alice"), {(row["case_id"], row["username"]) for row in report["items"]})
        self.assertTrue(report["blind_active"])

    def test_admin_reveal_and_closed_experiment_agreement(self) -> None:
        revealed = summarize_intent(self.data, ("c1", "c2"), username="alice", reveal_answers=True)
        self.assertEqual(revealed["total"], 4)
        closed = summarize_intent(self.data, ("c1", "c2"), username="alice", experiment_id="closed")
        self.assertEqual(closed["agreement"], {"comparable_cases": 1, "matching_cases": 1})

    def test_assignee_filter_requires_selected_owners_on_case(self) -> None:
        report = summarize_intent(self.data, ("c1", "c2"), username="alice", assignees=("alice", "bob"), reveal_answers=True)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["total"], 4)

    def test_assignee_filter_also_supports_annotations_outside_experiments(self) -> None:
        data = {"assignments": [], "heads": [self.data["heads"][0]]}
        report = summarize_intent(data, ("c1",), username="alice", assignees=("alice",))
        self.assertEqual(report["case_count"], 1)
        self.assertEqual(report["total"], 1)

    def test_unlabeled_assignment_rows_are_hidden(self) -> None:
        data = {"assignments": self.data["assignments"], "heads": []}
        report = summarize_intent(data, ("c1", "c2"), username="alice", experiment_id="active")
        self.assertEqual(report["case_count"], 1)
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["items"], [])

    def test_axis_filters_include_override_only_annotations(self) -> None:
        data = {"assignments": [], "heads": [{
            "case_id": "c1", "username": "alice", "routing_default": "",
            "lane_change_default": "", "updated_at": "1",
            "overrides": [{"offset_ms": 0, "routing_intent": "left_turn", "lane_change_intent": ""}],
        }]}
        routing = summarize_intent(data, ("c1",), username="alice", axis="routing", page_size=10)
        lane = summarize_intent(data, ("c1",), username="alice", axis="lane_change", page_size=10)
        self.assertEqual(routing["total"], 1)
        self.assertEqual(routing["axis"], "routing")
        self.assertEqual(lane["total"], 0)

    def test_frame_counts_follow_sparse_overrides_and_case_defaults(self) -> None:
        timeline = [
            {"id": "t:-1000", "offset_ms": -1000},
            {"id": "t:+0", "offset_ms": 0},
            {"id": "t:+1000", "offset_ms": 1000},
            {"id": "t:+2000", "offset_ms": 2000},
        ]
        counts = intent_frame_counts(
            timeline,
            routing_default="straight",
            lane_change_default="no_lane_change",
            overrides=[
                {"timepoint_id": "t:+0", "routing_intent": "left_turn", "lane_change_intent": ""},
                {"timepoint_id": "t:+1000", "routing_intent": "", "lane_change_intent": "lane_change"},
            ],
        )
        self.assertEqual(counts["frame_count"], 4)
        self.assertEqual(counts["routing"], {"straight": 3, "left_turn": 1})
        self.assertEqual(counts["lane_change"], {"no_lane_change": 3, "lane_change": 1})


if __name__ == "__main__":
    unittest.main()
