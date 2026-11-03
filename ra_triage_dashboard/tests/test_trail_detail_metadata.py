from __future__ import annotations

import json
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.trail_sync import (
    _detail_cache,
    ares_playback_metadata,
    read_trail_issue_metadata,
)
from ra_triage_dashboard.app.support.external_links import (
    _case_external_links,
    _case_link_metadata_fallback,
    resolve_disable_ra_simulation_version,
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
        "te_task_id_disabe_ra",
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
                "te_task_id_disabe_ra": 4515392300000101,
                "ra_stuck_auto_result_info": {
                    "ra_triage_dashboard": {"should_exclude": True},
                    "unrelated": "must-not-leak",
                },
                "unrelated_secret_field": "must-not-leak",
            }
        ]


class TrailDetailMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        _detail_cache.clear()
        self.addCleanup(_detail_cache.clear)

    def read_metadata(self, **overrides):
        return read_trail_issue_metadata(**{
            "ra_root": Path("/tmp/ra-auto-triage-test"),
            "issue_id": "cn31842459", "view_id": 2410, "cache_seconds": 300,
            **overrides,
        })

    def test_concurrent_navigation_uses_one_trail_query_and_copies_events(self):
        entered, release = threading.Event(), threading.Event()

        def loader(*_args):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"ra_event": [{"event": "start", "timestamp": 1778504337830}]}

        with patch("ra_triage_dashboard.app.trail_sync._read_trail_issue_metadata", side_effect=loader) as read:
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(self.read_metadata) for _ in range(6)]
                self.assertTrue(entered.wait(2))
                release.set()
                results = [future.result(timeout=2) for future in futures]
            self.assertEqual(read.call_count, 1)
            results[0]["ra_event"][0]["event"] = "modified"
            self.assertEqual(results[1]["ra_event"][0]["event"], "start")
            self.assertEqual(self.read_metadata()["ra_event"][0]["event"], "start")

    def test_negative_cache_backoff_expiry_and_explicit_disable(self):
        with patch("ra_triage_dashboard.app.timed_cache.time.monotonic") as clock, patch(
            "ra_triage_dashboard.app.trail_sync._read_trail_issue_metadata",
            side_effect=[{}, {"ra_id": "ready"}, {"ra_id": "refreshed"}, {}, {}],
        ) as read:
            clock.return_value = 100
            self.assertEqual(self.read_metadata(), {})
            clock.return_value = 129
            self.assertEqual(self.read_metadata(), {})
            self.assertEqual(read.call_count, 1)
            clock.return_value = 130
            self.assertEqual(self.read_metadata(), {"ra_id": "ready"})
            clock.return_value = 429
            self.assertEqual(self.read_metadata(), {"ra_id": "ready"})
            clock.return_value = 430
            self.assertEqual(self.read_metadata(), {"ra_id": "refreshed"})
            self.assertEqual(self.read_metadata(cache_seconds=0), {})
            self.assertEqual(self.read_metadata(cache_seconds=0), {})
            self.assertEqual(read.call_count, 5)

    def test_unavailable_trail_is_backed_off_and_view_and_root_are_separate(self):
        issue_utils = types.ModuleType("utils.get_ra_issue_utils")
        with patch.dict(sys.modules, {"utils": types.ModuleType("utils"), "utils.get_ra_issue_utils": issue_utils}), patch.object(
            issue_utils, "get_self_issue", side_effect=RuntimeError("offline"), create=True
        ) as read:
            self.assertEqual(self.read_metadata(), {})
            self.assertEqual(self.read_metadata(), {})
            self.assertEqual(read.call_count, 1)
            self.read_metadata(view_id=2411)
            self.read_metadata(ra_root=Path("/tmp/other-trail-test"))
            self.assertEqual(read.call_count, 3)

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
        self.assertEqual(metadata["te_task_id_disabe_ra"], "4515392300000101")
        self.assertEqual(metadata["ra_event"][0]["event"], "start")
        self.assertTrue(metadata["dashboard_should_exclude"])
        self.assertNotIn("unrelated_secret_field", metadata)

        playback = ares_playback_metadata(metadata, metadata["ra_event"])
        self.assertEqual(playback["ares_trip_id"], "10350_20260511_204156")
        self.assertEqual(playback["ares_timestamp_ms"], 1778504337849)

        metadata["te_task_version_disabe_ra"] = 1
        external_links = _case_external_links("cn31842459", metadata)
        self.assertEqual(
            external_links["disable_ra_simulation_url"],
            "https://voyager.intra.xiaojukeji.com/static/ares-animation/"
            "?task_id=4515392300000101&task_version=1",
        )
        self.assertEqual(
            external_links["disable_ra_simulation_task_id"],
            "4515392300000101",
        )
        self.assertEqual(external_links["disable_ra_simulation_task_version"], 1)

    def test_disable_ra_task_version_uses_highest_completed_retry(self) -> None:
        class Response:
            def __init__(self, payload: dict[str, object]):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, *, timeout):
            self.assertGreater(timeout, 0)
            version = json.loads(request.data)["version"]
            return Response(
                {
                    "code": 0,
                    "data": {
                        "version": version,
                        "result": {"trip_id": "trip"} if version <= 1 else {},
                    },
                }
            )

        with patch(
            "ra_triage_dashboard.app.support.external_links.urlopen",
            side_effect=fake_urlopen,
        ):
            version = resolve_disable_ra_simulation_version(
                "4546661100000025",
                cache_seconds=0,
            )
        self.assertEqual(version, 1)

    def test_invalid_disable_ra_task_id_does_not_create_external_link(self) -> None:
        external_links = _case_external_links(
            "cn31842459", {"te_task_id_disabe_ra": "javascript:alert(1)"}
        )
        self.assertEqual(external_links["disable_ra_simulation_url"], "")

    def test_imported_disable_ra_task_id_is_available_as_fallback(self) -> None:
        metadata = _case_link_metadata_fallback(
            {"extra": {"te_task_id_disabe_ra": "4515392300000101"}}
        )
        self.assertEqual(metadata["te_task_id_disabe_ra"], "4515392300000101")

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
