"""IFX conversion pipeline."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urljoin, urlencode

import requests
from requests import HTTPError

from model_release_pipeline.config import IfxConfig
from model_release_pipeline.models import ArtifactVersion
from model_release_pipeline.services.trail_client import TrailClient


class IfxPipelineError(RuntimeError):
    """IFX failure with partial state worth preserving in the run record."""

    def __init__(self, message: str, partial_result: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.partial_result = partial_result or {}


class IfxPipeline:
    """Pushes ONNX to truck, triggers IFX generation and collects outputs."""

    def __init__(self, config: IfxConfig) -> None:
        self.config = config
        self.trail = TrailClient(config)
        self._jenkins_session = requests.Session()

    def _jenkins_url(self) -> str:
        return (
            f"{self.config.jenkins_base_url.rstrip('/')}/job/"
            f"{self.config.jenkins_job_name}/buildWithParameters"
        )

    def _jenkins_crumb_url(self) -> str:
        return f"{self.config.jenkins_base_url.rstrip('/')}/crumbIssuer/api/json"

    def _jenkins_api_url(self, url: str, suffix: str = "api/json") -> str:
        absolute_url = urljoin(f"{self.config.jenkins_base_url.rstrip('/')}/", url)
        return f"{absolute_url.rstrip('/')}/{suffix.lstrip('/')}"

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
        method = self.config.jenkins_http_method.upper()
        headers: Dict[str, str] = {}
        crumb: Dict[str, Any] = {}
        if method == "POST" and self.config.jenkins_use_crumb:
            crumb_response = self._jenkins_session.get(
                self._jenkins_crumb_url(), timeout=30
            )
            try:
                crumb_response.raise_for_status()
            except HTTPError as exc:
                raise RuntimeError(
                    "Failed to get Jenkins crumb: "
                    f"GET {self._jenkins_crumb_url()} "
                    f"status={crumb_response.status_code}\n"
                    f"response: {crumb_response.text.strip()}"
                ) from exc
            crumb = crumb_response.json()
            crumb_field = crumb.get("crumbRequestField")
            crumb_value = crumb.get("crumb")
            if crumb_field and crumb_value:
                headers[str(crumb_field)] = str(crumb_value)
        if method == "GET":
            response = self._jenkins_session.get(
                self._jenkins_url(), params=payload, timeout=30
            )
        elif method == "POST":
            response = self._jenkins_session.post(
                self._jenkins_url(),
                data=payload,
                headers=headers,
                timeout=30,
            )
        else:
            raise RuntimeError(f"Unsupported Jenkins HTTP method: {method}")
        try:
            response.raise_for_status()
        except HTTPError as exc:
            raise RuntimeError(
                "Jenkins trigger failed: "
                f"{method} {self._jenkins_url()} status={response.status_code}\n"
                f"response: {response.text.strip()}"
            ) from exc
        return {
            "url": f"{self._jenkins_url()}?{urlencode(payload)}",
            "method": method,
            "status_code": response.status_code,
            "queue_url": response.headers.get("Location"),
            "crumb": {
                "enabled": bool(self.config.jenkins_use_crumb and method == "POST"),
                "field": crumb.get("crumbRequestField"),
            },
        }

    def _wait_for_jenkins_build(
        self,
        queue_url: Optional[str],
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        progress_step: int = 0,
    ) -> Dict[str, Any]:
        if not queue_url:
            raise RuntimeError("Jenkins did not return a queue Location header.")
        started = time.time()
        last_progress = 0.0
        build_url: Optional[str] = None
        queue_api = self._jenkins_api_url(queue_url)

        def emit(detail: str, force: bool = False) -> None:
            nonlocal last_progress
            now = time.time()
            if progress and (force or now - last_progress >= 30):
                progress("Poll IFX Artifacts", progress_step, detail)
                last_progress = now

        emit(f"waiting Jenkins queue; queue_url: {queue_url}", force=True)
        while time.time() - started < self.config.timeout_sec:
            response = self._jenkins_session.get(queue_api, timeout=30)
            response.raise_for_status()
            payload = response.json()
            executable = payload.get("executable") or {}
            if executable.get("url"):
                build_url = executable["url"]
                emit(f"Jenkins build assigned; build_url: {build_url}", force=True)
                break
            elapsed = int(time.time() - started)
            why = payload.get("why") or "waiting for executor"
            emit(f"queue pending ({elapsed}s); {why}")
            time.sleep(min(self.config.poll_interval_sec, 10))
        if not build_url:
            raise TimeoutError(f"Timed out waiting for Jenkins queue item: {queue_url}")

        return self._wait_for_jenkins_build_url(
            build_url, started=started, progress=progress, progress_step=progress_step
        )

    def _wait_for_jenkins_build_url(
        self,
        build_url: str,
        *,
        started: Optional[float] = None,
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        progress_step: int = 0,
    ) -> Dict[str, Any]:
        started = started or time.time()
        last_progress = 0.0

        def emit(detail: str, force: bool = False) -> None:
            nonlocal last_progress
            now = time.time()
            if progress and (force or now - last_progress >= 30):
                progress("Poll IFX Artifacts", progress_step, detail)
                last_progress = now

        build_api = self._jenkins_api_url(build_url)
        build_payload: Dict[str, Any] = {}
        build_running_reported = False
        emit(f"polling Jenkins build; build_url: {build_url}", force=True)
        while time.time() - started < self.config.timeout_sec:
            response = self._jenkins_session.get(build_api, timeout=30)
            response.raise_for_status()
            build_payload = response.json()
            if not build_payload.get("building"):
                emit(
                    "Jenkins build finished; "
                    f"result: {build_payload.get('result')}; "
                    f"build_number: {build_payload.get('number')}",
                    force=True,
                )
                break
            elapsed = int(time.time() - started)
            estimated_ms = build_payload.get("estimatedDuration")
            estimated_detail = (
                f"; estimated_total: {int(estimated_ms / 1000)}s"
                if isinstance(estimated_ms, (int, float)) and estimated_ms > 0
                else ""
            )
            emit(
                f"build running ({elapsed}s){estimated_detail}",
                force=not build_running_reported,
            )
            build_running_reported = True
            time.sleep(min(self.config.poll_interval_sec, 10))
        if build_payload.get("building"):
            raise TimeoutError(f"Timed out waiting for Jenkins build: {build_url}")

        emit("fetching Jenkins consoleText for artifact versions", force=True)
        console_response = self._jenkins_session.get(
            self._jenkins_api_url(build_url, "consoleText"), timeout=30
        )
        console_response.raise_for_status()
        emit(
            f"downloaded Jenkins consoleText; bytes: {len(console_response.text)}",
            force=True,
        )
        return {
            "build_url": build_url,
            "build_number": build_payload.get("number"),
            "result": build_payload.get("result"),
            "console_text": console_response.text,
        }

    def _collect_jenkins_ifx_result(
        self,
        jenkins_result: Dict[str, Any],
        onnx_arg: str,
        *,
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        progress_step: int = 0,
    ) -> Dict[str, Any]:
        if jenkins_result.get("build_url"):
            build_result = self._wait_for_jenkins_build_url(
                jenkins_result["build_url"],
                progress=progress,
                progress_step=progress_step,
            )
        else:
            build_result = self._wait_for_jenkins_build(
                jenkins_result.get("queue_url"),
                progress=progress,
                progress_step=progress_step,
            )
        persisted_build = {
            key: value for key, value in build_result.items() if key != "console_text"
        }
        console_lines = build_result.get("console_text", "").splitlines()
        persisted_build["console_tail"] = console_lines[-80:]
        persisted_build["last_poll_status"] = build_result.get("result") or "incomplete"
        updated_jenkins = {**jenkins_result, **persisted_build}
        parsed = self._parse_ifx_mapping_from_console(
            build_result.get("console_text", ""), onnx_arg
        )
        ifx_mapping = parsed["mapping"]
        failed_uploads = parsed["failed_uploads"]
        missing = [
            platform
            for platform in self.config.expected_platforms
            if platform not in ifx_mapping
        ]
        if progress:
            found = [
                platform
                for platform in self.config.expected_platforms
                if platform in ifx_mapping
            ]
            progress(
                "Poll IFX Artifacts",
                progress_step,
                f"parsed console; found: {found or 'none'}; "
                f"missing: {missing or 'none'}; "
                f"failed_uploads: {failed_uploads or 'none'}",
            )
        result = {
            "jenkins": updated_jenkins,
            "ifx_mapping": ifx_mapping,
            "failed_uploads": failed_uploads,
        }
        if failed_uploads or missing or build_result.get("result") != "SUCCESS":
            raise IfxPipelineError(
                "IFX conversion did not produce all expected artifacts. "
                f"jenkins_result={build_result.get('result')}; "
                f"failed_uploads={failed_uploads}; missing={missing}; "
                f"build_url={build_result.get('build_url')}",
                result,
            )
        return result

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def _parse_ifx_mapping_from_console(
        self,
        console_text: str,
        onnx_arg: str,
    ) -> Dict[str, Any]:
        clean_text = self._strip_ansi(console_text)
        failed_uploads = sorted(
            set(re.findall(r"(\S+\.ifxmodel)\s+upload failed", clean_text))
        )
        mapping: Dict[str, Dict[str, Any]] = {}
        for line in clean_text.splitlines():
            if "planner.model-files" not in line or ".ifxmodel" not in line:
                continue
            parts = line.split()
            try:
                name_index = next(
                    index for index, part in enumerate(parts) if part.endswith(".ifxmodel")
                )
            except StopIteration:
                continue
            name = parts[name_index]
            if name in failed_uploads:
                continue
            version: Optional[int] = None
            for token in parts[name_index + 1 :]:
                if token.isdigit():
                    version = int(token)
                    break
            if version is None:
                continue
            for platform in self.config.expected_platforms:
                if platform in name:
                    mapping[platform] = {"name": name, "version": version}
        parts = onnx_arg.split()
        mapping["onnx"] = {"name": parts[1], "version": int(parts[3])}
        return {"mapping": mapping, "failed_uploads": failed_uploads}

    def _wait_for_ifx_mapping(
        self,
        label: str,
        onnx_arg: str,
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        progress_step: int = 0,
    ) -> Dict[str, Dict[str, Any]]:
        started = time.time()
        last_progress = 0.0
        while time.time() - started < self.config.timeout_sec:
            file_infos = self.trail.query_files_by_label(label)
            mapping = self.trail.map_files_by_platform(
                file_infos, self.config.expected_platforms
            )
            missing = [
                platform
                for platform in self.config.expected_platforms
                if platform not in mapping
            ]
            now = time.time()
            if progress and (last_progress == 0.0 or now - last_progress >= 30):
                elapsed = int(now - started)
                found = [
                    platform
                    for platform in self.config.expected_platforms
                    if platform in mapping
                ]
                progress(
                    "Poll IFX Artifacts",
                    progress_step,
                    f"label polling ({elapsed}s); found: {found or 'none'}; "
                    f"missing: {missing or 'none'}",
                )
                last_progress = now
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
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
    ) -> Dict[str, Any]:
        upload_result = self.upload(
            local_onnx_file=local_onnx_file,
            description=description,
            version=version,
            dry_run=dry_run,
            progress=progress,
            step_offset=0,
        )
        convert_result = self.convert(
            upload_result=upload_result,
            dry_run=dry_run,
            progress=progress,
            step_offset=3,
        )
        return {**upload_result, **convert_result}

    def upload(
        self,
        local_onnx_file: str | Path,
        description: str,
        version: Optional[int] = None,
        dry_run: bool = False,
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        step_offset: int = 0,
    ) -> Dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("IFX pipeline is disabled in config.")

        local_path = Path(local_onnx_file).expanduser().resolve()

        if dry_run:
            if progress:
                progress(
                    "Select Truck Runner",
                    step_offset + 1,
                    "dry-run: skip truck runner probe",
                )
                progress(
                    "Upload ONNX To Truck",
                    step_offset + 2,
                    f"dry-run: {local_path}",
                )
                progress("Prepare Precision Test", step_offset + 3, "dry-run")
            chosen_version = version or 0
            onnx_artifact = ArtifactVersion(
                module=self.config.truck_module,
                name=local_path.name,
                version=chosen_version,
                local_path=local_path,
            )
            precision_test_arg = (
                self.config.precision_test_truck_arg
                or f"{self.config.precision_test_module} "
                f"{Path(self.config.precision_test_local_path).name} -v <version>"
            )
            return {
                "onnx": onnx_artifact.to_dict(),
                "precision_test_arg": precision_test_arg,
                "upload_description": description,
                "truck_runner": {
                    "configured": self.config.truck_runner,
                    "selected": "dry_run",
                    "attempts": [],
                },
            }

        try:
            if progress:
                progress(
                    "Select Truck Runner",
                    step_offset + 1,
                    f"configured: {self.config.truck_runner}",
                )
            runner = self.trail._select_truck_runner()
            if progress:
                progress(
                    "Upload ONNX To Truck",
                    step_offset + 2,
                    f"runner: {self.config.truck_runner} -> {runner}; desc: {description}",
                )
            onnx_artifact = self.trail.push_file(
                file_path=local_path,
                module=self.config.truck_module,
                description=description,
                version=version,
            )
            if progress:
                progress(
                    "Prepare Precision Test",
                    step_offset + 3,
                    "resolve precision_test_file",
                )
            precision_test_arg = self._ensure_precision_test_arg()
        except Exception as exc:
            runner = self.trail.runner_info()
            raise RuntimeError(
                f"{exc}\ntruck runner: "
                f"{runner.get('configured') or 'NA'} -> {runner.get('selected') or 'NA'}"
            ) from exc

        return {
            "onnx": onnx_artifact.to_dict(),
            "precision_test_arg": precision_test_arg,
            "upload_description": description,
            "truck_runner": self.trail.runner_info(),
        }

    def convert(
        self,
        upload_result: Dict[str, Any],
        dry_run: bool = False,
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        step_offset: int = 0,
    ) -> Dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("IFX pipeline is disabled in config.")

        onnx = upload_result.get("onnx") or {}
        precision_test_arg = upload_result.get("precision_test_arg")
        if not onnx or precision_test_arg is None:
            raise RuntimeError("Missing uploaded ONNX or precision_test_arg. Run upload first.")
        onnx_arg = ArtifactVersion(
            module=onnx.get("module") or self.config.truck_module,
            name=onnx["name"],
            version=onnx["version"],
        ).truck_pull_arg()
        if not onnx_arg:
            raise RuntimeError("Failed to build truck pull arg for ONNX artifact.")

        label = (
            f"{self.config.label_prefix}{int(time.time())}"
            if self.config.use_label
            else ""
        )
        params = {
            "username": self.config.username,
            "truck_py_arguments_of_onnx": onnx_arg,
            "max_batch": self.config.max_batch,
            "x86_convert": self.config.x86_convert,
            "precision_convert": self.config.precision_convert,
            "precision_test_file": precision_test_arg,
            **self.config.extra_params,
        }
        if label:
            params["label"] = label
        if dry_run:
            if progress:
                detail = f"dry-run label: {label}" if label else "dry-run without label"
                progress("Trigger Jenkins IFX", step_offset + 1, detail)
                progress("Poll IFX Artifacts", step_offset + 2, "dry-run placeholder mapping")
            placeholder_mapping = {"onnx": {"name": onnx["name"], "version": onnx["version"]}}
            for platform in self.config.expected_platforms:
                placeholder_mapping[platform] = {
                    "name": f"<{platform}_ifx_name>",
                    "version": "<version>",
                }
            return {
                "jenkins": {"method": self.config.method, "params": params},
                "ifx_mapping": placeholder_mapping,
                "label": label or None,
            }

        if self.config.method == "jenkins":
            if progress:
                detail = f"label: {label}" if label else "without label"
                progress("Trigger Jenkins IFX", step_offset + 1, detail)
            jenkins_result = self._trigger_jenkins(params)
        else:
            raise RuntimeError(f"Unsupported IFX method: {self.config.method}")

        if progress:
            progress(
                "Poll IFX Artifacts",
                step_offset + 2,
                f"expected: {', '.join(self.config.expected_platforms)}",
            )
        partial_result = {"jenkins": jenkins_result, "label": label or None}
        if label:
            ifx_mapping = self._wait_for_ifx_mapping(
                label,
                onnx_arg,
                progress=progress,
                progress_step=step_offset + 2,
            )
        else:
            try:
                collected = self._collect_jenkins_ifx_result(
                    jenkins_result,
                    onnx_arg,
                    progress=progress,
                    progress_step=step_offset + 2,
                )
                jenkins_result = collected["jenkins"]
                partial_result["jenkins"] = jenkins_result
                ifx_mapping = collected["ifx_mapping"]
            except IfxPipelineError:
                raise
            except Exception as exc:
                raise IfxPipelineError(str(exc), partial_result) from exc
        return {
            "jenkins": jenkins_result,
            "ifx_mapping": ifx_mapping,
            "label": label or None,
        }

    def poll_existing(
        self,
        upload_result: Dict[str, Any],
        progress: Optional[Callable[[str, int, Optional[str]], None]] = None,
        step_offset: int = 0,
    ) -> Dict[str, Any]:
        """Collect artifacts from an already-triggered Jenkins IFX build."""
        if not self.config.enabled:
            raise RuntimeError("IFX pipeline is disabled in config.")

        onnx = upload_result.get("onnx") or {}
        if not onnx:
            raise RuntimeError("Missing uploaded ONNX. Run upload first.")
        jenkins_result = upload_result.get("jenkins") or {}
        if not (jenkins_result.get("queue_url") or jenkins_result.get("build_url")):
            raise RuntimeError("No Jenkins queue_url/build_url found. Run ifx-convert first.")
        onnx_arg = ArtifactVersion(
            module=onnx.get("module") or self.config.truck_module,
            name=onnx["name"],
            version=onnx["version"],
        ).truck_pull_arg()
        if not onnx_arg:
            raise RuntimeError("Failed to build truck pull arg for ONNX artifact.")

        if progress:
            progress(
                "Poll IFX Artifacts",
                step_offset + 1,
                f"reuse Jenkins build: {jenkins_result.get('build_url') or jenkins_result.get('queue_url')}",
            )
        collected = self._collect_jenkins_ifx_result(
            jenkins_result,
            onnx_arg,
            progress=progress,
            progress_step=step_offset + 1,
        )
        return {
            "jenkins": collected["jenkins"],
            "ifx_mapping": collected["ifx_mapping"],
            "failed_uploads": collected.get("failed_uploads", []),
            "label": upload_result.get("label"),
        }
