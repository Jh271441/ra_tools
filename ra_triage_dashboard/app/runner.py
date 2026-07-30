from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .db import Database
from .settings import Settings
from .single_case_worker import RESULT_PREFIX


class InferenceRunner:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._lock = threading.Lock()
        self._active_jobs: set[str] = set()

    def launch(self, job: dict[str, Any], request: dict[str, Any]) -> None:
        with self._lock:
            self._active_jobs.add(job["id"])
        thread = threading.Thread(
            target=self._run,
            args=(job["id"], request),
            daemon=True,
            name=f"triage-inference-{job['id'][:8]}",
        )
        thread.start()

    def _run(self, job_id: str, request: dict[str, Any]) -> None:
        api_key = str(request.pop("api_key", ""))
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "worker.log"
        try:
            self.database.update_job(job_id, status="running")
            payload = {
                **request,
                "api_key": api_key,
                "bev_animation_manifest": str(self.settings.ares_manifest),
            }
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "RA_AUTO_TRIAGE_ROOT": str(self.settings.ra_auto_triage_root),
                "RA_TOOLS_ENABLED": "false",
                "BAG_CACHE_READ_ONLY": "true",
                "LANG": os.environ.get("LANG", "C.UTF-8"),
            }
            process = subprocess.Popen(
                [sys.executable, str(self.settings.app_root / "app" / "single_case_worker.py")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=job_dir,
                env=env,
            )
            try:
                output, _ = process.communicate(
                    json.dumps(payload, ensure_ascii=False),
                    timeout=self.settings.job_timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
                raise RuntimeError(
                    f"推理超过 {self.settings.job_timeout_seconds}s 超时，已终止。"
                )
            safe_output = self._redact(output, api_key)
            log_path.write_text(safe_output, encoding="utf-8")
            result = self._extract_result(output, api_key)
            if result.get("success"):
                self.database.update_job(
                    job_id,
                    status="succeeded",
                    result=result,
                    log_path=str(log_path),
                )
            else:
                error = str(result.get("error") or "模型未返回成功结果。")
                self.database.update_job(
                    job_id,
                    status="failed",
                    result=result,
                    error_text=self._redact(error, api_key),
                    log_path=str(log_path),
                )
        except Exception as exc:
            self.database.update_job(
                job_id,
                status="failed",
                error_text=self._redact(str(exc), api_key),
                log_path=str(log_path) if log_path.exists() else "",
            )
        finally:
            api_key = ""
            with self._lock:
                self._active_jobs.discard(job_id)

    @staticmethod
    def _extract_result(output: str, api_key: str) -> dict[str, Any]:
        for line in reversed(output.splitlines()):
            if not line.startswith(RESULT_PREFIX):
                continue
            try:
                parsed = json.loads(line[len(RESULT_PREFIX) :])
                return InferenceRunner._scrub_object(parsed, api_key)
            except (TypeError, ValueError):
                break
        return {"success": False, "error": "worker 未输出可解析的结果。"}

    @staticmethod
    def _redact(text: str, api_key: str) -> str:
        if not text:
            return ""
        if api_key:
            return text.replace(api_key, "[REDACTED]")
        return text

    @classmethod
    def _scrub_object(cls, value: Any, api_key: str) -> Any:
        if isinstance(value, dict):
            return {key: cls._scrub_object(item, api_key) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._scrub_object(item, api_key) for item in value]
        if isinstance(value, str):
            return cls._redact(value, api_key)
        return value
