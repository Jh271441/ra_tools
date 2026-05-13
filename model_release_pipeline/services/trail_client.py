"""Trail and truck helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from model_release_pipeline.config import IfxConfig
from model_release_pipeline.models import ArtifactVersion


class TrailClient:
    """Minimal client for truck and fileserver queries."""

    def __init__(self, config: IfxConfig) -> None:
        self.config = config
        self._runner: Optional[str] = None
        self.runner_attempts: List[Dict[str, Any]] = []

    def _run(self, args: List[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(args, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(
                args=args,
                returncode=127,
                stdout="",
                stderr=str(exc),
            )

    def _local_truck_args(self, args: List[str]) -> List[str]:
        if not self.config.truck_local_workdir and not self.config.truck_local_setup:
            return shlex.split(self.config.truck_cmd) + args
        return self._shell_truck_args(
            prefix=[],
            shell=self.config.truck_local_shell,
            workdir=self.config.truck_local_workdir,
            setup=self.config.truck_local_setup,
            args=args,
        )

    def _shell_truck_args(
        self,
        prefix: List[str],
        shell: str,
        workdir: str,
        setup: str,
        args: List[str],
    ) -> List[str]:
        truck_cmd = " ".join(shlex.quote(part) for part in shlex.split(self.config.truck_cmd))
        script_parts = []
        if workdir:
            script_parts.append(f"cd {shlex.quote(workdir)} || exit $?")
        if setup:
            # Some Voyager setup hooks emit non-fatal shell errors under zsh
            # (for example bash-only autocomplete functions). Keep the env
            # changes, but let truck.py decide whether the command succeeds.
            script_parts.append(f"{setup} || true")
        script_parts.append("set -e")
        script_parts.append(f"{truck_cmd} \"$@\"")
        return [
            *prefix,
            shell,
            "-lc",
            "; ".join(script_parts),
            self.config.truck_cmd,
            *args,
        ]

    def _docker_container(self) -> str:
        return self.config.truck_docker_container or os.environ.get(
            self.config.truck_docker_container_env, ""
        )

    def _docker_truck_args(self, args: List[str]) -> List[str]:
        container = self._docker_container()
        if not container:
            raise RuntimeError(
                "Docker truck runner requires a container name. Set "
                f"{self.config.truck_docker_container_env} or "
                "ifx.truck_docker_container."
            )
        return self._shell_truck_args(
            prefix=["docker", "exec", container],
            shell=self.config.truck_docker_shell,
            workdir=self.config.truck_docker_workdir,
            setup=self.config.truck_docker_setup,
            args=args,
        )

    def _ssh_host(self) -> str:
        return self.config.truck_ssh_host

    def _ssh_truck_args(self, args: List[str]) -> List[str]:
        host = self._ssh_host()
        if not host:
            raise RuntimeError("SSH truck runner requires ifx.truck_ssh_host.")
        remote_args = self._shell_truck_args(
            prefix=[],
            shell=self.config.truck_ssh_shell,
            workdir=self.config.truck_ssh_workdir,
            setup=self.config.truck_ssh_setup,
            args=args,
        )
        return ["ssh", host, " ".join(shlex.quote(part) for part in remote_args)]

    def _select_truck_runner(self) -> str:
        if self._runner:
            return self._runner
        self.runner_attempts = []
        runner = self.config.truck_runner.lower()
        if runner not in {"auto", "local", "docker", "ssh"}:
            raise RuntimeError(f"Unsupported truck_runner: {self.config.truck_runner}")
        if runner == "local":
            self._runner = "local"
            self.runner_attempts.append(
                {"runner": "local", "returncode": None, "stderr": "forced by config"}
            )
            return self._runner
        if runner == "docker":
            self._runner = "docker"
            self.runner_attempts.append(
                {"runner": "docker", "returncode": None, "stderr": "forced by config"}
            )
            return self._runner
        if runner == "ssh":
            self._runner = "ssh"
            self.runner_attempts.append(
                {"runner": "ssh", "returncode": None, "stderr": "forced by config"}
            )
            return self._runner

        local_result = self._run(self._local_truck_args(["--help"]))
        self.runner_attempts.append(
            {
                "runner": "local",
                "returncode": local_result.returncode,
                "stderr": local_result.stderr.strip(),
            }
        )
        if local_result.returncode == 0:
            self._runner = "local"
            return self._runner

        if self._docker_container():
            docker_result = self._run(self._docker_truck_args(["--help"]))
            self.runner_attempts.append(
                {
                    "runner": "docker",
                    "returncode": docker_result.returncode,
                    "stderr": docker_result.stderr.strip(),
                }
            )
            if docker_result.returncode == 0:
                self._runner = "docker"
                return self._runner
        if self._ssh_host():
            ssh_result = self._run(self._ssh_truck_args(["--help"]))
            self.runner_attempts.append(
                {
                    "runner": "ssh",
                    "returncode": ssh_result.returncode,
                    "stderr": ssh_result.stderr.strip(),
                }
            )
            if ssh_result.returncode == 0:
                self._runner = "ssh"
                return self._runner
        raise RuntimeError(
            f"{self.config.truck_cmd} is unavailable locally and no working "
            "Voyager docker/SSH truck runner was found. Run inside Voyager docker, "
            f"or export {self.config.truck_docker_container_env}=<container>, "
            "or set ifx.truck_docker_container / ifx.truck_ssh_host in config."
        )

    def _run_truck(
        self,
        args: List[str],
        runner: Optional[str] = None,
    ) -> subprocess.CompletedProcess[str]:
        chosen_runner = runner or self._select_truck_runner()
        if chosen_runner == "docker":
            return self._run(self._docker_truck_args(args))
        if chosen_runner == "ssh":
            return self._run(self._ssh_truck_args(args))
        return self._run(self._local_truck_args(args))

    def _stage_file_for_docker(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Local file not found for docker staging: {path}")
        container = self._docker_container()
        if not container:
            raise RuntimeError("Docker container is not configured for truck staging.")
        digest = hashlib.md5(str(path).encode()).hexdigest()[:12]
        container_dir = (
            f"{self.config.truck_docker_stage_dir.rstrip('/')}/{digest}"
        )
        container_path = f"{container_dir}/{path.name}"
        mkdir_result = self._run(["docker", "exec", container, "mkdir", "-p", container_dir])
        if mkdir_result.returncode != 0:
            raise RuntimeError(
                f"docker mkdir failed for {container_dir}. "
                f"stderr: {mkdir_result.stderr.strip()}"
            )
        copy_result = self._run(["docker", "cp", str(path), f"{container}:{container_path}"])
        if copy_result.returncode != 0:
            raise RuntimeError(
                f"docker cp failed for {path}. stderr: {copy_result.stderr.strip()}"
            )
        return container_path

    def _stage_file_for_ssh(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Local file not found for SSH staging: {path}")
        host = self._ssh_host()
        if not host:
            raise RuntimeError("SSH host is not configured for truck staging.")
        digest = hashlib.md5(str(path).encode()).hexdigest()[:12]
        remote_dir = f"{self.config.truck_ssh_stage_dir.rstrip('/')}/{digest}"
        remote_path = f"{remote_dir}/{path.name}"
        mkdir_result = self._run(["ssh", host, "mkdir", "-p", remote_dir])
        if mkdir_result.returncode != 0:
            raise RuntimeError(
                f"ssh mkdir failed for {remote_dir}. "
                f"stderr: {mkdir_result.stderr.strip()}"
            )
        copy_result = self._run(["scp", str(path), f"{host}:{remote_path}"])
        if copy_result.returncode != 0:
            raise RuntimeError(
                f"scp failed for {path}. stderr: {copy_result.stderr.strip()}"
            )
        return remote_path

    def _stage_file_for_runner(self, path: Path, runner: str) -> str:
        if runner == "docker":
            return self._stage_file_for_docker(path)
        if runner == "ssh":
            return self._stage_file_for_ssh(path)
        return str(path)

    def _parse_latest_version(
        self, module: str, name: str, output: str
    ) -> Optional[int]:
        versions = self._parse_versions(module, name, output)
        return max(versions) if versions else None

    def _parse_versions(self, module: str, name: str, output: str) -> List[int]:
        pattern = re.compile(
            rf"\b{re.escape(module)}\s+{re.escape(name)}\s+(?P<version>\d+)\b"
        )
        return [int(match.group("version")) for match in pattern.finditer(output)]

    def _parse_existing_file_info(self, output: str) -> Optional[Dict[str, Any]]:
        match = re.search(
            r"exist file info:\s*md5:(?P<md5>[^,]+),\s*"
            r"module:\s*(?P<module>[^,]+),\s*"
            r"file_name:\s*(?P<name>[^,]+),\s*"
            r"version:\s*(?P<version>\d+)",
            output,
        )
        if not match:
            return None
        return {
            "md5": match.group("md5").strip(),
            "module": match.group("module").strip(),
            "name": match.group("name").strip(),
            "version": int(match.group("version")),
        }

    def _existing_file_message(
        self,
        existing: Dict[str, Any],
        requested_version: int,
    ) -> str:
        existing_version = existing["version"]
        return (
            "ONNX already exists in fileserver and truck did not create the "
            f"requested version {requested_version}: "
            f"{existing['module']} {existing['name']} -v {existing_version} "
            f"(md5={existing['md5']}). "
            f"Use the existing version {existing_version}, or push with a new "
            "file name if a new fileserver version is required."
        )

    def ensure_truck(self) -> None:
        result = self._run_truck(["--help"])
        if result.returncode != 0:
            raise RuntimeError(
                f"{self.config.truck_cmd} is unavailable. "
                f"stderr: {result.stderr.strip()}"
            )

    def get_latest_version(self, module: str, name: str) -> Optional[int]:
        result = self._run_truck(["list", "-m", module, "-n", name])
        if result.returncode != 0:
            return None
        return self._parse_latest_version(module, name, result.stdout)

    def version_exists(
        self,
        module: str,
        name: str,
        version: int,
        attempts: int = 3,
        delay_sec: float = 1.0,
    ) -> tuple[bool, subprocess.CompletedProcess[str]]:
        last_result: Optional[subprocess.CompletedProcess[str]] = None
        for attempt in range(attempts):
            result = self._run_truck(["list", "-m", module, "-n", name])
            last_result = result
            if result.returncode == 0 and version in self._parse_versions(
                module, name, result.stdout
            ):
                return True, result
            if attempt < attempts - 1:
                time.sleep(delay_sec)
        if last_result is None:
            last_result = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        return False, last_result

    def get_next_version(self, module: str, name: str) -> int:
        latest = self.get_latest_version(module, name)
        return 1 if latest is None else latest + 1

    def push_file(
        self,
        file_path: str | Path,
        module: str,
        description: str,
        version: Optional[int] = None,
    ) -> ArtifactVersion:
        self.ensure_truck()
        path = Path(file_path).expanduser().resolve()
        file_name = path.name
        runner = self._select_truck_runner()
        command_path = self._stage_file_for_runner(path, runner)
        chosen_version = (
            version if version is not None else self.get_next_version(module, file_name)
        )
        cmd = [
            "push",
            module,
            command_path,
            "-v",
            str(chosen_version),
            "--desc",
            description,
        ]
        result = self._run_truck(cmd, runner=runner)
        if result.returncode != 0:
            existing = self._parse_existing_file_info(result.stdout + "\n" + result.stderr)
            if existing:
                raise RuntimeError(
                    self._existing_file_message(existing, chosen_version)
                )
            raise RuntimeError(
                f"truck push failed for {path}. stderr: {result.stderr.strip()}"
            )
        if version is not None:
            exists, list_result = self.version_exists(module, file_name, chosen_version)
            if not exists:
                existing = self._parse_existing_file_info(
                    result.stdout + "\n" + result.stderr
                )
                if existing:
                    raise RuntimeError(
                        self._existing_file_message(existing, chosen_version)
                    )
                raise RuntimeError(
                    "truck push returned success but uploaded version was not found "
                    f"by truck list: {module} {file_name} -v {chosen_version}\n"
                    f"push stdout: {result.stdout.strip()}\n"
                    f"push stderr: {result.stderr.strip()}\n"
                    f"list stdout: {list_result.stdout.strip()}\n"
                    f"list stderr: {list_result.stderr.strip()}"
                )
        # An explicitly requested fileserver version is the release contract.
        # Do not replace it with `truck list` output, which may be stale or
        # incomplete immediately after a push.
        resolved_version = (
            chosen_version
            if version is not None
            else self.get_latest_version(module, file_name) or chosen_version
        )
        return ArtifactVersion(
            module=module,
            name=file_name,
            version=resolved_version,
            local_path=path,
        )

    def runner_info(self) -> Dict[str, Any]:
        return {
            "configured": self.config.truck_runner,
            "selected": self._runner,
            "attempts": self.runner_attempts,
        }

    def upload_precision_test(self, file_path: str | Path) -> str:
        artifact = self.push_file(
            file_path=file_path,
            module=self.config.precision_test_module,
            description="ifx precision test payload",
        )
        return artifact.truck_pull_arg() or ""

    def _sign(self, params: Dict[str, Any]) -> str:
        payload = dict(params)
        payload["token"] = self.config.trail_query_token
        text = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
        return hashlib.md5(text.encode()).hexdigest()

    def query_files_by_label(self, label: str) -> List[Dict[str, Any]]:
        params = {
            "label": label,
            "appid": self.config.trail_query_app_id,
            "time": int(time.time()),
        }
        params["sign"] = self._sign(params)
        url = urljoin(self.config.trail_base_url, "/fileserver/file/query")
        response = requests.get(url=url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", []) if payload.get("total", 0) > 0 else []

    @staticmethod
    def map_files_by_platform(
        file_infos: List[Dict[str, Any]], platforms: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        mapping: Dict[str, Dict[str, Any]] = {}
        for file_info in file_infos:
            name = file_info.get("name", "")
            version = file_info.get("version")
            for platform in platforms:
                if platform in name:
                    mapping[platform] = {"name": name, "version": version}
        return mapping

    @staticmethod
    def to_json(data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
