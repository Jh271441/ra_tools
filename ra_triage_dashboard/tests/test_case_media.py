from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ra_triage_dashboard.app import case_media
from ra_triage_dashboard.app.routers import cases as cases_router


class DeferredCaseMediaTest(unittest.IsolatedAsyncioTestCase):
    def test_blind_review_history_reveals_peers_only_after_own_submission(self) -> None:
        annotations = [
            {"id": 1, "author": "legacy", "work_split_id": ""},
            {"id": 2, "author": "alice", "work_split_id": "split-1"},
            {"id": 3, "author": "bob", "work_split_id": "split-1"},
            {"id": 4, "author": "carol", "work_split_id": "split-old"},
        ]
        assignment = {
            "mode": "blind",
            "split_id": "split-1",
            "assigned": True,
            "own_assignment": {"username": "alice", "submitted": False},
        }
        visible, peers_visible = cases_router._visible_case_annotations(
            annotations,
            assignment,
            username="ALICE",
            identity_verified=True,
        )
        self.assertEqual([item["id"] for item in visible], [2])
        self.assertFalse(peers_visible)

        assignment["own_assignment"]["submitted"] = True
        visible, peers_visible = cases_router._visible_case_annotations(
            annotations,
            assignment,
            username="alice",
            identity_verified=True,
        )
        self.assertEqual([item["id"] for item in visible], [2, 3])
        self.assertTrue(peers_visible)

        assignment["assigned"] = False
        assignment["own_assignment"] = None
        visible, peers_visible = cases_router._visible_case_annotations(
            annotations,
            assignment,
            username="outsider",
            identity_verified=True,
        )
        self.assertEqual([item["id"] for item in visible], [1])
        self.assertFalse(peers_visible)

        visible, peers_visible = cases_router._visible_case_annotations(
            annotations,
            assignment,
            username="admin",
            identity_verified=True,
            admin_reveal=True,
        )
        self.assertEqual([item["id"] for item in visible], [2, 3])
        self.assertTrue(peers_visible)

    async def test_image_only_routes_never_scan_video_or_full_case(self):
        provider = MagicMock()
        provider.get_assets.return_value = {"frames": [{"offset_ms": 0}], "capture": {"timestamp_ms": 123}, "video": {"url": "unused"}}
        provider.get_camera_assets.return_value = {"frames": [{"offset_ms": 0}]}
        with patch.object(cases_router.database, "get_issue", return_value={"baseline_scope": "scope", "gt_label": "误触发"}), patch.object(cases_router.database, "get_case") as full_case, patch.object(cases_router, "media_for_issue", return_value=provider):
            bev = await cases_router.get_case_media("cn1", kind="bev")
            provider.get_camera_assets.assert_not_called()
            self.assertNotIn("video", bev["assets"])
            images = await cases_router.get_case_media("cn1", kind="images")
            self.assertEqual(images["camera"]["frames"][0]["offset_ms"], 0)
            provider.get_camera_assets.assert_called_once_with("cn1", 123)
            provider.get_video.assert_not_called()
            full_case.assert_not_called()

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
