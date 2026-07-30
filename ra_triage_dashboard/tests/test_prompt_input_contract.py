from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ra_triage_dashboard.app.batch_prediction_worker import (
    apply_prediction_configuration,
)
from ra_triage_dashboard.app.prompt_catalog import (
    PromptCatalog,
    PromptCatalogError,
    normalise_input_config,
)


VALID_TEMPLATE = """
请基于 {{visual_timeline}} 完成 RA 三分类。
label 只能是：误触发、正确触发、无需协助。
请输出 JSON，并说明关键时序证据。
""".strip()


class PromptInputContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        versions = self.root / "vlm" / "prompts" / "versions"
        for prompt_id, template in (
            ("stuck_triage_auto_opt_api", VALID_TEMPLATE),
            (
                "unknown_variable",
                VALID_TEMPLATE + "\n{{unsupported_runtime_value}}",
            ),
            ("two_class", "仅输出误触发或正确触发。" * 4),
            (
                "four_class",
                VALID_TEMPLATE + "\n证据不足时 label 可以输出无法判断。",
            ),
        ):
            directory = versions / prompt_id
            directory.mkdir(parents=True)
            (directory / "template.md").write_text(template, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_catalog_only_exposes_renderable_three_class_templates(self) -> None:
        catalog = PromptCatalog(self.root).list_prompts()
        self.assertEqual(
            [item["id"] for item in catalog["items"]],
            ["stuck_triage_auto_opt_api"],
        )
        self.assertEqual(
            catalog["default_prompt_id"],
            "stuck_triage_auto_opt_api",
        )

    def test_custom_prompt_and_input_are_normalised_and_rechecked(self) -> None:
        catalog = PromptCatalog(self.root)
        custom = VALID_TEMPLATE + "\n优先核验 routing 方向。"
        prompt = catalog.resolve("stuck_triage_auto_opt_api", custom)
        input_config = normalise_input_config(
            {
                "profile_id": "camera_ra_options",
                "frame_offsets_ms": [-3000, -1000, 0, 1000, 3000],
                "use_ra_event": True,
                "use_ra_options": True,
            }
        )
        experiment = SimpleNamespace()
        metadata = apply_prediction_configuration(
            experiment,
            {
                "prompt_version": prompt["prompt_version"],
                "prompt_template": prompt["prompt_template"],
                "prompt_template_sha256": prompt["prompt_template_sha256"],
                "prompt_mode": prompt["prompt_mode"],
                "input_profile": input_config["profile_id"],
                "input_config": input_config,
            },
        )
        self.assertEqual(metadata["prompt_mode"], "custom")
        self.assertEqual(metadata["input_profile"], "custom")
        self.assertEqual(experiment.frame_offsets_ms, [-3000, -1000, 0, 1000, 3000])
        self.assertTrue(experiment.use_ra_options)
        self.assertFalse(experiment.use_ares_capture)
        self.assertFalse(experiment.use_bev_animation)

    def test_hash_mismatch_and_unknown_variables_fail_closed(self) -> None:
        catalog = PromptCatalog(self.root)
        prompt = catalog.resolve("stuck_triage_auto_opt_api", "")
        with self.assertRaises(PromptCatalogError):
            catalog.resolve(
                "stuck_triage_auto_opt_api",
                VALID_TEMPLATE + "\n{{unknown_value}}",
            )
        with self.assertRaisesRegex(PromptCatalogError, "三分类以外"):
            catalog.resolve(
                "stuck_triage_auto_opt_api",
                VALID_TEMPLATE + "\n证据不足时输出无法判断。",
            )
        input_config = normalise_input_config(None)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            apply_prediction_configuration(
                SimpleNamespace(),
                {
                    "prompt_version": prompt["prompt_version"],
                    "prompt_template": prompt["prompt_template"],
                    "prompt_template_sha256": hashlib.sha256(b"other").hexdigest(),
                    "prompt_mode": "catalog",
                    "input_profile": input_config["profile_id"],
                    "input_config": input_config,
                },
            )

    def test_input_boundaries_and_ares_cannot_be_enabled(self) -> None:
        with self.assertRaises(PromptCatalogError):
            normalise_input_config(
                {
                    "frame_offsets_ms": [-1000, 1000],
                    "use_ra_event": True,
                    "use_ra_options": False,
                }
            )
        with self.assertRaises(PromptCatalogError):
            normalise_input_config(
                {
                    "frame_offsets_ms": [-31_000, 0],
                    "use_ra_event": True,
                    "use_ra_options": False,
                }
            )
        prompt = PromptCatalog(self.root).resolve("", "")
        unsafe_input = normalise_input_config(None) | {"use_ares_capture": True}
        with self.assertRaisesRegex(ValueError, "Ares/BEV"):
            apply_prediction_configuration(
                SimpleNamespace(),
                {
                    "prompt_version": prompt["prompt_version"],
                    "prompt_template": prompt["prompt_template"],
                    "prompt_template_sha256": prompt["prompt_template_sha256"],
                    "prompt_mode": "catalog",
                    "input_profile": unsafe_input["profile_id"],
                    "input_config": unsafe_input,
                },
            )
