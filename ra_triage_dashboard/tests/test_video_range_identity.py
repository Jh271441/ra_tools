"""One native download must never combine original and short-GOP MP4 bytes."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ra_triage_dashboard.app.routers import cases


class VideoRangeIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.original = Path(folder.name) / "source.mp4"
        self.copy = Path(folder.name) / "copy.mp4"
        self.original.write_bytes(bytes(range(256)) * 256)
        self.copy.write_bytes(bytes(reversed(range(256))) * 257)
        self.provider = MagicMock()
        self.provider.get_asset_path.return_value = self.original
        for target, name, value in [
            (cases.database, "get_issue", {"baseline_scope": "strict"}),
            (cases, "media_for_issue", self.provider),
            (cases.video_playback_cache, "request", None),
            (cases.video_playback_cache, "get", None),
        ]:
            patcher = patch.object(target, name, return_value=value)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if target is cases.video_playback_cache:
                setattr(self, name, mocked)
        prefix = patch.object(cases, "_public_path", side_effect=lambda path: "/manual" + path)
        prefix.start()
        self.addCleanup(prefix.stop)
        app = FastAPI()
        app.add_api_route("/manual/api/assets/{issue_id}/{asset_id}", cases.get_asset)
        self.client = AsyncClient(transport=ASGITransport(app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.entry = "/manual/api/assets/cn1/bev-video-0?playback=short-gop-v1"

    async def select(self):
        response = await self.client.get(self.entry, headers={"Range": "bytes=0-1023"})
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.content, b"")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertTrue(response.headers["location"].startswith("/manual/api/assets/cn1/"))
        return response.headers["location"]

    async def test_cold_ranges_stay_original_after_copy_becomes_ready(self):
        url = await self.select()
        first = await self.client.get(url, headers={"Range": "bytes=0-1023"})
        self.assertEqual(first.content, self.original.read_bytes()[:1024])
        self.request.return_value = self.get.return_value = self.copy
        ranges = [(n * 1024, (n + 1) * 1024 - 1) for n in range(1, 13)]
        responses = await asyncio.gather(*[
            self.client.get(url, headers={"Range": f"bytes={lo}-{hi}"}) for lo, hi in ranges
        ])
        for (lo, hi), response in zip(ranges, responses):
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, self.original.read_bytes()[lo:hi + 1])
            self.assertEqual(response.headers["content-range"], f"bytes {lo}-{hi}/65536")
            self.assertEqual(response.headers["etag"], first.headers["etag"])
            self.assertEqual(response.headers["x-video-playback"], "original")
        self.request.assert_called_once_with(self.original)
        self.get.assert_not_called()
        # A separate playback can choose the ready copy without changing this one.
        warm_url = await self.select()
        self.assertNotEqual(warm_url, url)
        warm = await self.client.get(warm_url, headers={"Range": "bytes=1024-2047"})
        self.assertEqual(warm.content, self.copy.read_bytes()[1024:2048])
        self.assertEqual(warm.headers["content-range"], "bytes 1024-2047/65792")
        self.assertNotEqual(warm.headers["etag"], first.headers["etag"])

    async def test_lost_or_replaced_copy_fails_closed_without_original_bytes(self):
        self.request.return_value = self.get.return_value = self.copy
        url = await self.select()
        self.get.return_value = None
        missing = await self.client.get(url, headers={"Range": "bytes=1024-2047"})
        self.assertEqual(missing.status_code, 409)
        self.get.return_value = self.copy
        self.copy.write_bytes(b"a different MP4")
        replaced = await self.client.get(url, headers={"Range": "bytes=1024-2047"})
        self.assertEqual(replaced.status_code, 409)
        self.assertNotEqual(replaced.content, self.original.read_bytes()[1024:2048])
        self.request.assert_called_once_with(self.original)

    async def test_changed_original_or_revoked_scope_cannot_reuse_old_version(self):
        url = await self.select()
        self.original.write_bytes(b"new capture")
        response = await self.client.get(url, headers={"Range": "bytes=0-3"})
        self.assertEqual(response.status_code, 409)
        self.provider.get_asset_path.return_value = None
        response = await self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.request.assert_called_once_with(self.original)

    async def test_redirect_and_version_preserve_range_and_conditional_range(self):
        first = await self.client.get(self.entry, headers={"Range": "bytes=2048-3071"}, follow_redirects=True)
        self.assertEqual(first.status_code, 206)
        self.assertEqual(first.content, self.original.read_bytes()[2048:3072])
        self.assertEqual(len(first.history), 1)
        tail = await self.client.get(first.url, headers={"Range": "bytes=-1024", "If-Range": first.headers["etag"]})
        self.assertEqual(tail.status_code, 206)
        self.assertEqual(tail.content, self.original.read_bytes()[-1024:])
        stale = await self.client.get(first.url, headers={"Range": "bytes=0-1023", "If-Range": '"old"'})
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(stale.content, self.original.read_bytes())
        invalid = await self.client.get(first.url, headers={"Range": "bytes=65536-"})
        self.assertEqual(invalid.status_code, 416)


if __name__ == "__main__":
    unittest.main()
