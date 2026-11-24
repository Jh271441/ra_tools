"""Regression tests for Phase 0 concurrency, AI naming resilience, ASGI guards, and offloaded gzip."""
from __future__ import annotations

import asyncio
import gzip
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import JSONResponse

from ra_triage_dashboard.app.auth import SessionIdentity
from ra_triage_dashboard.app.contracts import MAX_DEFAULT_JSON_REQUEST_BYTES
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.intent_name_suggestion import (
    IntentNameSuggestionError,
    _suggestion_runtime,
    reset_name_suggestion_runtime,
    suggest_assignment_name_with_llm,
)
from ra_triage_dashboard.app.middleware import (
    BasePathTimingAndSecurityMiddleware,
    ProductionWriteGuardMiddleware,
    RequestSizeGuardMiddleware,
)
from ra_triage_dashboard.app.response_compression import TextResponseCompressionMiddleware
from ra_triage_dashboard.app.support import identity as identity_support


def _run_asgi(
    app,
    *,
    method: str = "GET",
    path: str = "/api/cases",
    headers: list[tuple[bytes, bytes]] | None = None,
    chunks: list[bytes] | None = None,
):
    async def _invoke():
        body_chunks = list(chunks or [b""])
        idx = 0
        messages = []

        async def receive():
            nonlocal idx
            if idx < len(body_chunks):
                data = body_chunks[idx]
                idx += 1
                return {"type": "http.request", "body": data, "more_body": idx < len(body_chunks)}
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": list(headers or []),
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8785),
            "state": {},
        }
        await app(scope, receive, send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return int(start["status"]), dict(start["headers"]), body, scope

    return asyncio.run(_invoke())


class Phase0LockFreePreviewTest(unittest.TestCase):
    def _seed_campaign(self, tmp: str) -> tuple[Database, str]:
        db = Database(Path(tmp) / "phase0.sqlite")
        db.init()
        db.set_access_user(username="alice", role="writer", actor="admin")
        db.set_access_user(username="bob", role="writer", actor="admin")
        ids = [f"cn{i:04d}" for i in range(1, 21)]
        db.upsert_issues(
            [{"issue_id": iid, "gt_label": "误触发"} for iid in ids],
            source="test",
            replace_gt=True,
            baseline_scope="scope0",
        )
        db.apply_gt_sync_snapshot(
            scope="scope0",
            rows=[{"issue_id": iid, "gt_label": "误触发"} for iid in ids],
            source_name="Trail",
            source_view_id=1000,
            source_field="gt",
            trigger="test",
            requested_by="tester",
            requested_by_source="test",
            requested_by_verified=True,
            expected_issue_ids=ids,
        )
        ws = db.create_review_workset(
            baseline_scope="scope0", issue_ids=ids, created_by="alice"
        )
        created = db.create_campaign(
            spec={
                "purpose": "labeling",
                "workset_id": ws["id"],
                "overlap_ratio": 0,
                "members": [
                    {"issue_id": iid, "assignees": ["alice" if idx < 10 else "bob"]}
                    for idx, iid in enumerate(ids)
                ],
            },
            actor="alice",
        )
        return db, created["campaign"]["id"]

    def test_get_and_preview_campaign_allocation_do_not_acquire_global_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, cid = self._seed_campaign(tmp)
            try:
                with patch.object(
                    db,
                    "_lock_task_work",
                    side_effect=AssertionError("read-only preview must not acquire _lock_task_work"),
                ):
                    current = db.get_campaign_allocation(cid)
                    self.assertEqual(current["member_count"], 20)
                    preview = db.preview_campaign_allocation(
                        campaign_id=cid,
                        assignees=[
                            {"name": "alice", "review_percent": 70},
                            {"name": "bob", "review_percent": 30},
                        ],
                        reviewers_per_issue=1,
                        overlap_ratio=0,
                        expected_revision=current["expected_revision"],
                    )
                    self.assertEqual(preview["total_slots"], 20)
                    grouped = db.preview_campaign_allocation(
                        campaign_id=cid,
                        assignees=[],
                        reviewers_per_issue=1,
                        overlap_ratio=0,
                        expected_revision=current["expected_revision"],
                        groups=[
                            {
                                "group_id": "group-1",
                                "coverage_percent": 100,
                                "members": [
                                    {"name": "alice", "review_percent": 65},
                                    {"name": "bob", "review_percent": 35},
                                ],
                            }
                        ],
                    )
                    self.assertEqual(grouped["total_slots"], 20)
                    removal = db.preview_campaign_member_removal(
                        campaign_id=cid,
                        assignee="bob",
                        expected_revision=current["expected_revision"],
                    )
                    self.assertEqual(removal["removed_assignee"], "bob")
            finally:
                db.close()

    def test_preview_succeeds_concurrently_while_write_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db, cid = self._seed_campaign(tmp)
            try:
                current = db.get_campaign_allocation(cid)
                lock_acquired = threading.Event()
                release_lock = threading.Event()
                preview_result: dict[str, object] = {}
                preview_error: list[BaseException] = []

                def _hold_write_lock() -> None:
                    with db._write_lock:
                        lock_acquired.set()
                        release_lock.wait(timeout=5.0)

                def _run_preview() -> None:
                    try:
                        preview_result["data"] = db.preview_campaign_allocation(
                            campaign_id=cid,
                            assignees=[
                                {"name": "alice", "review_percent": 60},
                                {"name": "bob", "review_percent": 40},
                            ],
                            reviewers_per_issue=1,
                            overlap_ratio=0,
                            expected_revision=current["expected_revision"],
                        )
                    except BaseException as exc:  # pragma: no cover
                        preview_error.append(exc)

                holder = threading.Thread(target=_hold_write_lock, daemon=True)
                holder.start()
                self.assertTrue(lock_acquired.wait(timeout=2.0))
                try:
                    worker = threading.Thread(target=_run_preview, daemon=True)
                    worker.start()
                    worker.join(timeout=3.0)
                    self.assertFalse(worker.is_alive(), "preview blocked on _write_lock")
                finally:
                    release_lock.set()
                    holder.join(timeout=2.0)

                self.assertEqual(preview_error, [])
                self.assertEqual(preview_result["data"]["total_slots"], 20)
            finally:
                db.close()


class Phase0NameSuggestionResilienceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_name_suggestion_runtime()

    def tearDown(self) -> None:
        reset_name_suggestion_runtime()

    def _call_kwargs(self) -> dict[str, object]:
        return dict(
            fallback="0508 Case标注 2人均分 1071 Case",
            dataset_labels=["0508 · 1071"],
            assignment_kind="case_labeling",
            case_count=1071,
            reviewers_per_issue=1,
            overlap_ratio=0,
            member_count=2,
        )

    def test_cache_hit_and_bypass_cache(self) -> None:
        calls = {"count": 0}

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _size):
                return json.dumps({
                    "choices": [{"message": {"content": "0508 Case标注 2人均分 1071 Case"}}]
                }).encode("utf-8")

        class _Opener:
            def open(self, request, timeout):
                calls["count"] += 1
                assert timeout == 8
                return _Resp()

        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_Opener()),
        ):
            r1 = suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
            r2 = suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
            r3 = suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), bypass_cache=True, **self._call_kwargs())

        self.assertEqual(r1, "0508 Case标注 2人均分 1071 Case")
        self.assertEqual(r2, r1)
        self.assertEqual(r3, r1)
        self.assertEqual(calls["count"], 2)

    def test_single_flight_deduplicates_concurrent_requests(self) -> None:
        calls = {"count": 0}
        entered = threading.Event()
        release = threading.Event()

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _size):
                return json.dumps({
                    "choices": [{"message": {"content": "0508 Case标注 2人均分 1071 Case"}}]
                }).encode("utf-8")

        class _SlowOpener:
            def open(self, request, timeout):
                calls["count"] += 1
                entered.set()
                release.wait(timeout=3.0)
                return _Resp()

        results: list[str] = []

        def _worker():
            results.append(
                suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
            )

        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_SlowOpener()),
        ):
            t1 = threading.Thread(target=_worker)
            t2 = threading.Thread(target=_worker)
            t1.start()
            self.assertTrue(entered.wait(timeout=2.0))
            t2.start()
            time.sleep(0.05)
            release.set()
            t1.join(timeout=3.0)
            t2.join(timeout=3.0)

        self.assertEqual(calls["count"], 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])

    def test_circuit_breaker_opens_after_transport_failures_and_recovers(self) -> None:
        calls = {"count": 0}

        class _FailingOpener:
            def open(self, request, timeout):
                calls["count"] += 1
                raise TimeoutError("slow gateway")

        class _OkResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _size):
                return json.dumps({
                    "choices": [{"message": {"content": "0508 Case标注 2人均分 1071 Case"}}]
                }).encode("utf-8")

        class _OkOpener:
            def open(self, request, timeout):
                calls["count"] += 1
                return _OkResp()

        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_FailingOpener()),
        ):
            for _ in range(3):
                with self.assertRaises(IntentNameSuggestionError) as ctx:
                    suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
                self.assertEqual(ctx.exception.reason, "timeout")
            self.assertEqual(calls["count"], 3)

            # Circuit is now open: 4th call fails fast without touching upstream opener.
            with self.assertRaises(IntentNameSuggestionError) as ctx:
                suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
            self.assertEqual(ctx.exception.reason, "unavailable")
            self.assertEqual(calls["count"], 3)

        # Expire cooldown and verify half-open probe succeeds and closes breaker.
        _suggestion_runtime._circuit_open_until = time.monotonic() - 1.0
        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_OkOpener()),
        ):
            recovered = suggest_assignment_name_with_llm(SimpleNamespace(), SimpleNamespace(), **self._call_kwargs())
        self.assertEqual(recovered, "0508 Case标注 2人均分 1071 Case")
        self.assertEqual(calls["count"], 4)


class Phase0MiddlewareAndCompressionTest(unittest.TestCase):
    def test_streaming_size_guard_rejects_oversized_declared_and_chunked_json(self) -> None:
        async def echo_app(scope, receive, send):
            request = Request(scope, receive)
            data = await request.body()
            resp = JSONResponse({"size": len(data)})
            await resp(scope, receive, send)

        wrapped = RequestSizeGuardMiddleware(echo_app)

        # Declared Content-Length > 2 MiB on generic write route -> 413 immediately.
        status, _, _, _ = _run_asgi(
            wrapped,
            method="POST",
            path="/api/campaigns",
            headers=[(b"content-length", str(MAX_DEFAULT_JSON_REQUEST_BYTES + 1).encode())],
            chunks=[b"{}"],
        )
        self.assertEqual(status, 413)

        # Chunked (no Content-Length) streaming > 2 MiB on generic write route -> 413.
        half = b"a" * (MAX_DEFAULT_JSON_REQUEST_BYTES // 2 + 1024)
        status, _, _, _ = _run_asgi(
            wrapped,
            method="POST",
            path="/api/cases/cn1/annotations",
            headers=[],
            chunks=[half, half],
        )
        self.assertEqual(status, 413)

        # Normal JSON payload passes through.
        status, _, body, _ = _run_asgi(
            wrapped,
            method="POST",
            path="/api/campaigns",
            headers=[(b"content-length", b"2")],
            chunks=[b"{}"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"size": 2})

        # Large import route allows > 2 MiB (up to 64 MiB).
        status, _, _, _ = _run_asgi(
            wrapped,
            method="POST",
            path="/api/import/model-results",
            headers=[],
            chunks=[half, half],
        )
        self.assertEqual(status, 200)

        # Artifact route is left untouched by default JSON guard.
        status, _, _, _ = _run_asgi(
            wrapped,
            method="POST",
            path="/api/artifacts",
            headers=[],
            chunks=[half, half],
        )
        self.assertEqual(status, 200)

    def test_base_path_timing_and_default_security_headers(self) -> None:
        seen_paths: list[str] = []

        async def ok_app(scope, receive, send):
            seen_paths.append(scope["path"])
            resp = JSONResponse({"ok": True})
            await resp(scope, receive, send)

        settings = SimpleNamespace(base_path="/manual")
        wrapped = BasePathTimingAndSecurityMiddleware(ok_app, settings=settings)

        status, headers, _, _ = _run_asgi(wrapped, method="GET", path="/manual/api/cases")
        self.assertEqual(status, 200)
        self.assertEqual(seen_paths[-1], "/api/cases")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(headers[b"referrer-policy"], b"strict-origin-when-cross-origin")
        self.assertEqual(headers[b"x-frame-options"], b"SAMEORIGIN")
        self.assertIn(b"server-timing", headers)
        self.assertIn(b"x-request-duration-ms", headers)

        # Artifact paths keep their own headers untouched.
        status, art_headers, _, _ = _run_asgi(wrapped, method="GET", path="/manual/artifacts/demo/frame")
        self.assertEqual(status, 200)
        self.assertEqual(seen_paths[-1], "/artifacts/demo/frame")
        self.assertNotIn(b"x-frame-options", art_headers)

    def test_production_write_guard_caches_verified_identity_for_downstream_helpers(self) -> None:
        id_calls = {"identity": 0, "role": 0}
        fake_settings = SimpleNamespace(deployment_mode="production")

        class _FakeDb:
            def access_role(self, username: str) -> str:
                id_calls["role"] += 1
                return "admin" if username == "alice" else ""

        fake_db = _FakeDb()

        def _fake_request_identity(_req, _cfg):
            id_calls["identity"] += 1
            return SessionIdentity(username="alice", source="kylin_ticket", authenticated=True, verified=True)

        async def downstream(scope, receive, send):
            req = Request(scope, receive)
            resolved = identity_support._admin_identity(req)
            resp = JSONResponse({"actor": resolved.username})
            await resp(scope, receive, send)

        wrapped = ProductionWriteGuardMiddleware(downstream, settings=fake_settings, database=fake_db)
        with (
            patch("ra_triage_dashboard.app.middleware.request_identity", side_effect=_fake_request_identity),
            patch.object(identity_support, "settings", fake_settings),
            patch.object(identity_support, "database", fake_db),
            patch.object(identity_support, "request_identity", side_effect=_fake_request_identity),
        ):
            status, _, body, _ = _run_asgi(
                wrapped,
                method="POST",
                path="/api/campaigns",
                headers=[(b"x-ra-triage-request", b"browser-v1")],
                chunks=[b"{}"],
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"actor": "alice"})
        self.assertEqual(id_calls["identity"], 1)
        self.assertEqual(id_calls["role"], 1)

    def test_large_gzip_response_offloads_to_thread_and_preserves_bytes(self) -> None:
        payload = b'{"data":"' + (b"x" * 24000) + b'"}'
        to_thread_called = {"count": 0}
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, *args, **kwargs):
            if func is gzip.compress:
                to_thread_called["count"] += 1
            return await real_to_thread(func, *args, **kwargs)

        async def big_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": payload})

        wrapped = TextResponseCompressionMiddleware(big_app)
        with patch("ra_triage_dashboard.app.response_compression.asyncio.to_thread", side_effect=spy_to_thread):
            status, headers, body, _ = _run_asgi(
                wrapped,
                method="GET",
                path="/api/cases",
                headers=[(b"accept-encoding", b"gzip")],
            )
        self.assertEqual(status, 200)
        self.assertEqual(to_thread_called["count"], 1)
        self.assertEqual(headers[b"content-encoding"], b"gzip")
        self.assertEqual(gzip.decompress(body), payload)


if __name__ == "__main__":
    unittest.main()
