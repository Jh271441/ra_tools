"""Tests for state persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_release_pipeline.state_store import StateStore


class StateStoreTest(unittest.TestCase):
    def test_create_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = StateStore(Path(tmp_dir))
            record = store.create("/tmp/exp", "demo")
            loaded = store.load(record["release_id"])
            self.assertEqual(loaded["experiment_path"], "/tmp/exp")
            self.assertEqual(loaded["description"], "demo")


if __name__ == "__main__":
    unittest.main()
