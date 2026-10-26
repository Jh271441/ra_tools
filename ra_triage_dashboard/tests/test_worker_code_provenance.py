from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

from ra_triage_dashboard.app.batch_prediction_worker import repo_commit


class WorkerCodeProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_sha = "a" * 40
        self.files = {}
        for name in ("vlm/__init__.py", "utils/config.py", "core/batch_engine.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# verified exported code\n")
            self.files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = self.root / "migration-code-receipt.json"
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(
            json.dumps({"source_sha": self.source_sha, "files_sha256": self.files})
        )
        return hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def pinned(self, pin=None):
        return patch.dict(
            os.environ,
            {
                "RA_CODE_MANIFEST_SHA256": pin
                or hashlib.sha256(self.manifest.read_bytes()).hexdigest()
            },
        )

    def test_verified_export_reports_original_source_version(self):
        with self.pinned():
            self.assertEqual(repo_commit(self.root), self.source_sha)

    def test_malformed_manifest_is_a_validation_error(self):
        for content in (b"[]", b"null", b"{", b"\xff"):
            with self.subTest(content=content):
                self.manifest.write_bytes(content)
                with self.pinned(), self.assertRaisesRegex(ValueError, "格式非法"):
                    repo_commit(self.root)

    def test_manifest_size_limit(self):
        self.manifest.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        with self.pinned(), self.assertRaisesRegex(ValueError, "格式非法"):
            repo_commit(self.root)

    def test_modified_code_is_rejected(self):
        with self.pinned():
            (self.root / "utils/config.py").write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "代码文件与部署清单不一致"):
                repo_commit(self.root)

    def test_extra_python_module_is_rejected(self):
        (self.root / "utils/injected.py").write_text("# extra\n")
        with self.pinned(), self.assertRaisesRegex(ValueError, "清单外"):
            repo_commit(self.root)

    def test_rewritten_manifest_cannot_relabel_version(self):
        pin = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.source_sha = "b" * 40
        self.write_manifest()
        with self.pinned(pin), self.assertRaisesRegex(
            ValueError, "固定 SHA-256 不一致"
        ):
            repo_commit(self.root)

    def test_path_escape_and_symlink_are_rejected(self):
        self.files["../outside.py"] = "a" * 64
        self.write_manifest()
        with self.pinned(), self.assertRaisesRegex(ValueError, "非法文件"):
            repo_commit(self.root)
        del self.files["../outside.py"]
        self.files["utils/alias.py"] = self.files["utils/config.py"]
        (self.root / "utils/alias.py").symlink_to(self.root / "utils/config.py")
        self.write_manifest()
        with self.pinned(), self.assertRaisesRegex(ValueError, "非法文件"):
            repo_commit(self.root)

    def test_unpinned_git_checkout_retains_existing_behavior(self):
        with patch.dict(os.environ, {"RA_CODE_MANIFEST_SHA256": ""}), patch(
            "ra_triage_dashboard.app.batch_prediction_worker.subprocess.run",
            return_value=CompletedProcess([], 0, stdout=self.source_sha + "\n"),
        ):
            self.assertEqual(repo_commit(self.root), self.source_sha)


if __name__ == "__main__":
    unittest.main()
