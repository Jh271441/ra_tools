"""Background job runner for web-triggered CLI actions."""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from model_release_pipeline.web.actions import ACTIONS, build_cli_command


class JobManager:
    """Runs CLI actions in background threads and keeps recent logs."""

    def __init__(self, package_root: Path, config_path: Optional[str] = None) -> None:
        self.package_root = package_root
        self.config_path = config_path
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def build_command(
        self,
        release_id: str,
        action: str,
        dry_run: bool = False,
        payload: Optional[Dict[str, Any]] = None,
    ) -> list[str]:
        return build_cli_command(
            release_id,
            action,
            dry_run=dry_run,
            payload=payload,
            config_path=self.config_path,
        )

    def start(
        self,
        release_id: str,
        action: str,
        dry_run: bool,
        confirm_text: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        spec = ACTIONS[action]
        expected_confirm = release_id if spec.get("needs_run_id", True) else "EXPORT"
        if spec["requires_confirm"] and not dry_run and confirm_text != expected_confirm:
            raise PermissionError(
                f"Real action requires confirm_text to match {expected_confirm}."
            )

        command = self.build_command(
            release_id, action, dry_run=dry_run, payload=payload
        )
        job_id = uuid.uuid4().hex[:12]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job = {
            "job_id": job_id,
            "release_id": release_id,
            "action": action,
            "label": spec["label"],
            "dry_run": dry_run,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "command": " ".join(command),
            "returncode": None,
            "log": [],
        }
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, command),
            daemon=True,
        )
        thread.start()
        return self.get(job_id)

    def _append(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["log"].append(line.rstrip("\n"))
            job["log"] = job["log"][-500:]
            job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _finish(self, job_id: str, returncode: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["returncode"] = returncode
            job["status"] = "completed" if returncode == 0 else "failed"
            job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _run_job(self, job_id: str, command: list[str]) -> None:
        self._append(job_id, f"$ {' '.join(command)}")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.package_root.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._append(job_id, f"failed to start: {exc}")
            self._finish(job_id, 127)
            return

        assert process.stdout is not None
        for line in process.stdout:
            self._append(job_id, line)
        self._finish(job_id, process.wait())

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise FileNotFoundError(f"Job not found: {job_id}")
            return json.loads(json.dumps(self._jobs[job_id]))

    def list(self) -> Dict[str, Any]:
        with self._lock:
            jobs = list(self._jobs.values())
        return {
            "jobs": sorted(
                json.loads(json.dumps(jobs)),
                key=lambda item: item.get("updated_at") or "",
                reverse=True,
            )
        }
