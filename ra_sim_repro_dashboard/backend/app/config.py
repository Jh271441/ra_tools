from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
DEFAULT_REPORT_DIR = ROOT_DIR.parent / "reports"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(DATA_DIR / 'dev.db').as_posix()}",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    enable_rq: bool = os.getenv("ENABLE_RQ", "0") == "1"
    versions_config: Path = Path(
        os.getenv("VERSIONS_CONFIG", str(CONFIG_DIR / "versions.yaml"))
    )
    mock_data_dir: Path = Path(os.getenv("MOCK_DATA_DIR", str(DATA_DIR / "mock")))
    report_dir: Path = Path(os.getenv("REPORT_DIR", str(DEFAULT_REPORT_DIR)))
    trail_base_url: str = os.getenv("TRAIL_BASE_URL", "http://100.69.238.11:8000/voyager/trail")
    trail_app_id: str = os.getenv("TRAIL_APP_ID", "")
    trail_app_token: str = os.getenv("TRAIL_APP_TOKEN", "")
    voyager_result_base_url: str = os.getenv(
        "VOYAGER_RESULT_BASE_URL",
        "https://voyager.intra.xiaojukeji.com",
    )
    voyager_cookie: str = os.getenv("VOYAGER_COOKIE", "")
    voyager_query_page_size: int = int(os.getenv("VOYAGER_QUERY_PAGE_SIZE", "1000"))
    voyager_timeout_seconds: float = float(os.getenv("VOYAGER_TIMEOUT_SECONDS", "60"))
    scenario_base_url: str = os.getenv(
        "SCENARIO_BASE_URL",
        os.getenv("TRAIL_BASE_URL", "http://100.69.238.11:8000/voyager/trail"),
    ) or os.getenv("TRAIL_BASE_URL", "http://100.69.238.11:8000/voyager/trail")
    scenario_app_id: str = os.getenv("SCENARIO_APP_ID") or os.getenv("TRAIL_APP_ID", "")
    scenario_app_token: str = os.getenv("SCENARIO_APP_TOKEN") or os.getenv("TRAIL_APP_TOKEN", "")
    scenario_query_page_size: int = int(os.getenv("SCENARIO_QUERY_PAGE_SIZE", "500"))
    issue_base_url: str = os.getenv(
        "ISSUE_BASE_URL",
        "http://voyager.intra.xiaojukeji.com/paladin/issue/pool",
    )
    issue_app_id: str = os.getenv("ISSUE_APP_ID", "")
    issue_app_token: str = os.getenv("ISSUE_APP_TOKEN", "")
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "600"))


settings = Settings()


def load_versions_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or settings.versions_config
    if not config_path.exists():
        fallback = CONFIG_DIR / "versions.example.yaml"
        if fallback.exists():
            config_path = fallback
        else:
            return {"current_version": "", "compare_versions": [], "versions": {}}
    with config_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    payload.setdefault("compare_versions", [])
    payload.setdefault("versions", {})
    return payload


def config_hash(payload: dict[str, Any] | None = None) -> str:
    data = payload if payload is not None else load_versions_config()
    text = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
