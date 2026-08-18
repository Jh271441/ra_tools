from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.trail_sync import (
    ares_playback_metadata,
    read_trail_issue_metadata,
)


class _Frame:
    columns = [
        "issue_id",
        "ra_id",
        "ra_event",
        "car_id",
        "trip_id",
        "ra_start_timestamp",
        "ra_end_timestamp",
        "ra_stuck_auto_result_info",
        "unrelated_secret_field",
    ]

    def __len__(self) -> int:
        return 1

    def to_dict(self, orient: str = "records") -> list[dict[str, object]]:
        assert orient == "records"
        return [
            {
                "issue_id": "cn31842459",
                "ra_id": "10350_1119_1778504337830_100",
                "ra_event": [
                    {"event": "start", "value": "StuckModel-50", "timestamp": 1778504337830},
                    {"event": "exit", "value": 8.65, "timestamp": 1778504346478},
                ],
                "car_id": 10350,
                "trip_id": "10350_20260511_204156",
                "ra_start_timestamp": 1778504337849,
                "ra_end_timestamp": 1778504346456,
                "ra_stuck_auto_result_info": {
                    "ra_triage_dashboard": {"should_exclude": True},
                    "unrelated": "must-not-leak",
                },
                "unrelated_secret_field": "must-not-leak",
            }
        ]


class TrailDetailMetadataTest(unittest.TestCase):
    def test_only_allowlisted_metadata_is_returned(self) -> None:
        utils_module = types.ModuleType("utils")
        issue_utils_module = types.ModuleType("utils.get_ra_issue_utils")

        def get_self_issue(condition, *, view_id, size):
            self.assertEqual(view_id, 2410)
            self.assertEqual(size, 1)
            self.assertEqual(condition[0]["attr_id"], "issue_id")
            return _Frame()

        issue_utils_module.get_self_issue = get_self_issue
        with patch.dict(
            sys.modules,
            {
                "utils": utils_module,
                "utils.get_ra_issue_utils": issue_utils_module,
            },
        ):
            metadata = read_trail_issue_metadata(
                ra_root=Path("/tmp/ra-auto-triage-test"),
                issue_id="cn31842459",
                view_id=2410,
                cache_seconds=300,
            )

        self.assertEqual(metadata["ra_id"], "10350_1119_1778504337830_100")
        self.assertEqual(metadata["car_id"], "10350")
        self.assertEqual(metadata["ra_event"][0]["event"], "start")
        self.assertTrue(metadata["dashboard_should_exclude"])
        self.assertNotIn("unrelated_secret_field", metadata)

        playback = ares_playback_metadata(metadata, metadata["ra_event"])
        self.assertEqual(playback["ares_trip_id"], "10350_20260511_204156")
        self.assertEqual(playback["ares_timestamp_ms"], 1778504337849)

    def test_start_event_is_ares_timestamp_fallback(self) -> None:
        playback = ares_playback_metadata(
            {
                "trip_id": "10350_20260511_204156",
            },
            [{"event": "start", "value": "StuckModel-50", "timestamp": 1778504337830}],
        )
        self.assertEqual(playback["ares_timestamp_ms"], 1778504337830)


if __name__ == "__main__":
    unittest.main()
