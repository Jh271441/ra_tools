from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.model_catalog import ModelCatalog, ModelCatalogError


class _GatewayResponse:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, rows: list[dict[str, str]]):
        self._raw = json.dumps({"data": rows}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size: int) -> bytes:
        return self._raw


class _GatewayOpener:
    def __init__(self, rows: list[dict[str, str]]):
        self._rows = rows

    def open(self, _request, timeout: int):
        if timeout != 10:
            raise AssertionError(f"unexpected timeout: {timeout}")
        return _GatewayResponse(self._rows)


def _settings():
    return SimpleNamespace(
        ra_model_catalog_url="http://ra-model.intra.xiaojukeji.com/v1/models",
        ra_model_default_id="auto",
        ra_model_catalog_ttl_seconds=300,
    )


def _profile() -> dict:
    compatible = {
        "enabled": True,
        "provider": "kylin",
        "prompt_mode": "server_default",
        "input_contract": "camera_only_ra_triage",
    }
    return {
        "schema_version": 1,
        "default_model_id": "auto",
        "aliases": {
            "auto": {
                "display_name": "Auto · baseline",
                "resolved_model_id": "Qwen3.5-9B-finetuned/base",
            }
        },
        "models": {
            "Qwen3.5-9B-finetuned/base": {
                **compatible,
                "display_name": "Qwen3.5 baseline",
            },
            "Approved/Legacy-Vision": {
                **compatible,
                "display_name": "Explicit legacy profile",
            },
        },
    }


class ModelCatalogTest(unittest.TestCase):
    def test_profile_models_are_validated_and_online_qwen3_models_are_experimental(
        self,
    ) -> None:
        rows = [
            {"id": "Qwen3.5-9B-finetuned/base"},
            {"id": "Approved/Legacy-Vision"},
            {"id": "Qwen3/Qwen3-VL-8B"},
            {"id": "vendor/qWeN3-chat"},
            {"id": "Qwen3-Embedding/Qwen3-Embedding-4B"},
            {"id": "Other/Llama-Vision"},
            # Repeated gateway rows must not produce repeated public options.
            {"id": "Qwen3/Qwen3-VL-8B"},
        ]
        catalog = ModelCatalog(_settings())

        with (
            patch(
                "ra_triage_dashboard.app.model_catalog.build_opener",
                return_value=_GatewayOpener(rows),
            ),
            patch(
                "ra_triage_dashboard.app.model_catalog.read_model_gateway_api_key",
                return_value="server-owned-secret",
            ),
            patch.object(catalog, "_load_profiles", return_value=_profile()),
        ):
            snapshot = catalog.list_models(allow_stale=False)

        by_id = {item["id"]: item for item in snapshot["models"]}
        self.assertEqual(snapshot["default_model_id"], "auto")
        self.assertEqual(
            set(by_id),
            {
                "auto",
                "Qwen3.5-9B-finetuned/base",
                "Approved/Legacy-Vision",
                "Qwen3/Qwen3-VL-8B",
                "vendor/qWeN3-chat",
            },
        )
        self.assertEqual(by_id["auto"]["validation_status"], "validated")
        self.assertEqual(
            by_id["Approved/Legacy-Vision"]["validation_status"], "validated"
        )
        for model_id in ("Qwen3/Qwen3-VL-8B", "vendor/qWeN3-chat"):
            self.assertEqual(by_id[model_id]["validation_status"], "experimental")
            self.assertEqual(by_id[model_id]["provider"], "kylin")
            self.assertEqual(
                by_id[model_id]["input_contract"], "camera_only_ra_triage"
            )
            self.assertEqual(by_id[model_id]["prompt_mode"], "server_default")

        self.assertNotIn("Qwen3-Embedding/Qwen3-Embedding-4B", by_id)
        self.assertNotIn("Other/Llama-Vision", by_id)
        self.assertEqual(snapshot["online_count"], 6)
        self.assertEqual(snapshot["available_count"], 5)
        self.assertEqual(snapshot["compatible_count"], 5)
        self.assertEqual(snapshot["validated_count"], 3)
        self.assertEqual(snapshot["experimental_count"], 2)
        self.assertEqual(snapshot["excluded_count"], 2)

        experimental = catalog.resolve("Qwen3/Qwen3-VL-8B")
        self.assertEqual(experimental["validation_status"], "experimental")
        self.assertEqual(experimental["provider"], "kylin")
        baseline = catalog.resolve("")
        self.assertEqual(baseline["requested_model_id"], "auto")
        self.assertEqual(baseline["validation_status"], "validated")

    def test_non_qwen3_and_embedding_models_remain_fail_closed(self) -> None:
        rows = [
            {"id": "Qwen3.5-9B-finetuned/base"},
            {"id": "Approved/Legacy-Vision"},
            {"id": "Qwen3-Embedding/Qwen3-Embedding-4B"},
            {"id": "Other/Llama-Vision"},
        ]
        catalog = ModelCatalog(_settings())

        with (
            patch(
                "ra_triage_dashboard.app.model_catalog.build_opener",
                return_value=_GatewayOpener(rows),
            ),
            patch(
                "ra_triage_dashboard.app.model_catalog.read_model_gateway_api_key",
                return_value="server-owned-secret",
            ),
            patch.object(catalog, "_load_profiles", return_value=_profile()),
        ):
            catalog.list_models(allow_stale=False)

        for model_id in (
            "Qwen3-Embedding/Qwen3-Embedding-4B",
            "Other/Llama-Vision",
        ):
            with self.subTest(model_id=model_id):
                with self.assertRaises(ModelCatalogError) as context:
                    catalog.resolve(model_id)
                self.assertEqual(context.exception.status_code, 400)

    def test_tokenservice_provider_keeps_qwen3_catalog_usable(self) -> None:
        rows = [
            {"id": "aliyun/Qwen3-VL-Plus"},
            {"id": "aliyun/Qwen3-Next-80B-A3B-Instruct"},
            {"id": "Qwen3-Embedding/Qwen3-Embedding-4B"},
            {"id": "Other/Llama-Vision"},
        ]
        catalog = ModelCatalog(_settings())
        with (
            patch(
                "ra_triage_dashboard.app.model_catalog.build_opener",
                return_value=_GatewayOpener(rows),
            ),
            patch(
                "ra_triage_dashboard.app.model_catalog.read_provider_api_key",
                return_value="tokenservice-secret",
            ),
        ):
            snapshot = catalog.list_models(
                provider_id="tokenservice",
                allow_stale=False,
            )
            selected = catalog.resolve(
                "aliyun/Qwen3-VL-Plus",
                provider_id="tokenservice",
            )
        self.assertEqual(snapshot["provider_id"], "tokenservice")
        self.assertEqual(snapshot["default_model_id"], "aliyun/Qwen3-VL-Plus")
        self.assertEqual(snapshot["experimental_count"], 2)
        self.assertEqual(selected["provider"], "tokenservice")
        self.assertEqual(selected["validation_status"], "experimental")


if __name__ == "__main__":
    unittest.main()
