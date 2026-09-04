from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.routers import intent_labeling


class _Registry:
    @staticmethod
    def case_ids(dataset_id: str) -> tuple[str, ...]:
        return {
            "0206": ("cn1_1", "cn2_2"),
            "0508": ("cn3_3",),
        }[dataset_id]


class IntentMultiDatasetTest(unittest.TestCase):
    def test_combined_queue_preserves_dataset_boundaries_and_navigation(self) -> None:
        def fake_list(dataset_id: str, **_kwargs):
            items = [
                {
                    "case_id": case_id,
                    "issue_id": case_id.rsplit("_", 1)[0],
                    "ordinal": index,
                    "status": "unlabeled",
                    "revision_id": None,
                }
                for index, case_id in enumerate(_Registry.case_ids(dataset_id), 1)
            ]
            return {"items": items}

        with (
            patch.object(intent_labeling, "intent_dataset_registry", _Registry()),
            patch.object(intent_labeling, "_list_cases", side_effect=fake_list),
        ):
            payload = intent_labeling._list_cases_multi(
                ("0206", "0508"),
                status="all",
                search="",
                page=1,
                page_size=20,
            )
        self.assertEqual(payload["scope_total"], 3)
        self.assertEqual(
            [(item["dataset_id"], item["case_id"], item["ordinal"]) for item in payload["items"]],
            [("0206", "cn1_1", 1), ("0206", "cn2_2", 2), ("0508", "cn3_3", 3)],
        )
        self.assertEqual(payload["items"][1]["next"], {"dataset_id": "0508", "case_id": "cn3_3"})
        self.assertEqual(payload["items"][2]["previous"], {"dataset_id": "0206", "case_id": "cn2_2"})

    def test_combined_queue_search_keeps_global_ordinal(self) -> None:
        def fake_list(dataset_id: str, **_kwargs):
            return {"items": [
                {
                    "case_id": case_id,
                    "issue_id": case_id.rsplit("_", 1)[0],
                    "ordinal": index,
                    "status": "unlabeled",
                    "revision_id": None,
                }
                for index, case_id in enumerate(_Registry.case_ids(dataset_id), 1)
            ]}

        with (
            patch.object(intent_labeling, "intent_dataset_registry", _Registry()),
            patch.object(intent_labeling, "_list_cases", side_effect=fake_list),
        ):
            payload = intent_labeling._list_cases_multi(
                ("0206", "0508"),
                status="all",
                search="cn3_3",
                page=1,
                page_size=20,
            )
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["ordinal"], 3)

    def test_combined_queue_incomplete_includes_partial_and_keeps_navigation(self) -> None:
        statuses = {"cn1_1": "completed", "cn2_2": "partial", "cn3_3": "unlabeled"}

        def fake_list(dataset_id: str, **_kwargs):
            return {"items": [
                {
                    "case_id": case_id,
                    "issue_id": case_id.rsplit("_", 1)[0],
                    "ordinal": index,
                    "status": statuses[case_id],
                    "revision_id": None,
                }
                for index, case_id in enumerate(_Registry.case_ids(dataset_id), 1)
            ]}

        with (
            patch.object(intent_labeling, "intent_dataset_registry", _Registry()),
            patch.object(intent_labeling, "_list_cases", side_effect=fake_list),
        ):
            payload = intent_labeling._list_cases_multi(
                ("0206", "0508"),
                status="incomplete",
                search="",
                page=1,
                page_size=1,
            )
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["scope_total"], 3)
        self.assertEqual(payload["items"][0]["case_id"], "cn2_2")
        self.assertEqual(payload["items"][0]["previous"], {"dataset_id": "0206", "case_id": "cn1_1"})
        self.assertEqual(payload["items"][0]["next"], {"dataset_id": "0508", "case_id": "cn3_3"})

    def test_combined_summary_keeps_dataset_identity(self) -> None:
        class SummaryRegistry(_Registry):
            @staticmethod
            def timeline(_dataset_id: str, case_id: str):
                return ({"id": f"{case_id}:0"},)

        class SummaryDatabase:
            @staticmethod
            def list_intent_experiments(_dataset_id: str):
                return []

            @staticmethod
            def intent_report_rows(dataset_id: str):
                case_id = _Registry.case_ids(dataset_id)[0]
                return {
                    "heads": [{
                        "case_id": case_id,
                        "username": "annotator",
                        "revision_id": 1,
                        "routing_default": "straight",
                        "lane_change_default": "no_lane_change",
                        "updated_at": "2026-09-04T00:00:00Z",
                        "overrides": [],
                    }],
                    "assignments": [],
                    "comments": [{
                        "id": 9,
                        "case_id": case_id,
                        "body": f"{dataset_id} comment",
                        "author": "annotator",
                        "reply_to_id": None,
                        "created_at": "2026-09-04T00:01:00Z",
                    }],
                }

            @staticmethod
            def search_intent_comments(*_args, **_kwargs):
                return []

        with (
            patch.object(intent_labeling, "intent_dataset_registry", SummaryRegistry()),
            patch.object(intent_labeling, "database", SummaryDatabase()),
        ):
            payload = intent_labeling._intent_summary_payload_multi(
                ("0206", "0508"),
                SimpleNamespace(username="annotator"),
                "",
                (),
                False,
                "all",
                1,
                20,
            )
        self.assertEqual(payload["dataset_ids"], ["0206", "0508"])
        self.assertEqual(payload["case_count"], 3)
        self.assertEqual(
            [(item["dataset_id"], item["case_id"]) for item in payload["items"]],
            [("0206", "cn1_1"), ("0508", "cn3_3")],
        )
        self.assertEqual(payload["items"][0]["comments"][0]["body"], "0206 comment")
        self.assertEqual(payload["frame_distributions"]["routing"], {"straight": 2})
        self.assertEqual(payload["frame_distributions"]["lane_change"], {"no_lane_change": 2})


if __name__ == "__main__":
    unittest.main()
