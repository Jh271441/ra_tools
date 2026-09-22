from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import run_collections as api


class RunCollectionsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "api.sqlite3")
        self.database.init()
        self.database.upsert_issues(
            [{"issue_id": "api-a", "gt_label": "正确触发"}],
            source="api-test", replace_gt=True, baseline_scope="api-scope",
        )
        self.run, _ = self.database.import_model_run(
            name="api-run", source_name="api-run.json", source_sha256="api-run-collections-test",
            metadata={}, rows=[{"issue_id": "api-a", "model_label": "正确触发"}],
        )
        self.candidate, _ = self.database.import_model_run(
            name="api-candidate", source_name="api-candidate.json", source_sha256="api-run-collections-candidate-test",
            metadata={}, rows=[{"issue_id": "api-a", "model_label": "误触发"}],
        )

    @staticmethod
    def request(method: str, path: str, body: dict, *, idempotency_key: str = "") -> Request:
        body_bytes = json.dumps(body).encode("utf-8")
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        headers = [(b"content-type", b"application/json")]
        if idempotency_key:
            headers.append((b"idempotency-key", idempotency_key.encode("ascii")))
        scope = {
            "type": "http", "method": method, "path": path,
            "headers": headers, "query_string": b"", "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 12345),
        }
        return Request(scope, receive)

    def test_verified_admin_api_freezes_collection_and_evaluation(self) -> None:
        identity = SimpleNamespace(username="verified-admin", source="test-sso", verified=True)
        with patch.object(api, "database", self.database), patch.object(api, "_admin_identity", return_value=identity):
            collection = asyncio.run(api.create_run_collection(self.request(
                "POST", "/api/run-collections",
                {"name": "API collection", "members": [{"run_id": self.run["id"], "is_reference": True}]},
                idempotency_key="api-collection-create",
            )))
            self.assertTrue(collection["created_by_verified"])
            self.assertEqual(collection["created_by_source"], "test-sso")
            evaluation = asyncio.run(api.create_run_evaluation(self.request(
                "POST", "/api/run-evaluations",
                {
                    "collection_id": collection["id"],
                    "baseline_scopes": ["api-scope"],
                    "reference_type": "gt",
                },
                idempotency_key="api-evaluation-create",
            )))
            self.assertTrue(evaluation["created_by_verified"])
            self.assertEqual(evaluation["created_by_source"], "test-sso")
            restored = asyncio.run(api.get_run_evaluation(evaluation["id"], page=1, page_size=10))
            self.assertEqual(restored["context_sha256"], evaluation["context_sha256"])
            self.assertEqual(restored["summary"]["runs"][0]["accuracy"], 1.0)

    def test_unverified_writer_is_rejected_before_collection_mutation(self) -> None:
        with patch.object(api, "database", self.database), patch.object(
            api, "_admin_identity", side_effect=HTTPException(status_code=403, detail="verified admin only")
        ):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.create_run_collection(self.request(
                    "POST", "/api/run-collections",
                    {"name": "Rejected", "members": [self.run["id"]]},
                )))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.database.list_run_collections(), [])

    def test_pairwise_save_preserves_baseline_candidate_order(self) -> None:
        identity = SimpleNamespace(username="verified-admin", source="test-sso", verified=True)
        request = self.request(
            "POST", "/api/run-comparison/save-collection",
            {
                "baseline_run_id": self.run["id"],
                "candidate_run_id": self.candidate["id"],
                "name": "Saved Pairwise",
            },
            idempotency_key="api-pairwise-save",
        )
        original_url = str(request.url)
        with patch.object(api, "database", self.database), patch.object(api, "_admin_identity", return_value=identity):
            collection = asyncio.run(api.save_pairwise_as_collection(request))
        self.assertEqual([item["run_id"] for item in collection["current"]["members"]], [self.run["id"], self.candidate["id"]])
        self.assertTrue(collection["current"]["members"][0]["is_reference"])
        self.assertEqual(str(request.url), original_url)

    def test_prediction_reference_is_rejected_and_reference_run_stays_comparison_only(self) -> None:
        identity = SimpleNamespace(username="verified-admin", source="test-sso", verified=True)
        with patch.object(api, "database", self.database), patch.object(api, "_admin_identity", return_value=identity):
            collection = asyncio.run(api.create_run_collection(self.request(
                "POST", "/api/run-collections",
                {"name": "API reference", "members": [{"run_id": self.run["id"]}]},
                idempotency_key="api-reference-collection",
            )))
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.create_run_evaluation(self.request(
                    "POST", "/api/run-evaluations",
                    {
                        "collection_id": collection["id"],
                        "baseline_scopes": ["api-scope"],
                        "reference_type": "run",
                        "reference_id": self.run["id"],
                    },
                    idempotency_key="api-run-reference",
                )))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("comparison_reference_run_id", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
