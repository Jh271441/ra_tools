"""Small web console for release records.

The server is intentionally dependency-free so it can run from the same
`assist_stuck` shell as the CLI. Mutating actions are still routed through the
same CLI commands and require an explicit release-id confirmation from the UI.
"""

from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from model_release_pipeline.config import PACKAGE_ROOT, ReleaseConfig
from model_release_pipeline.state_store import StateStore


STATIC_DIR = PACKAGE_ROOT / "web_static"


_ACTIONS = {
    "export": {
        "command": "export",
        "label": "Model Export",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": False,
    },
    "handoff": {
        "command": "handoff",
        "label": "Generate Handoff",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": True,
    },
    "ifx-convert": {
        "command": "ifx-convert",
        "label": "Trigger IFX Convert",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "apply-handoff": {
        "command": "apply-handoff",
        "label": "Apply Handoff",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "offboard": {
        "command": "offboard",
        "label": "Run Offboard",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": ["--remote", "luban_2_card"],
        "needs_run_id": True,
    },
}


_PIPELINE_STEPS = [
    ("inspect", "Inspect", "Inspect experiment metadata and checkpoints"),
    ("pick", "Pick", "Recommend epoch from log/TensorBoard metrics"),
    ("export", "Export", "Export and copy ONNX from Luban"),
    ("upload", "Upload", "Upload ONNX with truck.py"),
    ("ifx", "IFX Convert", "Trigger Jenkins and collect IFX versions"),
    ("handoff", "Handoff", "Generate or apply Voyager MANIFEST updates"),
    ("dcl", "DCL", "Update review diffs manually"),
    ("offboard", "Offboard", "Run release checkpoint validation"),
]


def _command_state(result: Optional[Dict[str, Any]]) -> str:
    if not result:
        return "missing"
    returncode = result.get("returncode")
    stderr = str(result.get("stderr") or "")
    if returncode == 0:
        return "done"
    if returncode is None and stderr.startswith("Skipped"):
        return "skipped"
    if returncode is None:
        return "dry_run"
    return "failed"


def _step_status(record: Dict[str, Any], key: str) -> str:
    stage = str(record.get("stage") or "")
    status = str(record.get("status") or "")
    if status == "failed" and key in stage:
        return "failed"
    if key == "inspect":
        return "done" if record.get("experiment") else "pending"
    if key == "pick":
        selection = record.get("selection") or {}
        return "done" if selection.get("selected_epoch") is not None else "pending"
    if key == "export":
        export = record.get("export") or {}
        if not export:
            return "pending"
        if stage == "export_failed":
            return "failed"
        export_state = _command_state(export.get("export"))
        scp_state = _command_state(export.get("scp"))
        if "failed" in {export_state, scp_state}:
            return "failed"
        if export_state in {"done", "skipped", "dry_run"} and scp_state in {
            "done",
            "dry_run",
        }:
            return "done" if status != "dry_run" else "dry_run"
        return "running" if key in stage else "pending"
    if key == "upload":
        ifx = record.get("ifx") or {}
        if not ifx.get("onnx"):
            return "running" if stage == "ifx_uploading" else "pending"
        return "dry_run" if stage == "ifx_upload_dry_run" else "done"
    if key == "ifx":
        ifx = record.get("ifx") or {}
        if stage == "ifx_converting":
            return "running"
        if status == "failed" and stage.startswith("ifx"):
            return "failed"
        if ifx.get("ifx_mapping"):
            return "dry_run" if stage == "ifx_convert_dry_run" else "done"
        return "pending"
    if key == "handoff":
        if record.get("apply_handoff"):
            return _command_state(record.get("apply_handoff"))
        if record.get("handoff"):
            return "done"
        return "pending"
    if key == "dcl":
        apply_handoff = record.get("apply_handoff") or {}
        return "ready" if apply_handoff.get("dcl_commands") else "pending"
    if key == "offboard":
        offboard = record.get("offboard") or {}
        if not offboard:
            return "pending"
        if stage == "offboard_failed":
            return "failed"
        return _command_state(offboard)
    return "pending"


def _record_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    experiment = record.get("experiment") or {}
    selection = record.get("selection") or {}
    ifx = record.get("ifx") or {}
    mapping = ifx.get("ifx_mapping") or {}
    errors = record.get("errors") or []
    return {
        "release_id": record.get("release_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "stage": record.get("stage"),
        "status": record.get("status"),
        "experiment_name": experiment.get("name") or Path(str(record.get("experiment_path") or "")).name,
        "experiment_path": record.get("experiment_path"),
        "selected_epoch": selection.get("selected_epoch"),
        "selection_source": selection.get("selection_source"),
        "onnx_version": (ifx.get("onnx") or mapping.get("onnx") or {}).get("version"),
        "ifx_platforms": len([key for key in mapping if key != "onnx"]),
        "offboard_status": _step_status(record, "offboard"),
        "error_count": len(errors),
    }


def _timeline(record: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        {
            "key": key,
            "title": title,
            "description": description,
            "status": _step_status(record, key),
        }
        for key, title, description in _PIPELINE_STEPS
    ]


def _extract_metric_table(stdout: str) -> list[str]:
    lines = stdout.splitlines()
    keep: list[str] = []
    capture = False
    for line in lines:
        if "Validation Metrics" in line or "Saved metric analysis" in line:
            capture = True
        if capture:
            keep.append(line)
            if line.startswith("+------------") and len(keep) > 3:
                break
    return keep[-12:]


def _tail(value: Any, max_lines: int = 80) -> list[str]:
    lines = str(value or "").splitlines()
    return lines[-max_lines:]


def _logs(record: Dict[str, Any]) -> Dict[str, list[str]]:
    export = record.get("export") or {}
    ifx = record.get("ifx") or {}
    jenkins = ifx.get("jenkins") or {}
    apply_handoff = record.get("apply_handoff") or {}
    offboard = record.get("offboard") or {}
    return {
        "export_stdout": _tail((export.get("export") or {}).get("stdout")),
        "export_stderr": _tail((export.get("export") or {}).get("stderr")),
        "jenkins_console": jenkins.get("console_tail") or [],
        "handoff_stdout": _tail(apply_handoff.get("stdout")),
        "handoff_stderr": _tail(apply_handoff.get("stderr")),
        "offboard_stdout": _tail(offboard.get("stdout"), 120),
        "offboard_stderr": _tail(offboard.get("stderr"), 80),
    }


def _commands(record: Dict[str, Any]) -> Dict[str, Any]:
    release_id = record.get("release_id")
    experiment_path = record.get("experiment_path") or "<experiment_path>"
    selected_epoch = (record.get("selection") or {}).get("selected_epoch")
    epoch_arg = f"--epoch {int(selected_epoch):03d}" if selected_epoch is not None else "--epoch <epoch>"
    return {
        "export": (
            "python3 -m model_release_pipeline.cli export "
            f"--remote luban_2_card --experiment {experiment_path!r} {epoch_arg}"
        ),
        "upload": (
            "python3 -m model_release_pipeline.cli upload "
            f"--run-id {release_id} --onnx-version <version> --desc '<desc>'"
        ),
        "ifx_convert": f"python3 -m model_release_pipeline.cli ifx-convert --run-id {release_id}",
        "apply_handoff": f"python3 -m model_release_pipeline.cli apply-handoff --run-id {release_id}",
        "offboard": f"python3 -m model_release_pipeline.cli offboard --run-id {release_id} --remote luban_2_card",
        "dcl": (record.get("apply_handoff") or {}).get("dcl_commands") or [],
    }


def _safe_run_id(path_value: str) -> str:
    decoded = unquote(path_value).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", decoded):
        raise ValueError(f"Invalid release id: {decoded}")
    return decoded


def _safe_job_id(path_value: str) -> str:
    decoded = unquote(path_value).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", decoded):
        raise ValueError(f"Invalid job id: {decoded}")
    return decoded


class JobManager:
    """Runs CLI actions in background threads and keeps recent logs."""

    def __init__(self, config_path: Optional[str] = None) -> None:
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
        if action not in _ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        spec = _ACTIONS[action]
        if dry_run and not spec["supports_dry_run"]:
            raise ValueError(f"Action {action} does not support dry_run.")
        command = [sys.executable, "-m", "model_release_pipeline.cli"]
        if self.config_path:
            command.extend(["--config", self.config_path])
        command.append(spec["command"])
        payload = payload or {}
        if spec.get("needs_run_id", True):
            command.extend(["--run-id", release_id])
        if action == "export":
            experiment = str(payload.get("experiment") or "").strip()
            if not experiment:
                raise ValueError("Model export requires experiment.")
            command.extend(["--experiment", experiment])
            remote = str(payload.get("remote") or "").strip()
            if remote:
                command.extend(["--remote", remote])
            remote_python = str(payload.get("remote_python") or "").strip()
            if remote_python:
                command.extend(["--remote-python", remote_python])
            epoch = str(payload.get("epoch") or "").strip()
            if epoch:
                if not epoch.isdigit():
                    raise ValueError("epoch must be an integer.")
                command.extend(["--epoch", str(int(epoch))])
            task = str(payload.get("task") or "").strip()
            if task:
                command.extend(["--task", task])
            desc = str(payload.get("desc") or "").strip()
            if desc:
                command.extend(["--desc", desc])
        else:
            command.extend(spec["extra_args"])
        command.append("--yes")
        if dry_run:
            command.append("--dry-run")
        return command

    def start(
        self,
        release_id: str,
        action: str,
        dry_run: bool,
        confirm_text: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if action not in _ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        spec = _ACTIONS[action]
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
                cwd=str(PACKAGE_ROOT.parent),
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


class ReleaseWebApp:
    """HTTP adapter around StateStore records."""

    def __init__(self, config: ReleaseConfig, config_path: Optional[str] = None) -> None:
        self.config = config
        self.store = StateStore(config.runs_dir)
        self.jobs = JobManager(config_path=config_path)

    def list_runs(self) -> Dict[str, Any]:
        records = self.store.list_records()
        return {
            "runs_dir": str(self.config.runs_dir),
            "runs": [_record_summary(record) for record in records],
        }

    def get_run(self, release_id: str) -> Dict[str, Any]:
        record = self.store.load(release_id)
        return {
            "summary": _record_summary(record),
            "timeline": _timeline(record),
            "record": record,
            "logs": _logs(record),
            "commands": _commands(record),
            "actions": _action_specs(),
            "offboard_metrics": _extract_metric_table(
                str((record.get("offboard") or {}).get("stdout") or "")
            ),
        }

    def read_run_file(self, release_id: str, name: str) -> tuple[bytes, str]:
        allowed = {
            "record": "release_record.json",
            "handoff": "handoff_manifest_snippet.txt",
            "commands": "handoff_commands.sh",
            "summary": "handoff_summary.txt",
        }
        if name not in allowed:
            raise FileNotFoundError(name)
        path = self.store.run_dir(release_id) / allowed[name]
        return path.read_bytes(), "text/plain; charset=utf-8"

    def start_action(
        self,
        release_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.store.load(release_id)
        return self.jobs.start(
            release_id=release_id,
            action=action,
            dry_run=bool(payload.get("dry_run", True)),
            confirm_text=str(payload.get("confirm_text") or ""),
            payload=payload,
        )


def _action_specs() -> list[Dict[str, Any]]:
    return [
        {
            "key": key,
            "label": spec["label"],
            "supports_dry_run": spec["supports_dry_run"],
            "requires_confirm": spec["requires_confirm"],
            "needs_run_id": spec.get("needs_run_id", True),
        }
        for key, spec in _ACTIONS.items()
    ]


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _static_response(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        _text_response(handler, "Not found", HTTPStatus.NOT_FOUND)
        return
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _make_handler(app: ReleaseWebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/runs":
                    _json_response(self, app.list_runs())
                    return
                if parsed.path == "/api/jobs":
                    _json_response(self, app.jobs.list())
                    return
                if parsed.path.startswith("/api/jobs/"):
                    job_id = _safe_job_id(parsed.path.removeprefix("/api/jobs/"))
                    _json_response(self, app.jobs.get(job_id))
                    return
                if parsed.path.startswith("/api/runs/"):
                    suffix = parsed.path.removeprefix("/api/runs/")
                    parts = suffix.split("/")
                    release_id = _safe_run_id(parts[0])
                    if len(parts) == 1:
                        _json_response(self, app.get_run(release_id))
                        return
                    if len(parts) == 3 and parts[1] == "files":
                        content, content_type = app.read_run_file(
                            release_id, _safe_run_id(parts[2])
                        )
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return
                if parsed.path in {"", "/"}:
                    _static_response(self, STATIC_DIR / "index.html")
                    return
                static_path = (STATIC_DIR / parsed.path.removeprefix("/")).resolve()
                if STATIC_DIR.resolve() in static_path.parents:
                    _static_response(self, static_path)
                    return
                _text_response(self, "Not found", HTTPStatus.NOT_FOUND)
            except FileNotFoundError as exc:
                _json_response(
                    self,
                    {"error": str(exc)},
                    status=HTTPStatus.NOT_FOUND,
                )
            except Exception as exc:  # pylint: disable=broad-except
                _json_response(
                    self,
                    {"error": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                content_length = int(self.headers.get("Content-Length") or "0")
                raw_body = self.rfile.read(content_length) if content_length else b"{}"
                payload = json.loads(raw_body.decode("utf-8") or "{}")
                if parsed.path.startswith("/api/runs/"):
                    suffix = parsed.path.removeprefix("/api/runs/")
                    parts = suffix.split("/")
                    if len(parts) == 3 and parts[1] == "actions":
                        release_id = _safe_run_id(parts[0])
                        action = _safe_run_id(parts[2])
                        _json_response(
                            self,
                            app.start_action(release_id, action, payload),
                            status=HTTPStatus.ACCEPTED,
                        )
                        return
                _text_response(self, "Not found", HTTPStatus.NOT_FOUND)
            except PermissionError as exc:
                _json_response(self, {"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            except FileNotFoundError as exc:
                _json_response(self, {"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:  # pylint: disable=broad-except
                _json_response(
                    self,
                    {"error": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

    return Handler


def serve(
    config: ReleaseConfig,
    host: str,
    port: int,
    open_browser: bool = False,
    config_path: Optional[str] = None,
) -> None:
    app = ReleaseWebApp(config, config_path=config_path)
    server = ThreadingHTTPServer((host, port), _make_handler(app))
    url = f"http://{host}:{port}"
    print(f"Release Agent Console: {url}")
    print(f"runs_dir: {config.runs_dir}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Release Agent Console.")
