"""Tests for handoff generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_release_pipeline.config import default_config
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService


class VoyagerHandoffTest(unittest.TestCase):
    def test_generate_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            config = default_config()
            service = VoyagerHandoffService(config.voyager)
            result = service.generate(
                run_dir=run_dir,
                ifx_mapping={
                    "onnx": {
                        "name": "vectorized_scenario_remote_assist_model.onnx",
                        "version": 64,
                    },
                    "fp32_x86": {"name": "model_x86.ifxmodel", "version": 1},
                    "fp16_6000": {"name": "model_6000.ifxmodel", "version": 2},
                    "fp16_3060": {"name": "model_3060.ifxmodel", "version": 3},
                    "fp16_gen4": {"name": "model_gen4.ifxmodel", "version": 4},
                    "fp16_thor": {"name": "model_thor.ifxmodel", "version": 5},
                },
                description="demo",
                experiment_name="exp",
                selected_epoch=10,
            )
            manifest = Path(result["manifest_snippet"]).read_text(encoding="utf-8")
            self.assertIn("model_gen4.ifxmodel", manifest)
            commands = Path(result["commands_file"]).read_text(encoding="utf-8")
            self.assertIn("dcl diff -n -u 5716859", commands)


if __name__ == "__main__":
    unittest.main()
