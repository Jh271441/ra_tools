from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ra_triage_dashboard.app import case_media
from ra_triage_dashboard.app.routers import cases as cases_router


class DeferredCaseMediaTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolver_starts_bev_and_video_before_camera(self) -> None:
        """The independent BEV/video scans must overlap on a cold volume."""

        asset_started = threading.Event()
        video_started = threading.Event()
        camera_timestamps: list[int | None] = []

        class Provider:
            def get_assets(self, issue_id: str):
                self.assertEqual(issue_id, "cn00000001")
                asset_started.set()
                if not video_started.wait(timeout=1):
                    raise AssertionError("video scan was serialised after BEV")
                return {
                    "available": True,
                    "issue_id": issue_id,
                    "frames": [
                        {
                            "url": "/manual/api/assets/cn00000001/bev-0",
                            "offset_ms": 0,
                        }
                    ],
                    "capture": {"timestamp_ms": 123},
                }

            def get_video(self, issue_id: str):
                self.assertEqual(issue_id, "cn00000001")
                video_started.set()
                if not asset_started.wait(timeout=1):
                    raise AssertionError("BEV scan did not start with video")
                return {"url": "/manual/api/assets/cn00000001/bev-video-0"}

            def get_camera_assets(self, issue_id: str, timestamp_ms: int | None):
                self.assertEqual(issue_id, "cn00000001")
                camera_timestamps.append(timestamp_ms)
                return {
                    "available": False,
                    "issue_id": issue_id,
                    "frames": [],
                    "capture": {},
                }

            # Bind unittest assertions so worker-thread failures remain useful.
            assertEqual = unittest.TestCase().assertEqual

        assets, camera = await case_media.resolve_case_media(Provider(), "cn00000001")

        self.assertEqual(camera_timestamps, [123])
        self.assertEqual(assets["video"]["poster_url"], "/manual/api/assets/cn00000001/bev-0")
        self.assertFalse(camera["available"])

    async def test_core_case_detail_defers_provider_media_calls(self) -> None:
        provider = MagicMock()
        case = {
            "issue_id": "cn00000001",
            "baseline_scope": "release0206_1326",
            "annotations": [],
            "batch_jobs": [],
        }
        with patch.object(cases_router.database, "get_case", return_value=case), patch(
            "ra_triage_dashboard.app.routers.cases.media_for_issue",
            return_value=provider,
        ), patch(
            "ra_triage_dashboard.app.routers.cases.baseline_registry",
            SimpleNamespace(by_scope=lambda _scope: SimpleNamespace(id="0206")),
        ), patch(
            "ra_triage_dashboard.app.routers.cases.issue_tag_sources",
            SimpleNamespace(lookup=lambda **_kwargs: None),
        ), patch(
            "ra_triage_dashboard.app.routers.cases._case_external_links",
            return_value={},
        ):
            result = await cases_router.get_case(
                "cn00000001",
                include_media=False,
            )

        self.assertEqual(result["media_status"], "pending")
        self.assertFalse(result["assets"]["available"])
        provider.get_assets.assert_not_called()
        provider.get_video.assert_not_called()
        provider.get_camera_assets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
