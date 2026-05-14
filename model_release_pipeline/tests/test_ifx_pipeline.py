"""Tests for IFX pipeline staging and dry-run output."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_release_pipeline.config import IfxConfig
from model_release_pipeline.services.ifx_pipeline import IfxPipeline


class IfxPipelineTest(unittest.TestCase):
    def test_dry_run_reports_substeps_and_upload_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            onnx = Path(tmp_dir) / "model.onnx"
            onnx.write_text("onnx", encoding="utf-8")
            progress_events = []

            result = IfxPipeline(IfxConfig()).run(
                local_onnx_file=onnx,
                description="exp, epoch=007, demo.",
                dry_run=True,
                progress=lambda title, step, detail=None: progress_events.append(
                    (title, step, detail)
                ),
            )

        self.assertEqual([event[1] for event in progress_events], [1, 2, 3, 4, 5])
        self.assertEqual(result["upload_description"], "exp, epoch=007, demo.")
        self.assertEqual(result["truck_runner"]["selected"], "dry_run")

    def test_jenkins_trigger_uses_configured_post_method(self) -> None:
        class FakeResponse:
            status_code = 201
            headers = {"Location": "http://jenkins/queue/item/1/"}
            text = ""

            def __init__(self, payload=None) -> None:
                self._payload = payload or {}

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return self._payload

        class FakeSession:
            def __init__(self) -> None:
                self.post_headers = None

            def get(self, url, timeout=30):
                return FakeResponse(
                    {
                        "crumbRequestField": "Jenkins-Crumb",
                        "crumb": "abc123",
                    }
                )

            def post(self, url, data=None, headers=None, timeout=30):
                self.post_headers = headers
                return FakeResponse()

        session = FakeSession()

        with patch(
            "model_release_pipeline.services.ifx_pipeline.requests.Session",
            return_value=session,
        ):
            config = IfxConfig(jenkins_http_method="POST")
            pipeline = IfxPipeline(config)
            result = pipeline._trigger_jenkins({"label": "demo"})

        self.assertEqual(result["method"], "POST")
        self.assertEqual(result["status_code"], 201)
        self.assertEqual(result["queue_url"], "http://jenkins/queue/item/1/")
        self.assertEqual(result["crumb"]["field"], "Jenkins-Crumb")
        self.assertEqual(session.post_headers, {"Jenkins-Crumb": "abc123"})

    def test_convert_dry_run_matches_v64_build_defaults_except_onnx_version(self) -> None:
        pipeline = IfxPipeline(IfxConfig())

        result = pipeline.convert(
            upload_result={
                "onnx": {
                    "module": "planner.model-files",
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 66,
                },
                "precision_test_arg": (
                    "ifx-precision-test ifx_fp32_after_scaling_pos1e1_5.zip -v 1"
                ),
            },
            dry_run=True,
        )

        params = result["jenkins"]["params"]
        self.assertEqual(
            params["truck_py_arguments_of_onnx"],
            "planner.model-files vectorized_scenario_remote_assist_model.onnx -v 66",
        )
        self.assertEqual(params["max_batch"], 0)
        self.assertEqual(params["x86_convert"], "openvino")
        self.assertEqual(params["precision_convert"], "FP16")
        self.assertNotIn("label", params)

    def test_parse_console_reports_failed_thor_upload(self) -> None:
        console = """
vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel upload done
vectorized_scenario_remote_assist_model_bs0_fp16_6000_trt109.ifxmodel upload done
vectorized_scenario_remote_assist_model_bs0_fp16_3060_trt109.ifxmodel upload done
vectorized_scenario_remote_assist_model_bs0_fp16_gen4_trt109.ifxmodel upload done
vectorized_scenario_remote_assist_model_bs0_fp16_thor_trt1013.ifxmodel upload failed
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel 72 21.41 2026-05-08T06:47:22Z 4de42
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp16_6000_trt109.ifxmodel 37 13.11 2026-05-08T06:47:24Z 95d0
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp16_3060_trt109.ifxmodel 45 14.85 2026-05-08T06:47:24Z 6828
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp16_gen4_trt109.ifxmodel 45 14.45 2026-05-08T06:47:24Z 4dca
"""
        pipeline = IfxPipeline(IfxConfig())

        result = pipeline._parse_ifx_mapping_from_console(
            console,
            "planner.model-files vectorized_scenario_remote_assist_model.onnx -v 64",
        )

        self.assertEqual(result["mapping"]["fp32_x86"]["version"], 72)
        self.assertEqual(result["mapping"]["fp16_6000"]["version"], 37)
        self.assertNotIn("fp16_thor", result["mapping"])
        self.assertEqual(
            result["failed_uploads"],
            ["vectorized_scenario_remote_assist_model_bs0_fp16_thor_trt1013.ifxmodel"],
        )

    def test_wait_for_jenkins_build_reports_progress(self) -> None:
        class FakeResponse:
            status_code = 200
            headers = {}
            text = "Finished: SUCCESS"

            def __init__(self, payload=None, text=None) -> None:
                self._payload = payload or {}
                if text is not None:
                    self.text = text

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return self._payload

        class FakeSession:
            def __init__(self) -> None:
                self.queue_payloads = [
                    {"why": "Waiting for next available executor"},
                    {"executable": {"url": "http://jenkins/job/demo/1/"}},
                ]
                self.build_payloads = [
                    {"building": True, "number": 1, "estimatedDuration": 90000},
                    {"building": False, "number": 1, "result": "SUCCESS"},
                ]

            def get(self, url, timeout=30):
                if url.endswith("/queue/item/1/api/json"):
                    return FakeResponse(self.queue_payloads.pop(0))
                if url.endswith("/job/demo/1/api/json"):
                    return FakeResponse(self.build_payloads.pop(0))
                if url.endswith("/job/demo/1/consoleText"):
                    return FakeResponse(text="Finished: SUCCESS")
                raise AssertionError(f"unexpected url: {url}")

        session = FakeSession()
        progress_events = []

        with patch(
            "model_release_pipeline.services.ifx_pipeline.requests.Session",
            return_value=session,
        ):
            pipeline = IfxPipeline(
                IfxConfig(
                    jenkins_base_url="http://jenkins",
                    poll_interval_sec=0,
                    timeout_sec=2,
                )
            )
            result = pipeline._wait_for_jenkins_build(
                "http://jenkins/queue/item/1/",
                progress=lambda title, step, detail=None: progress_events.append(
                    (title, step, detail)
                ),
                progress_step=2,
            )

        details = [event[2] or "" for event in progress_events]
        self.assertEqual(result["result"], "SUCCESS")
        self.assertTrue(any("waiting Jenkins queue" in detail for detail in details))
        self.assertTrue(any("Jenkins build assigned" in detail for detail in details))
        self.assertTrue(any("Jenkins build finished" in detail for detail in details))
        self.assertTrue(any("consoleText" in detail for detail in details))

    def test_poll_existing_uses_persisted_build_url(self) -> None:
        console = """
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel 72 21.41 2026-05-08T06:47:22Z 4de42
1 planner.model-files vectorized_scenario_remote_assist_model_bs0_fp16_6000_trt109.ifxmodel 37 13.11 2026-05-08T06:47:24Z 95d0
"""

        class FakeResponse:
            status_code = 200
            headers = {}

            def __init__(self, payload=None, text="") -> None:
                self._payload = payload or {}
                self.text = text

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return self._payload

        class FakeSession:
            def get(self, url, timeout=30):
                if url.endswith("/job/demo/1/api/json"):
                    return FakeResponse(
                        {"building": False, "number": 1, "result": "SUCCESS"}
                    )
                if url.endswith("/job/demo/1/consoleText"):
                    return FakeResponse(text=console)
                raise AssertionError(f"unexpected url: {url}")

        with patch(
            "model_release_pipeline.services.ifx_pipeline.requests.Session",
            return_value=FakeSession(),
        ):
            pipeline = IfxPipeline(
                IfxConfig(
                    jenkins_base_url="http://jenkins",
                    expected_platforms=["fp32_x86", "fp16_6000"],
                    timeout_sec=2,
                    poll_interval_sec=0,
                )
            )
            result = pipeline.poll_existing(
                {
                    "onnx": {
                        "module": "planner.model-files",
                        "name": "vectorized_scenario_remote_assist_model.onnx",
                        "version": 64,
                    },
                    "jenkins": {"build_url": "http://jenkins/job/demo/1/"},
                }
            )

        self.assertEqual(result["jenkins"]["build_number"], 1)
        self.assertEqual(result["ifx_mapping"]["fp32_x86"]["version"], 72)
        self.assertEqual(result["ifx_mapping"]["fp16_6000"]["version"], 37)
        self.assertEqual(result["ifx_mapping"]["onnx"]["version"], 64)


if __name__ == "__main__":
    unittest.main()
