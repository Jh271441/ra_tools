"""IFX conversion pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from model_release_pipeline.config import IfxConfig
from model_release_pipeline.models import ArtifactVersion
from model_release_pipeline.services.trail_client import TrailClient


class IfxPipeline:
    """Pushes ONNX to truck, triggers IFX generation and collects outputs."""

    def __init__(self, config: IfxConfig) -> None:
        self.config = config
        self.trail = TrailClient(config)

    def _jenkins_url(self) -> str:
        return (
            f"{self.config.jenkins_base_url.rstrip('/')}/job/"
            f"{self.config.jenkins_job_name}/buildWithParameters"
        )

    def _ensure_precision_test_arg(self) -> str:
        if self.config.precision_test_truck_arg:
            return self.config.precision_test_truck_arg
        if self.config.precision_test_local_path:
            return self.trail.upload_precision_test(
                self.config.precision_test_local_path
            )
        raise RuntimeError(
            "Neither precision_test_truck_arg nor precision_test_local_path "
            "is configured."
        )

    def _trigger_jenkins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(params)
        if self.config.jenkins_token:
            payload["token"] = self.config.jenkins_token
        response = requests.get(self._jenkins_url(), params=payload, timeout=30)
        response.raise_for_status()
        return {
            "url": f"{self._jenkins_url()}?{urlencode(payload)}",
            "status_code": response.status_code,
        }

    def _wait_for_ifx_mapping(
        self, label: str, onnx_arg: str
    ) -> Dict[str, Dict[str, Any]]:
        started = time.time()
        while time.time() - started < self.config.timeout_sec:
            file_infos = self.trail.query_files_by_label(label)
            mapping = self.trail.map_files_by_platform(
                file_infos, self.config.expected_platforms
            )
            if len(mapping) >= len(self.config.expected_platforms):
                parts = onnx_arg.split()
                mapping["onnx"] = {"name": parts[1], "version": int(parts[3])}
                return mapping
            time.sleep(self.config.poll_interval_sec)
        raise TimeoutError(
            f"Timed out waiting for IFX files with label {label}. "
            f"Expected platforms: {', '.join(self.config.expected_platforms)}"
        )

    def run(
        self,
        local_onnx_file: str | Path,
        description: str,
        version: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("IFX pipeline is disabled in config.")

        local_path = Path(local_onnx_file).expanduser().resolve()
        label = f"{self.config.label_prefix}{int(time.time())}"

        if dry_run:
            chosen_version = version or 0
            onnx_artifact = ArtifactVersion(
                module=self.config.truck_module,
                name=local_path.name,
                version=chosen_version,
                local_path=local_path,
                label=label,
            )
            precision_test_arg = (
                self.config.precision_test_truck_arg
                or f"{self.config.precision_test_module} "
                f"{Path(self.config.precision_test_local_path).name} -v <version>"
            )
            params = {
                "username": self.config.username,
                "truck_py_arguments_of_onnx": onnx_artifact.truck_pull_arg(),
                "max_batch": self.config.max_batch,
                "x86_convert": self.config.x86_convert,
                "precision_convert": self.config.precision_convert,
                "precision_test_file": precision_test_arg,
                "label": label,
                **self.config.extra_params,
            }
            placeholder_mapping = {
                "onnx": {"name": local_path.name, "version": chosen_version}
            }
            for platform in self.config.expected_platforms:
                placeholder_mapping[platform] = {
                    "name": f"<{platform}_ifx_name>",
                    "version": "<version>",
                }
            return {
                "onnx": onnx_artifact.to_dict(),
                "precision_test_arg": precision_test_arg,
                "jenkins": {"method": self.config.method, "params": params},
                "ifx_mapping": placeholder_mapping,
                "label": label,
            }

        onnx_artifact = self.trail.push_file(
            file_path=local_path,
            module=self.config.truck_module,
            description=description,
            version=version,
        )
        precision_test_arg = self._ensure_precision_test_arg()
        onnx_arg = onnx_artifact.truck_pull_arg()
        if not onnx_arg:
            raise RuntimeError("Failed to build truck pull arg for ONNX artifact.")

        if self.config.method == "jenkins":
            jenkins_result = self._trigger_jenkins(
                {
                    "username": self.config.username,
                    "truck_py_arguments_of_onnx": onnx_arg,
                    "max_batch": self.config.max_batch,
                    "x86_convert": self.config.x86_convert,
                    "precision_convert": self.config.precision_convert,
                    "precision_test_file": precision_test_arg,
                    "label": label,
                    **self.config.extra_params,
                }
            )
        else:
            raise RuntimeError(f"Unsupported IFX method: {self.config.method}")

        ifx_mapping = self._wait_for_ifx_mapping(label, onnx_arg)
        return {
            "onnx": onnx_artifact.to_dict(),
            "precision_test_arg": precision_test_arg,
            "jenkins": jenkins_result,
            "ifx_mapping": ifx_mapping,
            "label": label,
        }
