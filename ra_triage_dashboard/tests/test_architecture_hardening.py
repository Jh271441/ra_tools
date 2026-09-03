from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.assets import AssetIndex
from ra_triage_dashboard.app.observability import BoundedObservationSet
from ra_triage_dashboard.app.upload_limits import (
    UploadLimitExceeded,
    read_upload_limited,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


class _Upload:
    def __init__(self, content: bytes):
        self.content = content
        self.offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            size = len(self.content) - self.offset
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


def _is_to_thread_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "to_thread"
    )


class ArchitectureHardeningTest(unittest.IsolatedAsyncioTestCase):
    def test_application_modules_use_explicit_import_boundaries(self) -> None:
        paths = [
            APP_ROOT / "main.py",
            APP_ROOT / "runtime.py",
            APP_ROOT / "http_support.py",
            *(APP_ROOT / "routers").rglob("*.py"),
            *(APP_ROOT / "support").glob("*.py"),
        ]
        wildcard_imports: list[str] = []
        dynamic_exports: list[str] = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "*" for alias in node.names
                ):
                    wildcard_imports.append(f"{path.name}:{node.lineno}")
                if (
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "__all__"
                        for target in node.targets
                    )
                ):
                    dynamic_exports.append(f"{path.name}:{node.lineno}")
        self.assertEqual(wildcard_imports, [], "\n".join(wildcard_imports))
        self.assertEqual(dynamic_exports, [], "\n".join(dynamic_exports))

    def test_import_parser_does_not_initialise_runtime_singletons(self) -> None:
        tree = ast.parse(
            (APP_ROOT / "import_parsing.py").read_text(encoding="utf-8")
        )
        forbidden = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module in {"runtime", "http_support"}
        }
        self.assertEqual(forbidden, set())

    async def test_upload_reader_is_bounded_and_hashes_accepted_content(self) -> None:
        content = b"0123456789"
        upload = _Upload(content)
        received, digest = await read_upload_limited(
            upload,
            max_bytes=len(content),
            chunk_bytes=4,
        )
        self.assertEqual(received, content)
        self.assertEqual(digest, hashlib.sha256(content).hexdigest())
        self.assertTrue(all(0 < size <= 4 for size in upload.read_sizes))

    async def test_upload_reader_rejects_after_only_one_sentinel_byte(self) -> None:
        upload = _Upload(b"x" * 100)
        with self.assertRaises(UploadLimitExceeded):
            await read_upload_limited(upload, max_bytes=8, chunk_bytes=4)
        self.assertEqual(upload.offset, 9)
        self.assertNotIn(-1, upload.read_sizes)

    def test_identity_diagnostic_cache_has_a_strict_bound(self) -> None:
        observations = BoundedObservationSet[str](max_entries=3)
        self.assertTrue(observations.add_if_new("a"))
        self.assertFalse(observations.add_if_new("a"))
        for value in ("b", "c", "d"):
            observations.add_if_new(value)
        self.assertEqual(len(observations), 3)
        self.assertTrue(observations.add_if_new("a"))
        self.assertEqual(len(observations), 3)

    def test_health_asset_count_uses_cached_startup_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.jsonl"
            manifest.write_text(
                json.dumps(
                    {
                        "issue_id": "cn00000001",
                        "meta_path": "cn00000001/meta.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            index = AssetIndex(ra_root=root, manifest_path=manifest)
            self.assertEqual(index.refresh(force=True), 1)

            # A health probe must report the last startup/refresh snapshot even
            # when network storage is temporarily unavailable. The diagnostic
            # status endpoint remains responsible for an explicit refresh.
            manifest.unlink()
            self.assertEqual(index.indexed_count(), 1)
            self.assertEqual(index.refresh(), 0)
            self.assertEqual(index.indexed_count(), 0)

    def test_async_routes_do_not_call_sync_database_on_event_loop(self) -> None:
        violations: list[str] = []
        for path in sorted((APP_ROOT / "routers").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for route in tree.body:
                if not isinstance(route, ast.AsyncFunctionDef):
                    continue
                parents: dict[ast.AST, ast.AST] = {}
                for node in ast.walk(route):
                    for child in ast.iter_child_nodes(node):
                        parents[child] = node
                for call in ast.walk(route):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "database"
                    ):
                        continue
                    current: ast.AST = call
                    offloaded = False
                    while current in parents:
                        current = parents[current]
                        if _is_to_thread_call(current):
                            offloaded = True
                            break
                        if isinstance(current, ast.AsyncFunctionDef):
                            break
                    if not offloaded:
                        violations.append(
                            f"{path.name}:{call.lineno} database.{call.func.attr}"
                        )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_async_routes_offload_helpers_with_hidden_io(self) -> None:
        hidden_io_helpers = {
            "_action_actor",
            "_admin_identity",
            "_can_manage_team_default",
            "_ensure_case_thumbnail",
            "_filesystem_availability",
            "_load_case_media",
            "_missing_evidence_catalog",
            "_public_case_items",
            "_review_tag_catalog",
        }
        violations: list[str] = []
        for path in sorted((APP_ROOT / "routers").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for route in tree.body:
                if not isinstance(route, ast.AsyncFunctionDef):
                    continue
                parents: dict[ast.AST, ast.AST] = {}
                for node in ast.walk(route):
                    for child in ast.iter_child_nodes(node):
                        parents[child] = node
                for call in ast.walk(route):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id in hidden_io_helpers
                    ):
                        continue
                    current: ast.AST = call
                    offloaded = False
                    while current in parents:
                        current = parents[current]
                        if _is_to_thread_call(current):
                            offloaded = True
                            break
                        if isinstance(current, ast.AsyncFunctionDef):
                            break
                    if not offloaded:
                        violations.append(f"{path.name}:{call.lineno} {call.func.id}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_router_split_has_one_owner_for_each_helper(self) -> None:
        owners: dict[str, list[str]] = {}
        for path in sorted((APP_ROOT / "support").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owners.setdefault(node.name, []).append(path.name)
        duplicates = {
            name: paths for name, paths in owners.items() if len(paths) > 1
        }
        self.assertEqual(duplicates, {})
        self.assertGreaterEqual(len(owners), 40)

        compatibility_tree = ast.parse(
            (APP_ROOT / "http_support.py").read_text(encoding="utf-8")
        )
        compatibility_helpers = {
            node.name
            for node in compatibility_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(compatibility_helpers, set())

        forbidden_imports: list[str] = []
        for path in [APP_ROOT / "main.py", *(APP_ROOT / "routers").rglob("*.py")]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "http_support":
                    forbidden_imports.append(f"{path.name}:{node.lineno}")
        self.assertEqual(forbidden_imports, [])

        duplicates: list[str] = []
        for path in sorted((APP_ROOT / "routers").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in owners
                ):
                    duplicates.append(f"{path.name}:{node.lineno} {node.name}")
        self.assertEqual(duplicates, [], "\n".join(duplicates))


if __name__ == "__main__":
    unittest.main()
