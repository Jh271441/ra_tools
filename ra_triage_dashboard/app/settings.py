from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_root: Path
    build_commit: str
    static_dir: Path
    data_dir: Path
    database_url: str
    ra_auto_triage_root: Path
    ares_manifest: Path
    camera_root: Path
    baseline_label_xlsx: Path
    baseline_dataset: str
    baseline_scope: str
    bootstrap_model_json: Path | None
    trail_view_id: int
    trail_sync_on_start: bool
    trail_sync_chunk_size: int
    voyager_issue_base_url: str
    voyager_issue_view_id: int
    batch_prediction_enabled: bool
    autotriage_push_enabled: bool
    batch_max_issues: int
    batch_job_timeout_seconds: int
    batch_bag_cache_dir: Path
    ra_model_catalog_url: str
    ra_model_chat_url: str
    ra_model_tokenservice_catalog_url: str
    ra_model_tokenservice_chat_url: str
    ra_model_default_id: str
    ra_model_catalog_ttl_seconds: int
    ra_model_profile_path: Path
    ra_model_api_key_file: Path
    ra_model_tokenservice_api_key_file: Path
    auto_triage_record_base_url: str
    autotriage_api_base_url: str
    allowed_model_hosts: tuple[str, ...]
    job_timeout_seconds: int
    trust_proxy_identity_headers: bool
    identity_header: str
    team_default_managers: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        app_root = Path(__file__).resolve().parents[1]
        data_dir = _path("DASHBOARD_DATA_DIR", app_root / ".data")
        ra_root = _path(
            "RA_AUTO_TRIAGE_ROOT",
            Path("/volume/home/workspace/ra_auto_triage"),
        )
        manifest = _path(
            "ARES_CAPTURE_MANIFEST",
            ra_root / "bags/ares_capture_bev/manifest.jsonl",
        )
        camera_root = _path("CAMERA_CACHE_ROOT", ra_root / "bags/camera")
        baseline_xlsx = _path(
            "DASHBOARD_BASELINE_LABEL_XLSX",
            ra_root / "data/trail_label_baseline_20260729.xlsx",
        )
        bootstrap_value = os.getenv("DASHBOARD_BOOTSTRAP_MODEL_JSON", "").strip()
        bootstrap = Path(bootstrap_value).expanduser().resolve() if bootstrap_value else None
        extra_hosts = tuple(
            host.strip().lower()
            for host in os.getenv("DASHBOARD_ALLOWED_MODEL_HOSTS", "").split(",")
            if host.strip()
        )
        team_default_managers = tuple(
            username.strip()
            for username in os.getenv("DASHBOARD_TEAM_DEFAULT_MANAGERS", "").split(",")
            if username.strip()
        )
        return cls(
            app_root=app_root,
            build_commit=(
                os.getenv("DASHBOARD_BUILD_COMMIT", "").strip()[:64]
                or "unverified"
            ),
            static_dir=app_root / "static",
            data_dir=data_dir,
            database_url=os.getenv(
                "DASHBOARD_DATABASE_URL",
                f"sqlite:///{data_dir / 'triage.sqlite3'}",
            ),
            ra_auto_triage_root=ra_root,
            ares_manifest=manifest,
            camera_root=camera_root,
            baseline_label_xlsx=baseline_xlsx,
            baseline_dataset=os.getenv("DASHBOARD_BASELINE_DATASET", "0508").strip() or "0508",
            baseline_scope=os.getenv(
                "DASHBOARD_BASELINE_SCOPE", "release0508_1071_20260729"
            ).strip()
            or "release0508_1071_20260729",
            bootstrap_model_json=bootstrap,
            trail_view_id=_integer("DASHBOARD_TRAIL_VIEW_ID", 2410),
            trail_sync_on_start=_bool("DASHBOARD_SYNC_TRAIL_ON_START", True),
            trail_sync_chunk_size=_integer("DASHBOARD_TRAIL_SYNC_CHUNK_SIZE", 160, 1),
            voyager_issue_base_url=os.getenv(
                "DASHBOARD_VOYAGER_ISSUE_BASE_URL",
                "https://voyager.intra.xiaojukeji.com/static/management/#/issue",
            ).strip()
            or "https://voyager.intra.xiaojukeji.com/static/management/#/issue",
            voyager_issue_view_id=_integer("DASHBOARD_VOYAGER_ISSUE_VIEW_ID", 2410),
            batch_prediction_enabled=_bool(
                "DASHBOARD_BATCH_PREDICTION_ENABLED", False
            ),
            autotriage_push_enabled=_bool(
                "DASHBOARD_AUTOTRIAGE_PUSH_ENABLED", False
            ),
            batch_max_issues=min(
                50, _integer("DASHBOARD_BATCH_MAX_ISSUES", 50, 1)
            ),
            batch_job_timeout_seconds=_integer(
                "DASHBOARD_BATCH_JOB_TIMEOUT_SECONDS", 7200, 60
            ),
            batch_bag_cache_dir=_path(
                "DASHBOARD_BATCH_BAG_CACHE_DIR",
                data_dir / "batch_bags",
            ),
            ra_model_catalog_url=os.getenv(
                "DASHBOARD_RA_MODEL_CATALOG_URL",
                "http://ra-model.intra.xiaojukeji.com/v1/models",
            ).strip()
            or "http://ra-model.intra.xiaojukeji.com/v1/models",
            ra_model_chat_url=os.getenv(
                "DASHBOARD_RA_MODEL_CHAT_URL",
                "http://ra-model.intra.xiaojukeji.com/v1/chat/completions",
            ).strip()
            or "http://ra-model.intra.xiaojukeji.com/v1/chat/completions",
            ra_model_tokenservice_catalog_url=os.getenv(
                "DASHBOARD_RA_MODEL_TOKENSERVICE_CATALOG_URL",
                "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/models",
            ).strip()
            or "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/models",
            ra_model_tokenservice_chat_url=os.getenv(
                "DASHBOARD_RA_MODEL_TOKENSERVICE_CHAT_URL",
                "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/chat/completions",
            ).strip()
            or "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/chat/completions",
            ra_model_default_id=os.getenv(
                "DASHBOARD_RA_MODEL_DEFAULT_ID", "auto"
            ).strip()
            or "auto",
            ra_model_catalog_ttl_seconds=_integer(
                "DASHBOARD_RA_MODEL_CATALOG_TTL_SECONDS", 300, 30
            ),
            ra_model_profile_path=_path(
                "DASHBOARD_RA_MODEL_PROFILE_PATH",
                app_root / "config" / "model_profiles.json",
            ),
            ra_model_api_key_file=_path(
                "DASHBOARD_RA_MODEL_API_KEY_FILE",
                data_dir / "model_gateway_api_key",
            ),
            ra_model_tokenservice_api_key_file=_path(
                "DASHBOARD_RA_MODEL_TOKENSERVICE_API_KEY_FILE",
                data_dir / "tokenservice_api_key",
            ),
            auto_triage_record_base_url=os.getenv(
                "DASHBOARD_AUTO_TRIAGE_RECORD_BASE_URL",
                "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records",
            ).strip()
            or "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records",
            autotriage_api_base_url=os.getenv(
                "DASHBOARD_AUTOTRIAGE_API_BASE_URL",
                "http://10.190.57.183:8000",
            ).strip()
            or "http://10.190.57.183:8000",
            allowed_model_hosts=extra_hosts,
            job_timeout_seconds=_integer("DASHBOARD_JOB_TIMEOUT_SECONDS", 720, 32),
            trust_proxy_identity_headers=_bool(
                "DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS", False
            ),
            identity_header=os.getenv(
                "DASHBOARD_IDENTITY_HEADER", "X-SSO-User"
            ).strip()
            or "X-SSO-User",
            team_default_managers=team_default_managers,
        )

    @property
    def db_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise RuntimeError(
                "当前 MVP 仅启用 SQLite 运行时；PostgreSQL 表结构位于 "
                "migrations/postgres/，接入正式实例时替换 storage adapter。"
            )
        return Path(self.database_url[len(prefix) :]).expanduser().resolve()

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def review_attachments_dir(self) -> Path:
        return self.data_dir / "review_attachments"

    @property
    def case_thumbnails_dir(self) -> Path:
        return self.data_dir / "case_thumbnails"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.review_attachments_dir.mkdir(parents=True, exist_ok=True)
        self.case_thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.batch_bag_cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
