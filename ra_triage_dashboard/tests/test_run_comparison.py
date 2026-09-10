from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


class RunComparisonDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "triage.sqlite3")
        self.database.init()
        self.scope = "run-comparison-scope"
        self.database.upsert_issues(
            [
                {"issue_id": "cn-p2f", "gt_label": "误触发"},
                {"issue_id": "cn-f2p", "gt_label": "正确触发"},
                {"issue_id": "cn-p2p", "gt_label": "无需协助"},
                {"issue_id": "cn-f2f", "gt_label": "正确触发"},
                {"issue_id": "cn-candidate-missing", "gt_label": "误触发"},
                {"issue_id": "cn-both-missing", "gt_label": "无需协助"},
            ],
            source="test",
            replace_gt=True,
            baseline_scope=self.scope,
        )
        self.baseline, _ = self.database.import_model_run(
            name="baseline",
            source_name="baseline.json",
            source_sha256="baseline-comparison-sha",
            metadata={"prompt_version": "legacy-v1"},
            rows=[
                {
                    "issue_id": "cn-p2f",
                    "model_label": "误触发",
                    "model_reason": "baseline correct",
                },
                {
                    "issue_id": "cn-f2p",
                    "model_label": "误触发",
                    "model_reason": "baseline wrong",
                },
                {
                    "issue_id": "cn-p2p",
                    "model_label": "无需协助",
                    "model_reason": "baseline correct",
                },
                {
                    "issue_id": "cn-candidate-missing",
                    "model_label": "误触发",
                    "model_reason": "candidate has no output",
                },
            ],
        )
        self.candidate, _ = self.database.import_model_run(
            name="candidate",
            source_name="candidate.json",
            source_sha256="candidate-comparison-sha",
            metadata={},
            rows=[
                {
                    "issue_id": "cn-p2f",
                    "model_label": "正确触发",
                    "model_reason": "candidate wrong",
                },
                {
                    "issue_id": "cn-f2p",
                    "model_label": "正确触发",
                    "model_reason": "candidate correct",
                    "raw": {"model_extra": {
                        "routing_intents": ["straight", "u_turn"],
                        "lane_change_intents": ["lane_change", "no_lane_change"],
                    }},
                },
                {
                    "issue_id": "cn-p2p",
                    "model_label": "真实卡住",
                    "model_reason": "stage1 compatible",
                },
                {
                    "issue_id": "cn-f2f",
                    "model_label": "误触发",
                    "model_reason": "candidate still wrong",
                },
            ],
        )

    def compare(self, **overrides):
        options = {
            "baseline_run_id": self.baseline["id"],
            "candidate_run_id": self.candidate["id"],
            "baseline_scopes": [self.scope],
        }
        options.update(overrides)
        return self.database.compare_model_runs(**options)

    def test_transition_counts_matrices_and_stage1_semantics(self) -> None:
        payload = self.compare()
        self.assertEqual(
            payload["summary"]["transition_counts"],
            {"P2P": 1, "P2F": 2, "F2P": 1, "F2F": 1},
        )
        self.assertEqual(payload["summary"]["baseline"]["correct_count"], 3)
        self.assertEqual(payload["summary"]["candidate"]["correct_count"], 2)
        self.assertEqual(payload["summary"]["total_count"], 5)
        self.assertEqual(payload["summary"]["baseline"]["missing_count"], 1)
        self.assertEqual(payload["summary"]["candidate"]["missing_count"], 1)
        baseline_rows = {
            row["gt_label"]: row
            for row in payload["summary"]["baseline"]["rows"]
        }
        self.assertIn("NONE", payload["summary"]["baseline"]["columns"])
        self.assertEqual(baseline_rows["正确触发"]["cells"]["NONE"], 1)
        candidate_rows = {
            row["gt_label"]: row
            for row in payload["summary"]["candidate"]["rows"]
        }
        self.assertEqual(candidate_rows["无需协助"]["cells"]["真实卡住"], 1)

    def test_transition_search_and_pagination(self) -> None:
        default_order = self.compare()
        self.assertEqual(
            [item["issue_id"] for item in default_order["items"]],
            [
                "cn-candidate-missing",
                "cn-f2f",
                "cn-f2p",
                "cn-p2f",
                "cn-p2p",
            ],
        )
        compared_ids = {item["issue_id"] for item in default_order["items"]}
        self.assertIn("cn-f2f", compared_ids)
        self.assertIn("cn-candidate-missing", compared_ids)
        self.assertNotIn("cn-both-missing", compared_ids)
        f2p = next(item for item in default_order["items"] if item["issue_id"] == "cn-f2p")
        self.assertTrue(f2p["extra_inputs"]["candidate"]["available"])
        self.assertEqual(
            f2p["extra_inputs"]["candidate"]["axes"]["routing"]["frame_count"],
            2,
        )
        self.assertEqual(self.compare(search="candidate has no output")["total"], 1)
        regression = self.compare(transition="P2F")
        self.assertEqual(regression["total"], 2)
        self.assertEqual(
            [item["issue_id"] for item in regression["items"]],
            ["cn-candidate-missing", "cn-p2f"],
        )
        searched = self.compare(search="f2", page_size=1, page=2)
        self.assertEqual(searched["total"], 2)
        self.assertEqual(searched["page_count"], 2)
        self.assertEqual(searched["page"], 2)
        self.assertEqual(len(searched["items"]), 1)

    def test_label_reason_and_change_filters(self) -> None:
        by_gt = self.compare(gt_label="正确触发")
        self.assertEqual(
            {item["issue_id"] for item in by_gt["items"]},
            {"cn-f2p", "cn-f2f"},
        )
        by_baseline = self.compare(baseline_label="NONE")
        self.assertEqual(
            [item["issue_id"] for item in by_baseline["items"]], ["cn-f2f"]
        )
        by_candidate_missing = self.compare(candidate_label="NONE")
        self.assertEqual(
            [item["issue_id"] for item in by_candidate_missing["items"]],
            ["cn-candidate-missing"],
        )
        by_candidate = self.compare(candidate_label="真实卡住")
        self.assertEqual(
            [item["issue_id"] for item in by_candidate["items"]], ["cn-p2p"]
        )
        changed = self.compare(label_change="changed")
        self.assertEqual(changed["total"], 5)
        unchanged = self.compare(label_change="unchanged")
        self.assertEqual(unchanged["total"], 0)
        self.assertEqual(unchanged["items"], [])
        reason = self.compare(search="stage1 compatible")
        self.assertEqual(
            [item["issue_id"] for item in reason["items"]], ["cn-p2p"]
        )

    def test_extra_input_filter_and_review_fallback_order(self) -> None:
        filtered = self.compare(input_filter={
            "version": 1, "run": "candidate", "relation": "all",
            "conditions": [
                {"axis": "routing", "operator": "any", "values": ["直行", "掉头"]},
                {"axis": "lane_change", "operator": "any", "values": ["变道"]},
            ],
        })
        self.assertEqual([item["issue_id"] for item in filtered["items"]], ["cn-f2p"])
        self.assertEqual(filtered["items"][0]["extra_inputs"]["candidate"]["axes"]["routing"]["frame_count"], 2)

        def annotate(run_id, tag, author):
            self.database.create_annotation(
                issue_id="cn-f2p", model_run_id=run_id, label="正确触发",
                review_status="reviewed", tags=[tag], missing_evidence=[],
                note="", author=author,
            )

        annotate(self.baseline["id"], "other", "baseline-author")
        self.assertEqual(self.compare()["items"][2]["scene_review"]["source"], "other_run")
        annotate("", "legacy", "legacy-author")
        self.assertEqual(self.compare()["items"][2]["scene_review"]["source"], "unbound")
        annotate(self.candidate["id"], "candidate", "candidate-author")
        review = self.compare()["items"][2]["scene_review"]
        self.assertEqual(review["source"], "candidate")
        self.assertEqual(review["tags"], ["candidate"])

    def test_defaults_to_ten_cases_per_page_and_rejects_unknown_filters(self) -> None:
        payload = self.compare()
        self.assertEqual(payload["page_size"], 10)
        for field in ("gt_label", "baseline_label", "candidate_label", "label_change"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.compare(**{field: "unsupported"})

    def test_batch_prompt_and_input_snapshot_is_redacted(self) -> None:
        job = self.database.create_batch_prediction_job(
            name="candidate batch",
            issue_ids=["cn-p2f"],
            requested_by="admin",
            requested_model_id="model-requested",
            resolved_model_id="model-resolved",
            model_source="gateway",
            catalog_sha256="catalog-sha",
            prompt_version="prompt-v2",
            prompt_template="Classify this immutable input.",
            prompt_template_sha256="prompt-sha",
            prompt_mode="full",
            input_profile="ares-bev-v2",
            input_config={"frames": 5, "api_key": "must-not-leak"},
        )
        self.database.update_batch_prediction_job(
            job["id"], model_run_id=self.candidate["id"]
        )
        payload = self.compare()
        snapshot = payload["candidate_run"]
        self.assertEqual(snapshot["prompt"]["version"], "prompt-v2")
        self.assertEqual(
            snapshot["prompt"]["template"], "Classify this immutable input."
        )
        self.assertEqual(snapshot["input"]["profile"], "ares-bev-v2")
        self.assertNotEqual(snapshot["input"]["config"]["api_key"], "must-not-leak")

    def test_requires_two_existing_distinct_runs(self) -> None:
        with self.assertRaises(ValueError):
            self.compare(candidate_run_id=self.baseline["id"])
        with self.assertRaises(ValueError):
            self.compare(candidate_run_id="missing")


if __name__ == "__main__":
    unittest.main()
