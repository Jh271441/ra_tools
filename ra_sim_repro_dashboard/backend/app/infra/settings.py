"""Unified Pydantic Settings configuration center for RA Sim Repro Dashboard."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
DEFAULT_REPORT_DIR = ROOT_DIR.parent / "reports"

load_dotenv(ROOT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

EVALUATION_POLL_SECONDS = 30


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database_url: str = Field(
        default=f"sqlite:///{(DATA_DIR / 'dev.db').as_posix()}",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    enable_rq: bool = Field(default=False, alias="ENABLE_RQ")
    cache_ttl_seconds: int = Field(default=600, alias="CACHE_TTL_SECONDS")
    versions_config: Path = Field(
        default=CONFIG_DIR / "versions.yaml",
        alias="VERSIONS_CONFIG",
    )
    mock_data_dir: Path = Field(default=DATA_DIR / "mock", alias="MOCK_DATA_DIR")
    disable_mock_data: bool = Field(default=False, alias="DISABLE_MOCK_DATA")
    report_dir: Path = Field(default=DEFAULT_REPORT_DIR, alias="REPORT_DIR")
    ssl_verify: str = Field(default="true", alias="SIM_SSL_VERIFY")
    ca_bundle: str = Field(default="", alias="SIM_CA_BUNDLE")

    trail_base_url: str = Field(
        default="http://100.69.238.11:8000/voyager/trail",
        alias="TRAIL_BASE_URL",
    )
    trail_app_id: str = Field(default="", alias="TRAIL_APP_ID")
    trail_app_token: str = Field(default="", alias="TRAIL_APP_TOKEN")

    voyager_result_base_url: str = Field(
        default="https://voyager.intra.xiaojukeji.com",
        alias="VOYAGER_RESULT_BASE_URL",
    )
    voyager_cookie: str = Field(default="", alias="VOYAGER_COOKIE")
    voyager_query_page_size: int = Field(default=1000, alias="VOYAGER_QUERY_PAGE_SIZE")
    voyager_timeout_seconds: float = Field(default=60.0, alias="VOYAGER_TIMEOUT_SECONDS")

    scenario_base_url: str = Field(
        default="http://100.69.238.11:8000/voyager/trail",
        alias="SCENARIO_BASE_URL",
    )
    scenario_app_id: str = Field(default="", alias="SCENARIO_APP_ID")
    scenario_app_token: str = Field(default="", alias="SCENARIO_APP_TOKEN")
    scenario_query_page_size: int = Field(default=500, alias="SCENARIO_QUERY_PAGE_SIZE")

    issue_base_url: str = Field(
        default="http://voyager.intra.xiaojukeji.com/paladin/issue/pool",
        alias="ISSUE_BASE_URL",
    )
    issue_app_id: str = Field(default="", alias="ISSUE_APP_ID")
    issue_app_token: str = Field(default="", alias="ISSUE_APP_TOKEN")


def _load_settings() -> AppSettings:
    s = AppSettings()
    if not s.scenario_app_id and s.trail_app_id:
        s.scenario_app_id = s.trail_app_id
    if not s.scenario_app_token and s.trail_app_token:
        s.scenario_app_token = s.trail_app_token
    if not s.scenario_base_url and s.trail_base_url:
        s.scenario_base_url = s.trail_base_url
    return s


settings = _load_settings()


def evaluation_worker_enabled() -> bool:
    return os.getenv("EVALUATION_WORKER_ENABLED", "1") == "1"


def evaluation_scheduling_enabled() -> bool:
    return evaluation_worker_enabled() and os.getenv("EVALUATION_CRON_ENABLED") == "1"


def mock_data_disabled() -> bool:
    raw = os.getenv("DISABLE_MOCK_DATA", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return settings.disable_mock_data


def ssl_verify_setting() -> bool | str:
    ca_bundle = os.getenv("SIM_CA_BUNDLE", settings.ca_bundle).strip()
    if ca_bundle:
        return ca_bundle
    raw = os.getenv("SIM_SSL_VERIFY", settings.ssl_verify).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


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
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


@lru_cache(maxsize=4)
def load_shuyi_report_config(path: str | None = None) -> dict[str, Any]:
    target = Path(
        path or os.getenv("SIM_SHUYI_REPORT_CONFIG", str(CONFIG_DIR / "shuyi-report.json"))
    )
    raw = json.loads(target.read_text(encoding="utf-8"))
    return {
        "report_id": int(raw["report_id"]),
        "slice_id": int(raw["slice_id"]),
        "review_slice_id": int(raw["review_slice_id"]),
        "source": str(raw["source"]),
        "project_id": int(raw["project_id"]),
        "endpoint": str(raw["endpoint"]),
        "fields": {k: tuple(v) for k, v in raw["fields"].items()},
        "review_fields": {k: tuple(v) for k, v in raw["review_fields"].items()},
        "raw_fields": {k: tuple(v) for k, v in raw["raw_fields"].items()},
    }
