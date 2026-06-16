"""State persistence for model release runs."""

from __future__ import annotations

import json
import fcntl
import hashlib
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


class StateStore:
    """Persists release state under the configured runs directory."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = Path(runs_dir).expanduser()
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create(self, experiment_path: Optional[str], description: str) -> Dict[str, Any]:
        release_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        record = {
            "release_id": release_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "created",
            "stage": "created",
            "description": description,
            "experiment_path": experiment_path,
            "metadata": {},
            "selection": {},
            "export": {},
            "ifx": {},
            "handoff": {},
            "offboard": {},
            "errors": [],
        }
        self.save(record)
        return record

    @contextmanager
    def run_lock(self, release_id: str) -> Iterator[None]:
        """Hold an inter-process lock for one release record mutation."""
        locks_dir = self.runs_dir / ".locks"
        locks_dir.mkdir(parents=True, exist_ok=True)
        lock_name = hashlib.sha256(str(release_id).encode("utf-8")).hexdigest()
        lock_path = locks_dir / f"{lock_name}.lock"
        with lock_path.open("w", encoding="utf-8") as lock_file:
            lock_file.write(str(release_id))
            lock_file.flush()
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    f"Release {release_id} already has a running action."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def run_dir(self, release_id: str) -> Path:
        path = self.runs_dir / release_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "artifacts").mkdir(parents=True, exist_ok=True)
        return path

    def record_path(self, release_id: str) -> Path:
        return self.run_dir(release_id) / "release_record.json"

    def save(self, record: Dict[str, Any]) -> Path:
        record = deepcopy(record)
        record["updated_at"] = datetime.now().isoformat()
        path = self.record_path(record["release_id"])
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load(self, release_id: str) -> Dict[str, Any]:
        path = self.record_path(release_id)
        if not path.exists():
            raise FileNotFoundError(f"Release record not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_records(self) -> list[Dict[str, Any]]:
        records = []
        if not self.runs_dir.exists():
            return records
        for item in sorted(self.runs_dir.iterdir(), reverse=True):
            if not item.is_dir():
                continue
            record_path = item / "release_record.json"
            if not record_path.exists():
                continue
            try:
                records.append(json.loads(record_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                records.append(
                    {
                        "release_id": item.name,
                        "stage": "corrupt_record",
                        "status": "failed",
                        "errors": [
                            {
                                "message": f"Failed to parse {record_path}",
                            }
                        ],
                    }
                )
        return sorted(
            records,
            key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""),
            reverse=True,
        )

    def update(self, record: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
        for key, value in fields.items():
            record[key] = value
        self.save(record)
        return record

    def add_error(self, record: Dict[str, Any], message: str) -> Dict[str, Any]:
        errors = list(record.get("errors", []))
        errors.append({"time": datetime.now().isoformat(), "message": message})
        record["errors"] = errors
        record["status"] = "failed"
        self.save(record)
        return record
