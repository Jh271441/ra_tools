from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi import FastAPI

from ra_triage_dashboard.app.routers import cases, core
from ra_triage_dashboard.app.support import identity as identity_support


class ReviewAssignmentPageAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(core.router, prefix="/manual")
        self.app.include_router(cases.router, prefix="/manual")
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)

    def request(self, method: str, url: str):
        """Exercise the HTTP routes without optional HTTP-client dependencies."""
        parsed = urlsplit(url)
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(self.app({
            "type": "http", "asgi": {"version": "3.0"},
            "http_version": "1.1", "method": method, "scheme": "http",
            "path": parsed.path, "query_string": parsed.query.encode(),
            "root_path": "", "headers": [],
            "client": ("127.0.0.1", 12345), "server": ("test", 80),
        }, receive, send))
        start = next(item for item in messages if item["type"] == "http.response.start")
        return SimpleNamespace(
            status_code=start["status"],
            headers={key.decode(): value.decode() for key, value in start["headers"]},
            text=b"".join(item.get("body", b"") for item in messages).decode(),
        )

    def identity(self, role: str, *, verified: bool = True):
        actor = SimpleNamespace(
            username="reviewer", verified=verified, source="test"
        )
        self.patches.enter_context(patch.object(
            identity_support, "request_identity", return_value=actor
        ))
        self.patches.enter_context(patch.object(
            identity_support.database, "access_role", return_value=role
        ))

    def test_writer_can_open_and_refresh_shared_assignment_page(self) -> None:
        self.identity("writer")
        url = (
            "/manual/review-assignments?lifecycle=current"
            "&baselines=version-20261030&split=example&page=2&page_size=20"
        )
        for _ in range(2):
            response = self.request("GET", url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="reviewAssignmentsPage"', response.text)
            self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
            self.assertNotIn("location", response.headers)

    def test_admin_can_still_open_assignment_page(self) -> None:
        self.identity("admin")
        response = self.request("GET", "/manual/review-assignments")
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_open_assignment_page(self) -> None:
        self.identity("viewer")
        response = self.request("GET", "/manual/review-assignments")
        self.assertEqual(response.status_code, 403)

    def test_unverified_identity_cannot_use_claimed_admin_role(self) -> None:
        self.identity("admin", verified=False)
        response = self.request("GET", "/manual/review-assignments")
        self.assertEqual(response.status_code, 403)

    def test_writer_cannot_create_or_transfer_assignments(self) -> None:
        self.identity("writer")
        self.assertEqual(
            self.request("GET", "/manual/case-labeling/new-task").status_code, 403
        )
        self.assertEqual(
            self.request("POST", "/manual/api/cases/work-split").status_code,
            403,
        )
        self.assertEqual(
            self.request(
                "PATCH",
                "/manual/api/cases/work-splits/example/assignments/cn123",
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
