from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl

from ra_triage_dashboard.app.issue_tag_sources import (
    IssueTagSourceIndex,
    IssueTagSourceSpec,
    load_issue_tag_source,
)
from ra_triage_dashboard.app.review_workflow import resolve_expected_output
from ra_triage_dashboard.app.routers import cases as cases_router
from ra_triage_dashboard.app.runtime import REVIEW_TAG_CATALOG
from ra_triage_dashboard.app.settings import Settings


class IssueTagSourceTests(unittest.TestCase):
    def test_default_source_paths_stay_under_dashboard_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "DASHBOARD_DATA_DIR": directory,
                "DASHBOARD_ISSUE_TAG_SOURCE_0206_XLSX": "",
                "DASHBOARD_ISSUE_TAG_SOURCE_0626_XLSX": "",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        sources = {source.source_id: source.path for source in settings.issue_tag_sources}
        root = (Path(directory) / "issue_tag_sources").resolve()
        self.assertEqual(
            sources["spotcheck-0206"],
            root / "release0206版本 RA问题review.xlsx",
        )
        self.assertEqual(
            sources["spotcheck-0626"], root / "release0626抽检.xlsx"
        )

    def _write_source(self, path: Path) -> None:
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.append(
            [
                "issue_id",
                "label",
                "是否排除",
                "误触发Tag",
                "应该触发Tag",
                "如何驶离Tag",
                "无需协助Tag",
            ]
        )
        worksheet.append(
            ["cn0206a", "误触发", "是", "排队/人工误触发", "", "", ""]
        )
        worksheet.append(
            [
                "cn0626a",
                "正确触发",
                "",
                "",
                "EOL&&地图变更",
                "Waypoint&&接管",
                "",
            ]
        )
        worksheet.append(
            [
                "cn0626b",
                "无需协助",
                "",
                "",
                "未避障",
                "",
                "前车驶离",
            ]
        )
        # A label that contradicts its false-trigger direction must not
        # prefill a human Review.
        worksheet.append(["cnconflict", "正确触发", "", "排队", "", "", ""])
        workbook.save(path)
        workbook.close()

    def test_maps_spotcheck_columns_with_provenance_and_fails_closed_on_conflict(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release0206-review.xlsx"
            self._write_source(path)
            spec = IssueTagSourceSpec(
                source_id="spotcheck-0206",
                label="0206 抽检",
                baseline_id="0206",
                path=path,
            )

            loaded = load_issue_tag_source(spec)

            false_trigger = loaded.suggestions["cn0206a"].public()
            self.assertEqual(
                false_trigger["annotation"]["tags"],
                ["queue", "scene_false_other"],
            )
            self.assertEqual(false_trigger["annotation"]["expected_output"], "误触发")
            self.assertTrue(false_trigger["annotation"]["is_excluded"])
            self.assertEqual(false_trigger["source"]["row_number"], 2)
            self.assertEqual(false_trigger["source"]["baseline_id"], "0206")
            self.assertEqual(len(false_trigger["source"]["sha256"]), 64)

            correct_trigger = loaded.suggestions["cn0626a"].public()
            self.assertEqual(
                correct_trigger["annotation"]["tags"],
                [
                    "true_eol",
                    "true_map_change",
                    "egress_waypoint",
                    "egress_takeover",
                ],
            )
            self.assertEqual(
                correct_trigger["annotation"]["expected_output"], "正确触发"
            )
            self.assertEqual(
                resolve_expected_output(
                    correct_trigger["annotation"]["expected_output"],
                    correct_trigger["annotation"]["tags"],
                    REVIEW_TAG_CATALOG,
                ),
                "正确触发",
            )

            no_assist = loaded.suggestions["cn0626b"].public()
            self.assertEqual(
                no_assist["annotation"]["tags"],
                ["obstacle_not_avoided", "lead_vehicle_departed"],
            )
            self.assertEqual(no_assist["annotation"]["expected_output"], "无需协助")
            self.assertIn("cnconflict", loaded.conflicted_issue_ids)
            self.assertNotIn("cnconflict", loaded.suggestions)

    def test_index_scopes_suggestions_and_keeps_missing_sources_nonfatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.xlsx"
            self._write_source(path)
            index = IssueTagSourceIndex()

            statuses = index.reload(
                [
                    IssueTagSourceSpec(
                        source_id="spotcheck-0206",
                        label="0206 抽检",
                        baseline_id="0206",
                        path=path,
                    ),
                    IssueTagSourceSpec(
                        source_id="spotcheck-0626",
                        label="0626 抽检",
                        baseline_id="0626",
                        path=root / "missing.xlsx",
                    ),
                ]
            )

            self.assertTrue(statuses[0]["available"])
            self.assertFalse(statuses[1]["available"])
            self.assertIsNotNone(
                index.lookup(baseline_id="0206", issue_id="cn0206a")
            )
            self.assertIsNone(index.lookup(baseline_id="0626", issue_id="cn0206a"))

    def test_index_exposes_and_verifies_historical_exclusion_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xlsx"
            self._write_source(path)
            index = IssueTagSourceIndex()
            index.reload(
                [
                    IssueTagSourceSpec(
                        source_id="spotcheck-0206",
                        label="0206 抽检",
                        baseline_id="0206",
                        path=path,
                    )
                ]
            )

            candidates = index.exclusion_candidates(baseline_ids=["0206"])

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate["issue_id"], "cn0206a")
            self.assertEqual(candidate["source"]["kind"], "historical_spotcheck_xlsx")
            self.assertEqual(candidate["source"]["column"], "是否排除")
            self.assertEqual(candidate["source"]["value"], "是")
            self.assertEqual(candidate["source"]["row_number"], 2)
            self.assertIn("SHA-256", candidate["comment"])
            self.assertEqual(
                index.resolve_exclusion_candidate(
                    issue_id="cn0206a", source=candidate["source"]
                ),
                candidate,
            )
            tampered = dict(candidate["source"])
            tampered["row_number"] = 999
            self.assertIsNone(
                index.resolve_exclusion_candidate(
                    issue_id="cn0206a", source=tampered
                )
            )

    def test_case_detail_exposes_a_scope_matched_read_only_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xlsx"
            self._write_source(path)
            index = IssueTagSourceIndex()
            index.reload(
                [
                    IssueTagSourceSpec(
                        source_id="spotcheck-0206",
                        label="0206 抽检",
                        baseline_id="0206",
                        path=path,
                    )
                ]
            )
            case = {
                "issue_id": "cn0206a",
                "baseline_scope": "release0206_1326_20260729",
                "annotations": [],
                "batch_jobs": [],
                "trail_url": "",
            }
            with patch.object(
                cases_router.database, "get_case", return_value=case
            ), patch(
                "ra_triage_dashboard.app.routers.cases.media_for_issue",
                return_value=None,
            ), patch(
                "ra_triage_dashboard.app.routers.cases.baseline_registry",
                SimpleNamespace(by_scope=lambda _scope: SimpleNamespace(id="0206")),
            ), patch(
                "ra_triage_dashboard.app.routers.cases.issue_tag_sources", index
            ), patch(
                "ra_triage_dashboard.app.routers.cases._case_external_links",
                return_value={},
            ):
                result = asyncio.run(cases_router.get_case("cn0206a"))

            self.assertEqual(
                result["issue_tag_suggestion"]["annotation"]["tags"],
                ["queue", "scene_false_other"],
            )
            self.assertEqual(
                result["issue_tag_suggestion"]["source"]["baseline_id"], "0206"
            )


if __name__ == "__main__":
    unittest.main()
