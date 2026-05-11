"""Trail and truck helpers."""

from __future__ import annotations

import hashlib
import json
import re
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

    def _run(self, args: List[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def _parse_latest_version(
        self, module: str, name: str, output: str
    ) -> Optional[int]:
        pattern = re.compile(
            rf"\b{re.escape(module)}\s+{re.escape(name)}\s+(?P<version>\d+)\b"
        )
        versions = [int(match.group("version")) for match in pattern.finditer(output)]
        return max(versions) if versions else None

    def ensure_truck(self) -> None:
        result = self._run([self.config.truck_cmd, "--help"])
        if result.returncode != 0:
            raise RuntimeError(
                f"{self.config.truck_cmd} is unavailable. "
                f"stderr: {result.stderr.strip()}"
            )

    def get_latest_version(self, module: str, name: str) -> Optional[int]:
        result = self._run([self.config.truck_cmd, "list", "-m", module, "-n", name])
        if result.returncode != 0:
            return None
        return self._parse_latest_version(module, name, result.stdout)

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
        chosen_version = (
            version if version is not None else self.get_next_version(module, file_name)
        )
        cmd = [
            self.config.truck_cmd,
            "push",
            module,
            str(path),
            "-v",
            str(chosen_version),
            "--desc",
            description,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"truck push failed for {path}. stderr: {result.stderr.strip()}"
            )
        resolved_version = self.get_latest_version(module, file_name) or chosen_version
        return ArtifactVersion(
            module=module,
            name=file_name,
            version=resolved_version,
            local_path=path,
        )

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
