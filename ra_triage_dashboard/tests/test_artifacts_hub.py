"""Contracts and integration tests for the unified Artifact Hub and dynamic store."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ra_triage_dashboard.app.artifact_store import (
    ArtifactStore,
    normalize_artifact_slug,
    render_artifact_frame_html,
)
from ra_triage_dashboard.app.web_paths import BASE_PATH_TOKEN, render_index_html


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = DASHBOARD_ROOT / "static"
ARTIFACTS_STATIC_DIR = STATIC_DIR / "artifacts"
VENDOR_TAILWIND = STATIC_DIR / "vendor" / "tailwindcss" / "tailwindcss.min.js"


SAMPLE_AGY_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>LoRA Mounting Diagram</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] p-0 m-0">
  <div class="p-2 bg-[var(--card)] border border-[var(--card-border)]">Hello LoRA</div>
</body>
</html>
"""


class ArtifactStoreContractTest(unittest.TestCase):
    def test_static_hub_files_and_vendor_tailwind_avoid_external_cdns(self) -> None:
        self.assertTrue(VENDOR_TAILWIND.is_file())
        self.assertGreater(VENDOR_TAILWIND.stat().st_size, 100_000)

        for name in ("portal.html", "viewer.html"):
            path = ARTIFACTS_STATIC_DIR / name
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIn(BASE_PATH_TOKEN, text)
            self.assertNotIn("<select", text.lower(), f"{name} must use .ui-select, not raw <select>")
            for forbidden in ("gstatic.com", "googleapis.com", "unpkg.com", "jsdelivr.net"):
                self.assertNotIn(forbidden, text)
            rendered = render_index_html(text, "/manual/")
            self.assertIn('<meta name="ra-triage-base" content="/manual" />', rendered)
            self.assertNotIn(BASE_PATH_TOKEN, rendered)

        portal_html = (ARTIFACTS_STATIC_DIR / "portal.html").read_text(encoding="utf-8")
        self.assertIn("case-pagination", portal_html)
        self.assertIn("case-pagination-main", portal_html)
        self.assertIn("case-page-size", portal_html)
        self.assertIn("page-jump-control", portal_html)

        viewer_html = (ARTIFACTS_STATIC_DIR / "viewer.html").read_text(encoding="utf-8")
        hub_js = (ARTIFACTS_STATIC_DIR / "artifacts-hub.js").read_text(encoding="utf-8")
        self.assertIn('allow-scripts allow-downloads allow-popups', viewer_html)
        self.assertIn('allow-scripts allow-downloads allow-popups', hub_js)
        self.assertNotIn("allow-same-origin", viewer_html)
        self.assertNotIn("allow-same-origin", hub_js)

        # Must stay absent from the Manual Workbench shell navigation.
        workbench_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("/artifacts", workbench_index)

    def test_slug_validation_and_frame_renderer(self) -> None:
        self.assertEqual(normalize_artifact_slug("LoRA_Mounting 01"), "lora-mounting-01")
        for bad in ("", "a", "../etc/passwd", "api", "static", "frame", "health"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    normalize_artifact_slug(bad)

        dark_frame = render_artifact_frame_html(SAMPLE_AGY_HTML, base_path=None, initial_theme="dark")
        self.assertNotIn("gstatic.com", dark_frame)
        self.assertIn('../../static/vendor/tailwindcss/tailwindcss.min.js', dark_frame)
        self.assertIn('id="ra-agy-theme-tokens"', dark_frame)
        self.assertIn('id="ra-agy-bridge"', dark_frame)
        self.assertIn('ra-artifact-nav', dark_frame)
        self.assertIn('data-color-theme="dark"', dark_frame)

        light_frame = render_artifact_frame_html(SAMPLE_AGY_HTML, base_path="/manual", initial_theme="light")
        self.assertIn('/manual/static/vendor/tailwindcss/tailwindcss.min.js', light_frame)
        self.assertIn('class="light"', light_frame)
        self.assertIn('data-color-theme="light"', light_frame)

        slot_frame = render_artifact_frame_html(SAMPLE_AGY_HTML, inline_tailwind_slot=True, initial_theme="dark")
        self.assertIn("<!--RA_TAILWIND_INLINE_SLOT-->", slot_frame)
        self.assertIn("default-src 'none'", slot_frame)
        self.assertNotIn("gstatic.com", slot_frame)
        self.assertNotIn("tailwindcss.min.js", slot_frame)

    def test_store_crud_manual_edit_preservation_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp) / "artifacts", static_dir=STATIC_DIR)

            # Built-in original330 is present even before any dynamic writes.
            initial = store.list_artifacts()
            self.assertEqual(initial["total"], 1)
            self.assertEqual(initial["items"][0]["slug"], "architecture-original-330")
            self.assertTrue(initial["items"][0]["builtin"])

            # Cannot overwrite or delete built-in item.
            with self.assertRaises(ValueError):
                store.upsert_artifact(slug="architecture-original-330", html_content=SAMPLE_AGY_HTML)
            with self.assertRaises(ValueError):
                store.delete_artifact("architecture-original-330")

            # Upsert dynamic artifact and verify idempotency.
            res1 = store.upsert_artifact(
                slug="lora-mounting-inside-layers",
                html_content=SAMPLE_AGY_HTML,
                title="LoRA 层内挂载原理",
                title_en="LoRA Layer Mounting",
                summary="交互式 4-tab 图解",
                group="vlm-architecture",
                tags=["LoRA", "Qwen3.8", "lora"],
                conversation_id="514e2357-d2e2-499b-a7cb-a1cbeb8be7d8",
                source_filename="lora_mounting_inside_layers.html",
            )
            self.assertTrue(res1["created"])
            self.assertFalse(res1["unchanged"])
            self.assertEqual(res1["item"]["revision"], 1)
            self.assertEqual(res1["item"]["tags"], ["LoRA", "Qwen3.8"])

            res_same = store.upsert_artifact(
                slug="lora-mounting-inside-layers",
                html_content=SAMPLE_AGY_HTML,
                title="LoRA 层内挂载原理",
                title_en="LoRA Layer Mounting",
                summary="交互式 4-tab 图解",
                group="vlm-architecture",
                tags=["LoRA", "Qwen3.8"],
                conversation_id="514e2357-d2e2-499b-a7cb-a1cbeb8be7d8",
                source_filename="lora_mounting_inside_layers.html",
            )
            self.assertFalse(res_same["created"])
            self.assertTrue(res_same["unchanged"])
            self.assertEqual(res_same["item"]["revision"], 1)

            # Manual edit in UI must survive subsequent hook re-syncs.
            edited = store.update_artifact_metadata(
                "lora-mounting-inside-layers",
                patch={"title": "人工精修标题", "archived": True, "tags": ["PinnedTag"]},
                updated_by="jasperchen",
            )
            self.assertIsNotNone(edited)
            self.assertEqual(edited["title"], "人工精修标题")
            self.assertTrue(edited["archived"])

            res_hook_update = store.upsert_artifact(
                slug="lora-mounting-inside-layers",
                html_content=SAMPLE_AGY_HTML.replace("Hello LoRA", "Hello LoRA v2"),
                title="自动提取标题",
                archived=False,
                tags=["AutoTag"],
                preserve_manual_edits=True,
            )
            self.assertEqual(res_hook_update["item"]["revision"], 2)
            self.assertEqual(res_hook_update["item"]["title"], "人工精修标题")
            self.assertTrue(res_hook_update["item"]["archived"])
            self.assertEqual(res_hook_update["item"]["tags"], ["PinnedTag"])

            # Filtering by status/group/search and pagination.
            active_only = store.list_artifacts(status="active")
            self.assertEqual([x["slug"] for x in active_only["items"]], ["architecture-original-330"])
            archived_only = store.list_artifacts(status="archived")
            self.assertEqual([x["slug"] for x in archived_only["items"]], ["lora-mounting-inside-layers"])

            # Add more items and verify pagination bounds.
            for idx in range(5):
                store.upsert_artifact(
                    slug=f"demo-chart-{idx}",
                    html_content=SAMPLE_AGY_HTML,
                    title=f"Chart {idx}",
                    group="workbench-ui",
                )
            page1 = store.list_artifacts(status="all", page=1, page_size=3)
            self.assertEqual(page1["total"], 7)
            self.assertEqual(page1["total_pages"], 3)
            self.assertEqual(len(page1["items"]), 3)
            page_clamped = store.list_artifacts(status="all", page=99, page_size=3)
            self.assertEqual(page_clamped["page"], 3)
            self.assertEqual(len(page_clamped["items"]), 1)

            # Neighbor navigation follows exact active filter/sort order.
            nav_group = store.get_artifact_neighbors(
                "demo-chart-2",
                group="workbench-ui",
                sort="title_asc",
            )
            self.assertTrue(nav_group["scope_matched"])
            self.assertEqual(nav_group["index"], 3)
            self.assertEqual(nav_group["total"], 5)
            self.assertEqual(nav_group["prev"]["slug"], "demo-chart-1")
            self.assertEqual(nav_group["next"]["slug"], "demo-chart-3")

            nav_first = store.get_artifact_neighbors(
                "demo-chart-0",
                group="workbench-ui",
                sort="title_asc",
            )
            self.assertIsNone(nav_first["prev"])
            self.assertEqual(nav_first["next"]["slug"], "demo-chart-1")

            # Archived item outside active filter falls back to full catalog cleanly.
            nav_fallback = store.get_artifact_neighbors(
                "lora-mounting-inside-layers",
                status="active",
                sort="title_asc",
            )
            self.assertFalse(nav_fallback["scope_matched"])
            self.assertEqual(nav_fallback["total"], 7)
            self.assertGreaterEqual(nav_fallback["index"], 1)

            # Delete dynamic artifact cleanly.
            self.assertTrue(store.delete_artifact("demo-chart-0"))
            self.assertIsNone(store.get_artifact("demo-chart-0"))

    def test_publish_script_batch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "items": [
                    {
                        "slug": "batch-demo-1",
                        "html_content": SAMPLE_AGY_HTML,
                        "title": "Batch Demo 1",
                        "group": "vlm-architecture",
                    }
                ]
            }
            proc = subprocess.run(
                [
                    sys.executable,
                    str(DASHBOARD_ROOT / "scripts" / "publish_artifact.py"),
                    "--data-dir",
                    tmp,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(out["published"][0]["slug"], "batch-demo-1")
            self.assertTrue(out["published"][0]["created"])

    @unittest.skipUnless(
        sys.version_info >= (3, 10)
        and importlib.util.find_spec("starlette") is not None
        and importlib.util.find_spec("fastapi") is not None,
        "Python 3.10+ with starlette/fastapi runtime required",
    )
    def test_asgi_routes_and_api_crud(self) -> None:
        from fastapi import FastAPI

        from ra_triage_dashboard.app.routers import artifacts as artifacts_router

        async def asgi_req(
            app_obj,
            method: str,
            path: str,
            *,
            query: str = "",
            body: bytes = b"",
            headers: list[tuple[bytes, bytes]] | None = None,
        ) -> tuple[int, dict[bytes, bytes], bytes]:
            messages: list[dict] = []
            sent = False

            async def receive() -> dict:
                nonlocal sent
                if sent:
                    return {"type": "http.request", "body": b"", "more_body": False}
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message: dict) -> None:
                messages.append(message)

            req_headers = list(headers or [])
            req_headers.append((b"host", b"127.0.0.1:8785"))
            if body:
                req_headers.append((b"content-length", str(len(body)).encode("ascii")))

            await app_obj(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "method": method,
                    "path": path,
                    "raw_path": path.encode("utf-8"),
                    "root_path": "",
                    "query_string": query.encode("utf-8"),
                    "scheme": "http",
                    "http_version": "1.1",
                    "headers": req_headers,
                },
                receive,
                send,
            )
            status = messages[0]["status"]
            resp_headers = dict(messages[0]["headers"])
            resp_body = b"".join(m.get("body", b"") for m in messages)
            return status, resp_headers, resp_body

        with tempfile.TemporaryDirectory() as tmp:
            temp_store = ArtifactStore(Path(tmp) / "artifacts", static_dir=STATIC_DIR)
            route_app = FastAPI()
            route_app.include_router(artifacts_router.router)

            with (
                mock.patch.object(artifacts_router, "artifact_store", temp_store),
                mock.patch.object(
                    artifacts_router,
                    "_artifact_can_manage",
                    return_value=(True, "tester"),
                ),
                mock.patch.object(
                    artifacts_router,
                    "_artifact_require_writer",
                    return_value="tester",
                ),
            ):
                # Portal HTML with embedded bootstrap
                st, hdrs, body = asyncio.run(asgi_req(route_app, "GET", "/artifacts"))
                self.assertEqual(st, 200)
                self.assertEqual(hdrs.get(b"cache-control"), b"no-store, max-age=0")
                self.assertIn(b'data-page="portal"', body)
                self.assertIn(b'id="raPortalBootstrap"', body)

                # Async access probe endpoint
                st, _, body = asyncio.run(asgi_req(route_app, "GET", "/api/artifacts-access"))
                self.assertEqual(st, 200)
                self.assertTrue(json.loads(body)["can_manage"])

                # Redirect for built-in slug
                st, hdrs, _ = asyncio.run(
                    asgi_req(route_app, "GET", "/artifacts/architecture-original-330")
                )
                self.assertEqual(st, 302)
                self.assertEqual(hdrs.get(b"location"), b"../architecture-original-330")

                # 404 for unknown slug
                st, _, _ = asyncio.run(asgi_req(route_app, "GET", "/artifacts/missing-slug"))
                self.assertEqual(st, 404)

                # Create via POST API
                post_payload = json.dumps(
                    {
                        "slug": "test-diagram",
                        "html_content": SAMPLE_AGY_HTML,
                        "title": "测试图表",
                        "group": "vlm-architecture",
                    }
                ).encode("utf-8")
                st, _, body = asyncio.run(
                    asgi_req(
                        route_app,
                        "POST",
                        "/api/artifacts",
                        body=post_payload,
                        headers=[(b"content-type", b"application/json")],
                    )
                )
                self.assertEqual(st, 201)
                created = json.loads(body)
                self.assertEqual(created["item"]["slug"], "test-diagram")

                # Viewer page (with embedded bootstrap + frame_html) + sandboxed frame + immutable ETag/304
                st, _, body = asyncio.run(asgi_req(route_app, "GET", "/artifacts/test-diagram"))
                self.assertEqual(st, 200)
                self.assertIn("测试图表".encode("utf-8"), body)
                self.assertIn(b'id="raArtifactBootstrap"', body)
                body_str = body.decode("utf-8")
                m = body_str.split('<script id="raArtifactBootstrap" type="application/json">', 1)[1].split("</script>", 1)[0]
                parsed_boot = json.loads(m)
                self.assertEqual(parsed_boot["item"]["slug"], "test-diagram")
                self.assertIn("<!--RA_TAILWIND_INLINE_SLOT-->", parsed_boot["frame_html"])

                sha12 = created["item"]["content_sha256"][:12]
                st, hdrs, body = asyncio.run(
                    asgi_req(
                        route_app,
                        "GET",
                        "/artifacts/test-diagram/frame",
                        query=f"theme=light&v={sha12}-r3",
                    )
                )
                self.assertEqual(st, 200)
                self.assertIn(b"immutable", hdrs.get(b"cache-control", b""))
                self.assertIn(b"etag", hdrs)
                self.assertIn(b"connect-src 'none'", hdrs.get(b"content-security-policy", b""))
                self.assertIn(b"frame-ancestors 'self'", hdrs.get(b"content-security-policy", b""))
                self.assertNotIn(b"gstatic.com", body)
                self.assertIn(b"../../static/vendor/tailwindcss/tailwindcss.min.js", body)

                st304, _, _ = asyncio.run(
                    asgi_req(
                        route_app,
                        "GET",
                        "/artifacts/test-diagram/frame",
                        query=f"theme=light&v={sha12}-r3",
                        headers=[(b"if-none-match", hdrs[b"etag"])],
                    )
                )
                self.assertEqual(st304, 304)

                # List API + single GET with navigation and include_frame=1
                st, _, body = asyncio.run(asgi_req(route_app, "GET", "/api/artifacts"))
                self.assertEqual(st, 200)
                listing = json.loads(body)
                self.assertEqual(listing["total"], 2)

                st, _, body = asyncio.run(
                    asgi_req(
                        route_app,
                        "GET",
                        "/api/artifacts/test-diagram",
                        query="group=vlm-architecture&include_frame=1",
                    )
                )
                self.assertEqual(st, 200)
                detail = json.loads(body)
                self.assertEqual(detail["navigation"]["total"], 2)
                self.assertEqual(detail["navigation"]["index"], 2)
                self.assertEqual(detail["navigation"]["prev"]["slug"], "architecture-original-330")
                self.assertIsNone(detail["navigation"]["next"])
                self.assertIn("<!--RA_TAILWIND_INLINE_SLOT-->", detail["frame_html"])

                # PATCH metadata
                st, _, body = asyncio.run(
                    asgi_req(
                        route_app,
                        "PATCH",
                        "/api/artifacts/test-diagram",
                        body=json.dumps({"pinned": True, "title": "更新标题"}).encode("utf-8"),
                        headers=[(b"content-type", b"application/json")],
                    )
                )
                self.assertEqual(st, 200)
                self.assertTrue(json.loads(body)["item"]["pinned"])

                # DELETE dynamic item
                st, _, body = asyncio.run(
                    asgi_req(route_app, "DELETE", "/api/artifacts/test-diagram")
                )
                self.assertEqual(st, 200)
                self.assertTrue(json.loads(body)["deleted"])


if __name__ == "__main__":
    unittest.main()
