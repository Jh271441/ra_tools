from __future__ import annotations

import unittest

from auto_triage_bot.dashboard_client import build_case_context


class DashboardContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "issue_id": "12345678",
            "gt_label": "正确触发",
            "gt_source": "baseline",
            "baseline_scope": "release0508",
            "baseline_id": "0508",
            "predictions": [
                {
                    "model_run_id": "run-default",
                    "run_name": "default",
                    "run_is_default": True,
                    "model_label": "无需协助",
                    "model_reason": "reason default",
                },
                {
                    "model_run_id": "run-other",
                    "run_name": "other",
                    "run_is_default": False,
                    "model_label": "正确触发",
                    "model_reason": "reason other",
                },
            ],
            "annotations": [
                {
                    "id": 3,
                    "model_run_id": "run-other",
                    "label": "正确触发",
                    "note": "other review",
                },
                {
                    "id": 2,
                    "model_run_id": "run-default",
                    "label": "正确触发",
                    "note": "default review",
                },
                {
                    "id": 1,
                    "model_run_id": "",
                    "label": "误触发",
                    "note": "legacy review",
                },
            ],
        }

    def test_default_run_and_its_review_are_bound(self) -> None:
        context = build_case_context(self.case)
        self.assertEqual(context["prediction"]["run_id"], "run-default")
        self.assertEqual(
            context["latest_review_for_selected_run"]["note"], "default review"
        )

    def test_explicit_run_never_falls_back(self) -> None:
        context = build_case_context(self.case, run_id="run-missing")
        self.assertIsNone(context["prediction"])
        self.assertIsNone(context["latest_review_for_selected_run"])

    def test_explicit_run_uses_matching_review(self) -> None:
        context = build_case_context(self.case, run_id="run-other")
        self.assertEqual(context["prediction"]["label"], "正确触发")
        self.assertEqual(
            context["latest_review_for_selected_run"]["note"], "other review"
        )


if __name__ == "__main__":
    unittest.main()
