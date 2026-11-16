from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ra_triage_dashboard.app.routers import cases, core
from ra_triage_dashboard.app.support import identity as identity_support


class ReviewAssignmentPageAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(core.router, prefix="/manual")
        app.include_router(cases.router, prefix="/manual")
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)

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
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="reviewAssignmentsPage"', response.text)
            self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
            self.assertFalse(response.history)
            self.assertTrue(str(response.url).endswith(url))

    def test_admin_can_still_open_assignment_page(self) -> None:
        self.identity("admin")
        response = self.client.get("/manual/review-assignments")
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_open_assignment_page(self) -> None:
        self.identity("viewer")
        response = self.client.get("/manual/review-assignments")
        self.assertEqual(response.status_code, 403)

    def test_unverified_identity_cannot_use_claimed_admin_role(self) -> None:
        self.identity("admin", verified=False)
        response = self.client.get("/manual/review-assignments")
        self.assertEqual(response.status_code, 403)

    def test_writer_cannot_create_or_transfer_assignments(self) -> None:
        self.identity("writer")
        self.assertEqual(
            self.client.get("/manual/case-labeling/new-task").status_code, 403
        )
        self.assertEqual(
            self.client.post("/manual/api/cases/work-split", json={}).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                "/manual/api/cases/work-splits/example/assignments/cn123",
                json={"assignee": "other"},
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
