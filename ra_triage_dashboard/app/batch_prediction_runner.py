from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .batch_prediction_worker import EVENT_PREFIX, LABELS, RESULT_PREFIX
from .db import Database
from .settings import Settings


class BatchPredictionRunner:
    """Run the RA worker outside the dashboard process.

    Only one prediction/publish operation is launched at a time.  The worker
    resolves model credentials from the server-side RA checkout; neither
    credentials nor model endpoints enter HTTP requests or dashboard storage.
    """

    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        ra_root = settings.ra_auto_triage_root.resolve()
        bag_cache = settings.batch_bag_cache_dir.resolve()
        if bag_cache == ra_root or ra_root in bag_cache.parents:
            raise RuntimeError(
                "DASHBOARD_BATCH_BAG_CACHE_DIR 必须位于 RA_AUTO_TRIAGE_ROOT 之外。"
            )
        self._lock = threading.Lock()
        self._active_operation = ""
        self._active_process: subprocess.Popen[bytes] | None = None
        self._active_thread: threading.Thread | None = None
        self._shutting_down = False

    def launch_prediction(self, job: dict[str, Any]) -> bool:
        return self._launch(
            operation=f"predict:{job['id']}",
            target=self._predict,
            args=(job["id"],),
            claim=lambda: self.database.update_batch_prediction_job(
                job["id"],
                status="running",
                error_text="",
            ),
        )

    def launch_publish(self, job: dict[str, Any]) -> bool:
        return self._launch(
            operation=f"publish:{job['id']}",
            target=self._publish,
            args=(job["id"],),
            claim=lambda: self.database.update_batch_prediction_job(
                job["id"],
                publish_status="running",
                error_text="",
            ),
        )

    def _launch(
        self,
        *,
        operation: str,
        target: Any,
        args: tuple[Any, ...],
        claim: Any,
    ) -> bool:
        with self._lock:
            if self._active_operation or self._shutting_down:
                return False
            claim()
            self._active_operation = operation
            thread = threading.Thread(
                target=self._thread_entry,
                args=(target, args),
                daemon=True,
                name=f"ra-batch-{operation[:28]}",
            )
            self._active_thread = thread
        thread.start()
        return True

    def _thread_entry(self, target: Any, args: tuple[Any, ...]) -> None:
        try:
            target(*args)
        finally:
            with self._lock:
                self._active_operation = ""
                self._active_process = None
                self._active_thread = None

    def shutdown(self) -> None:
        """Stop an active worker tree before the web process exits."""
        with self._lock:
            self._shutting_down = True
            process = self._active_process
            thread = self._active_thread
        if process is not None and process.poll() is None:
            self._kill_process_group(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process)
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=5)

    def _predict(self, job_id: str) -> None:
        job = self.database.get_batch_prediction_job(job_id)
        if job is None:
            return
        issue_ids = [str(item["issue_id"]) for item in job.get("items", [])]
        run_id = ""
        try:
            result, _, log_path = self._run_worker(
                job_id=job_id,
                action="predict",
                payload={"action": "predict", "issue_ids": issue_ids},
            )
            raw_results = result.get("results")
            if not isinstance(raw_results, list):
                raw_results = []
            by_issue = {
                str(item.get("issue_id") or ""): item
                for item in raw_results
                if isinstance(item, dict) and str(item.get("issue_id") or "")
            }
            complete_results: list[dict[str, Any]] = []
            for issue_id in issue_ids:
                item = by_issue.get(issue_id)
                if item is None:
                    item = {
                        "issue_id": issue_id,
                        "success": False,
                        "error": str(
                            result.get("error") or "Batch worker 未返回该 Issue 的结果。"
                        ),
                    }
                else:
                    item = dict(item)
                    if not (
                        item.get("success") and item.get("model_label") in LABELS
                    ):
                        item["success"] = False
                        item["error"] = str(
                            item.get("error")
                            or f"模型标签不属于三分类契约: "
                            f"{item.get('model_label') or '<空>'}"
                        )
                complete_results.append(item)
            successful = [
                item
                for item in complete_results
                if item.get("success") and item.get("model_label") in LABELS
            ]
            failed_count = len(complete_results) - len(successful)
            duplicate = False
            if successful:
                run_rows = [
                    {
                        "issue_id": str(item.get("issue_id") or ""),
                        "trip_id": str(item.get("trip_id") or ""),
                        "model_label": str(item.get("model_label") or ""),
                        "model_reason": str(item.get("model_reason") or ""),
                        "model_confidence": item.get("model_confidence"),
                        "model_extra": item.get("model_extra")
                        if isinstance(item.get("model_extra"), dict)
                        else {},
                        "raw": item,
                    }
                    for item in successful
                ]
                fingerprint = {
                    "schema_version": "manual-batch-v1",
                    "config_sha256": str(result.get("config_sha256") or ""),
                    "results": sorted(
                        [
                            {
                                "issue_id": row["issue_id"],
                                "model_label": row["model_label"],
                                "model_reason": row["model_reason"],
                                "model_confidence": row["model_confidence"],
                                "model_extra": row["model_extra"],
                            }
                            for row in run_rows
                        ],
                        key=lambda row: row["issue_id"],
                    ),
                }
                source_sha256 = hashlib.sha256(
                    json.dumps(
                        fingerprint,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                safe_experiment = result.get("safe_experiment")
                if not isinstance(safe_experiment, dict):
                    safe_experiment = {}
                run, duplicate = self.database.import_model_run(
                    name=str(job.get("name") or "").strip()
                    or f"Batch {str(job.get('created_at') or '')[:16]}",
                    source_name=f"dashboard-batch:{job_id}",
                    source_sha256=source_sha256,
                    metadata={
                        "schema_version": "manual-batch-v1",
                        "experiment": safe_experiment,
                        "batch_prediction_job_id": job_id,
                        "config_sha256": str(result.get("config_sha256") or ""),
                        "ra_repo_commit": str(result.get("ra_repo_commit") or ""),
                        "trail_view_id": result.get("trail_view_id"),
                        "input_policy": {
                            "ares_bev_input": False,
                            "bag_cache_read_only": False,
                            "bag_cache_scope": "dashboard_isolated",
                            "trail_write_enabled": False,
                        },
                    },
                    rows=run_rows,
                    kind="manual_batch",
                    make_default=False,
                    created_by=str(job.get("requested_by") or ""),
                    created_by_source=str(
                        job.get("requested_by_source") or "legacy"
                    ),
                    created_by_verified=bool(job.get("requested_by_verified")),
                )
                run_id = str(run["id"])
                self.database.update_batch_prediction_job(
                    job_id,
                    model_run_id=run_id,
                    model_name=str(result.get("model_name") or ""),
                    prompt_version=str(result.get("prompt_version") or ""),
                    experiment_source=str(result.get("experiment_source") or ""),
                    config_sha256=str(result.get("config_sha256") or ""),
                )

            # Persist the immutable Run before terminal item states.  On a hard
            # restart, Database.init can recover the job/item linkage from the
            # Run metadata instead of leaving successful items without a Run.
            self.database.update_batch_prediction_items(job_id, complete_results)

            status = (
                "succeeded"
                if successful and failed_count == 0
                else "partial"
                if successful
                else "failed"
            )
            error_text = ""
            if status != "succeeded":
                error_text = str(
                    result.get("error")
                    or f"{failed_count} / {len(complete_results)} 个 Issue 推理失败。"
                )
            self.database.update_batch_prediction_job(
                job_id,
                status=status,
                completed_count=len(complete_results),
                success_count=len(successful),
                failed_count=failed_count,
                model_name=str(result.get("model_name") or ""),
                prompt_version=str(result.get("prompt_version") or ""),
                experiment_source=str(result.get("experiment_source") or ""),
                config_sha256=str(result.get("config_sha256") or ""),
                model_run_id=run_id or None,
                summary={
                    "ra_repo_commit": str(result.get("ra_repo_commit") or ""),
                    "trail_view_id": result.get("trail_view_id"),
                    "safe_experiment": result.get("safe_experiment") or {},
                    "model_run_duplicate": duplicate,
                    "ares_bev_input": False,
                    "bag_cache_read_only": False,
                    "bag_cache_scope": "dashboard_isolated",
                    "trail_write_enabled": False,
                },
                error_text=error_text,
                log_path=str(log_path),
            )
        except Exception as exc:
            failure = str(exc)
            current = self.database.get_batch_prediction_job(job_id) or {}
            unfinished = [
                str(item.get("issue_id") or "")
                for item in current.get("items", [])
                if item.get("status") in {"queued", "running"}
            ]
            if unfinished:
                self.database.update_batch_prediction_items(
                    job_id,
                    [
                        {"issue_id": issue_id, "success": False, "error": failure}
                        for issue_id in unfinished
                    ],
                )
            current = self.database.get_batch_prediction_job(job_id) or {}
            success_count = sum(
                1
                for item in current.get("items", [])
                if item.get("status") == "succeeded"
            )
            failed_count = sum(
                1
                for item in current.get("items", [])
                if item.get("status") == "failed"
            )
            self.database.update_batch_prediction_job(
                job_id,
                status="partial" if success_count and run_id else "failed",
                completed_count=success_count + failed_count,
                success_count=success_count,
                failed_count=failed_count,
                model_run_id=run_id or None,
                error_text=failure,
            )

    def _publish(self, job_id: str) -> None:
        job = self.database.get_batch_prediction_job(job_id)
        if job is None:
            return
        results = [
            item.get("result")
            for item in job.get("items", [])
            if item.get("status") == "succeeded"
            and isinstance(item.get("result"), dict)
            and item["result"].get("success")
            and item["result"].get("model_label") in LABELS
        ]
        batch_id = ""
        writer = ""
        try:
            result, events, log_path = self._run_worker(
                job_id=job_id,
                action="publish",
                payload={
                    "action": "publish",
                    "config_sha256": str(job.get("config_sha256") or ""),
                    "results": results,
                    "record_base_url": self.settings.auto_triage_record_base_url,
                },
            )
            for event in events:
                if event.get("event") == "autotriage_batch_created":
                    batch_id = str(event.get("batch_id") or "")
                    writer = str(event.get("writer") or "")
            batch_id = str(result.get("platform_batch_id") or batch_id)
            writer = str(result.get("writer") or writer)
            success = bool(result.get("success"))
            publish_status = (
                "succeeded"
                if success
                else "partial"
                if batch_id
                else "failed"
            )
            summary = dict(job.get("summary") or {})
            summary["autotriage_publish"] = {
                key: value
                for key, value in result.items()
                if key not in {"results"}
            }
            self.database.update_batch_prediction_job(
                job_id,
                publish_status=publish_status,
                autotriage_batch_id=batch_id,
                autotriage_writer=writer,
                summary=summary,
                error_text=""
                if success
                else str(result.get("error") or "AutoTriage 推送未完整完成。"),
                log_path=str(log_path),
            )
        except Exception as exc:
            current = self.database.get_batch_prediction_job(job_id) or {}
            batch_id = str(current.get("autotriage_batch_id") or batch_id)
            writer = str(current.get("autotriage_writer") or writer)
            self.database.update_batch_prediction_job(
                job_id,
                publish_status="partial" if batch_id else "failed",
                autotriage_batch_id=batch_id or None,
                autotriage_writer=writer or None,
                error_text=str(exc),
            )

    def _run_worker(
        self,
        *,
        job_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
        job_dir = self.settings.jobs_dir / "batches" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / f"{action}.log"
        script = self.settings.app_root / "scripts" / "run_batch_worker.sh"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "RA_AUTO_TRIAGE_ROOT": str(self.settings.ra_auto_triage_root),
            "DASHBOARD_PYTHON_BIN": sys.executable,
            "BAG_PATH": str(self.settings.batch_bag_cache_dir),
            "BAG_CACHE_READ_ONLY": "false",
            "RA_TOOLS_ENABLED": "false",
            "http_proxy": "",
            "https_proxy": "",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "no_proxy": "*",
            "NO_PROXY": "*",
        }
        for name in (
            "RA_TOOLS_USERNAME",
            "RA_TOOLS_BASE_URL",
            "MODEL_TRIAGE_API_BASE_URL",
        ):
            value = os.environ.get(name, "").strip()
            if value:
                env[name] = value
        with self._lock:
            if self._shutting_down:
                raise RuntimeError("服务正在停止，未启动 Batch worker。")
            process = subprocess.Popen(
                ["bash", str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=job_dir,
                env=env,
                start_new_session=True,
            )
            self._active_process = process
        if process.stdin is None or process.stdout is None:
            self._kill_process_group(process)
            raise RuntimeError("Batch worker 管道创建失败。")
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        process.stdin.close()

        timed_out = False
        chunks: list[bytes] = []
        pending = b""
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + self.settings.batch_job_timeout_seconds
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._kill_process_group(process)
                    break
                ready = selector.select(timeout=min(0.5, remaining))
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                data = os.read(process.stdout.fileno(), 65536)
                if not data:
                    break
                chunks.append(data)
                pending += data
                while b"\n" in pending:
                    raw_line, pending = pending.split(b"\n", 1)
                    event = self._parse_prefixed_line(
                        raw_line.decode("utf-8", errors="replace"),
                        EVENT_PREFIX,
                    )
                    if event is not None:
                        events.append(event)
                        self._persist_worker_event(job_id, action, event)
        except Exception:
            self._kill_process_group(process)
            process.wait(timeout=5)
            raise
        finally:
            selector.close()
        if timed_out:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process)
                process.wait(timeout=5)
        else:
            process.wait()
        remainder = process.stdout.read()
        if remainder:
            chunks.append(remainder)
            pending += remainder
        if pending:
            event = self._parse_prefixed_line(
                pending.decode("utf-8", errors="replace"),
                EVENT_PREFIX,
            )
            if event is not None:
                events.append(event)
                self._persist_worker_event(job_id, action, event)
        output = b"".join(chunks).decode("utf-8", errors="replace")
        descriptor = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(output)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        result = self._extract_last(output, RESULT_PREFIX)
        timeout_error = (
            f"Batch {action} 超过 "
            f"{self.settings.batch_job_timeout_seconds}s，已终止。"
        )
        if timed_out and action != "publish":
            raise RuntimeError(timeout_error)
        if action == "publish" and not result:
            created = next(
                (
                    event
                    for event in reversed(events)
                    if event.get("event") == "autotriage_batch_created"
                ),
                {},
            )
            if created:
                result = {
                    "success": False,
                    "partial": True,
                    "error": timeout_error
                    if timed_out
                    else f"AutoTriage Batch 已创建，但 worker 未返回最终结果"
                    f"（exit={process.returncode}）；为避免重复建批，不会自动重试。",
                    "platform_batch_id": str(created.get("batch_id") or ""),
                    "writer": str(created.get("writer") or ""),
                }
        if not result:
            raise RuntimeError(
                f"Batch worker 未输出可解析结果（exit={process.returncode}）。"
            )
        return result, events, log_path

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        """Terminate the isolated worker and every multiprocessing child."""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _persist_worker_event(
        self,
        job_id: str,
        action: str,
        event: dict[str, Any],
    ) -> None:
        if action != "publish" or event.get("event") != "autotriage_batch_created":
            return
        batch_id = str(event.get("batch_id") or "").strip()
        if not batch_id:
            raise RuntimeError("AutoTriage 建批事件缺少 Batch ID。")
        current = self.database.get_batch_prediction_job(job_id)
        if current is None:
            raise RuntimeError("AutoTriage 建批后无法读取本地 Batch Job。")
        existing = str(current.get("autotriage_batch_id") or "")
        if existing and existing != batch_id:
            raise RuntimeError(
                f"本地 Batch Job 已关联 AutoTriage {existing}，"
                f"拒绝覆盖为 {batch_id}。"
            )
        self.database.update_batch_prediction_job(
            job_id,
            publish_status="running",
            autotriage_batch_id=batch_id,
            autotriage_writer=str(event.get("writer") or ""),
        )

    @staticmethod
    def _parse_prefixed_line(
        line: str,
        prefix: str,
    ) -> dict[str, Any] | None:
        if not line.startswith(prefix):
            return None
        try:
            value = json.loads(line[len(prefix) :])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _extract_last(output: str, prefix: str) -> dict[str, Any]:
        for line in reversed(output.splitlines()):
            if not line.startswith(prefix):
                continue
            try:
                value = json.loads(line[len(prefix) :])
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                return value
        return {}

    @classmethod
    def _extract_all(cls, output: str, prefix: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for line in output.splitlines():
            if not line.startswith(prefix):
                continue
            try:
                value = json.loads(line[len(prefix) :])
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                values.append(value)
        return values
