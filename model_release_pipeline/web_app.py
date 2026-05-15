"""Dependency-free web console for release records."""

from __future__ import annotations

import json
import mimetypes
import re
import shlex
import subprocess
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from model_release_pipeline.config import PACKAGE_ROOT, ReleaseConfig
from model_release_pipeline.onboard.versioned_onnx import (
    copy_versioned_onnx_to_utils,
    versioned_onnx_info,
)
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web.actions import ACTIONS, action_specs
from model_release_pipeline.web.jobs import JobManager as _JobManager
from model_release_pipeline.web.logs import record_logs
from model_release_pipeline.web.stage_config import (
    STAGE_CONFIG_KEY,
    action_stage_key,
    effective_stage_config,
    read_defaults,
    record_stage_config,
    update_stage_config,
    write_defaults,
)
from model_release_pipeline.web.summary import (
    commands,
    extract_metric_table,
    record_summary,
    timeline,
)


STATIC_DIR = PACKAGE_ROOT / "web_static"
DEFAULT_EXPERIMENT_ROOT = (
    "device:/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/"
    "ego_stuck_data/scenario_dnn_26q1/"
)

# Backward-compatible names used by tests and any local helper scripts.
_ACTIONS = ACTIONS
_record_summary = record_summary
_timeline = timeline
_logs = record_logs


class JobManager(_JobManager):
    """Compatibility wrapper with the historical constructor signature."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__(package_root=PACKAGE_ROOT, config_path=config_path)


def _safe_id(path_value: str, label: str) -> str:
    decoded = unquote(path_value).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", decoded):
        raise ValueError(f"Invalid {label}: {decoded}")
    return decoded


def _safe_run_id(path_value: str) -> str:
    return _safe_id(path_value, "release id")


def _safe_job_id(path_value: str) -> str:
    return _safe_id(path_value, "job id")


def _device_filesystem_path(path_value: str) -> Path:
    match = re.fullmatch(r"[A-Za-z0-9_.-]+:(/.*)", path_value)
    local_path = match.group(1) if match else path_value
    return Path(local_path).expanduser()


def _remote_list_script() -> str:
    return r"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.exists():
    raise FileNotFoundError(f"Experiment root does not exist: {root}")
if not root.is_dir():
    raise NotADirectoryError(f"Experiment root is not a directory: {root}")
folders = [
    {"name": item.name, "path": item.as_posix()}
    for item in root.iterdir()
    if item.is_dir()
]
folders.sort(key=lambda item: item["name"].casefold(), reverse=True)
print(json.dumps(folders, ensure_ascii=False))
"""


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
            "runs": [record_summary(record) for record in records],
        }

    def get_run(self, release_id: str) -> Dict[str, Any]:
        record = self.store.load(release_id)
        return {
            "summary": record_summary(record),
            "timeline": timeline(record),
            "record": record,
            "logs": record_logs(record),
            "commands": commands(record),
            "actions": action_specs(),
            "stage_config": record_stage_config(record),
            "onnx_local_copy": versioned_onnx_info(self.config.runs_dir, record),
            "offboard_metrics": extract_metric_table(
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

    def list_branches(self) -> Dict[str, Any]:
        return {
            "branches": [
                {
                    "name": b.name,
                    "checkout_branch": b.checkout_branch,
                    "update_diff_ids": b.effective_diff_ids(),
                    "sim_plan": b.sim_plan,
                    "sim_plans": [
                        {
                            "name": plan.name,
                            "plan_id": plan.plan_id,
                            "enabled_by_default": plan.enabled_by_default,
                            "priority": plan.priority,
                            "time_sensitive_hour": plan.time_sensitive_hour,
                        }
                        for plan in b.effective_sim_plans()
                    ],
                }
                for b in self.config.voyager.branches
            ]
        }

    def get_stage_defaults(self) -> Dict[str, Any]:
        return {"stage_defaults": read_defaults(self.config.runs_dir)}

    def patch_stage_defaults(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        current = read_defaults(self.config.runs_dir)
        updated = update_stage_config(current, patch)
        return {"stage_defaults": write_defaults(self.config.runs_dir, updated)}

    def get_run_stage_config(self, release_id: str) -> Dict[str, Any]:
        record = self.store.load(release_id)
        return {"stage_config": record_stage_config(record)}

    def patch_run_stage_config(self, release_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        record = self.store.load(release_id)
        updated = update_stage_config(record_stage_config(record), patch)
        record[STAGE_CONFIG_KEY] = updated
        self.store.save(record)
        return {"stage_config": updated}

    def list_experiment_folders(
        self,
        root: str = DEFAULT_EXPERIMENT_ROOT,
        limit: int = 500,
    ) -> Dict[str, Any]:
        root = (root or DEFAULT_EXPERIMENT_ROOT).strip()
        filesystem_root = _device_filesystem_path(root)
        source = "local"
        if filesystem_root.exists():
            if not filesystem_root.is_dir():
                raise NotADirectoryError(f"Experiment root is not a directory: {filesystem_root}")

            folders = []
            for item in filesystem_root.iterdir():
                if not item.is_dir():
                    continue
                folders.append(
                    {
                        "name": item.name,
                        "path": item.as_posix(),
                    }
                )
            folders.sort(key=lambda item: item["name"].casefold(), reverse=True)
        else:
            source = f"remote:{self.config.luban.host_alias}"
            folders = self._list_remote_experiment_folders(filesystem_root)

        if limit > 0:
            folders = folders[:limit]
        return {
            "root": root,
            "filesystem_root": filesystem_root.as_posix(),
            "source": source,
            "folders": folders,
        }

    def _list_remote_experiment_folders(self, filesystem_root: Path) -> list[Dict[str, Any]]:
        remote_python = shlex.split(self.config.luban.remote_python_bin or "python3")
        remote_command = " ".join(
            shlex.quote(part)
            for part in [
                *remote_python,
                "-c",
                _remote_list_script(),
                filesystem_root.as_posix(),
            ]
        )
        command = ["ssh", self.config.luban.host_alias, remote_command]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise FileNotFoundError(
                f"Experiment root does not exist locally and remote listing failed "
                f"on {self.config.luban.host_alias}: {detail}"
            )
        folders = json.loads(result.stdout or "[]")
        if not isinstance(folders, list):
            raise ValueError("Remote experiment folder listing returned invalid data.")
        return folders

    def preview_pick(self, experiment: str, remote: str = "", remote_python: str = "") -> Dict[str, Any]:
        from model_release_pipeline.onboard.export import inspect_and_pick
        experiment_dict, pick_result = inspect_and_pick(
            experiment,
            self.config,
            remote=remote or None,
            remote_python=remote_python or None,
        )
        return {"experiment": experiment_dict, "pick": pick_result}

    def start_action(
        self,
        release_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if ACTIONS.get(action, {}).get("needs_run_id", True):
            record = self.store.load(release_id)
        else:
            record = {}
        payload = dict(payload)
        stage_key = action_stage_key(action)
        if stage_key:
            merged = effective_stage_config(
                stage_key,
                read_defaults(self.config.runs_dir),
                record_stage_config(record),
                payload,
            )
            payload.update(merged)
        return self.jobs.start(
            release_id=release_id,
            action=action,
            dry_run=bool(payload.get("dry_run", True)),
            confirm_text=str(payload.get("confirm_text") or ""),
            payload=payload,
        )

    def copy_versioned_onnx(self, release_id: str) -> Dict[str, Any]:
        record = self.store.load(release_id)
        result = copy_versioned_onnx_to_utils(self.config.runs_dir, record)
        record["ifx"] = {
            **record.get("ifx", {}),
            "local_onnx_copy": result,
        }
        self.store.save(record)
        return result


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    data = text.encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _static_response(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        _text_response(handler, "Not found", HTTPStatus.NOT_FOUND)
        return
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _handle_api_get(
    handler: BaseHTTPRequestHandler,
    app: ReleaseWebApp,
    path: str,
    query: str = "",
) -> bool:
    if path == "/api/config/branches":
        _json_response(handler, app.list_branches())
        return True
    if path == "/api/config/stage-defaults":
        _json_response(handler, app.get_stage_defaults())
        return True
    if path == "/api/experiment-folders":
        params = parse_qs(query)
        root = (params.get("root") or [DEFAULT_EXPERIMENT_ROOT])[0]
        limit_raw = (params.get("limit") or ["500"])[0]
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 500
        _json_response(handler, app.list_experiment_folders(root=root, limit=limit))
        return True
    if path == "/api/pick":
        params = parse_qs(query)
        experiment = (params.get("experiment") or [""])[0]
        remote = (params.get("remote") or [""])[0]
        remote_python = (params.get("remote_python") or [""])[0]
        if not experiment:
            _json_response(handler, {"error": "experiment is required"}, status=HTTPStatus.BAD_REQUEST)
            return True
        _json_response(handler, app.preview_pick(experiment, remote, remote_python))
        return True
    if path == "/api/runs":
        _json_response(handler, app.list_runs())
        return True
    if path == "/api/jobs":
        _json_response(handler, app.jobs.list())
        return True
    if path.startswith("/api/jobs/"):
        job_id = _safe_job_id(path.removeprefix("/api/jobs/"))
        _json_response(handler, app.jobs.get(job_id))
        return True
    if path.startswith("/api/runs/"):
        suffix = path.removeprefix("/api/runs/")
        parts = suffix.split("/")
        release_id = _safe_run_id(parts[0])
        if len(parts) == 1:
            _json_response(handler, app.get_run(release_id))
            return True
        if len(parts) == 2 and parts[1] == "stage-config":
            _json_response(handler, app.get_run_stage_config(release_id))
            return True
        if len(parts) == 3 and parts[1] == "files":
            content, content_type = app.read_run_file(
                release_id, _safe_run_id(parts[2])
            )
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(content)))
            handler.end_headers()
            handler.wfile.write(content)
            return True
    return False


def _handle_api_patch(
    handler: BaseHTTPRequestHandler,
    app: ReleaseWebApp,
    path: str,
    payload: Dict[str, Any],
) -> bool:
    if path == "/api/config/stage-defaults":
        _json_response(handler, app.patch_stage_defaults(payload))
        return True
    if path.startswith("/api/runs/"):
        suffix = path.removeprefix("/api/runs/")
        parts = suffix.split("/")
        release_id = _safe_run_id(parts[0])
        if len(parts) == 2 and parts[1] == "stage-config":
            _json_response(handler, app.patch_run_stage_config(release_id, payload))
            return True
    return False


def _handle_static_get(handler: BaseHTTPRequestHandler, path: str) -> None:
    if path in {"", "/"}:
        _static_response(handler, STATIC_DIR / "index.html")
        return
    if path == "/favicon.ico":
        _static_response(handler, STATIC_DIR / "favicon.svg")
        return
    static_path = (STATIC_DIR / path.removeprefix("/")).resolve()
    if STATIC_DIR.resolve() in static_path.parents:
        _static_response(handler, static_path)
        return
    _text_response(handler, "Not found", HTTPStatus.NOT_FOUND)


def _make_handler(app: ReleaseWebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if _handle_api_get(self, app, parsed.path, parsed.query):
                    return
                _handle_static_get(self, parsed.path)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except FileNotFoundError as exc:
                _json_response(self, {"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
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
                    if len(parts) == 2 and parts[1] == "copy-versioned-onnx":
                        release_id = _safe_run_id(parts[0])
                        _json_response(
                            self,
                            app.copy_versioned_onnx(release_id),
                            status=HTTPStatus.OK,
                        )
                        return
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
            except (BrokenPipeError, ConnectionResetError):
                pass
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

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                content_length = int(self.headers.get("Content-Length") or "0")
                raw_body = self.rfile.read(content_length) if content_length else b"{}"
                payload = json.loads(raw_body.decode("utf-8") or "{}")
                if _handle_api_patch(self, app, parsed.path, payload):
                    return
                _text_response(self, "Not found", HTTPStatus.NOT_FOUND)
            except (BrokenPipeError, ConnectionResetError):
                pass
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
