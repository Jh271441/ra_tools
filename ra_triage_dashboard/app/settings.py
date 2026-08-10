from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .web_paths import normalize_base_path


HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
IDENTITY_NAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


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


def _company_sso_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "mis.diditaxi.com.cn":
        raise RuntimeError(f"{name} 必须是 mis.diditaxi.com.cn 的 HTTPS 地址。")
    return value


def _dashboard_return_url(name: str, value: str, base_path: str) -> str:
    parsed = urlparse(value)
    expected_prefix = f"{base_path}/" if base_path else "/"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "auto-triage.intra.xiaojukeji.com"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not parsed.path.startswith(expected_prefix)
        or parsed.fragment
    ):
        raise RuntimeError(
            f"{name} 必须是 auto-triage.intra.xiaojukeji.com 的 {expected_prefix} HTTPS 地址。"
        )
    return value


def _kylin_logout_url(endpoint: str, app_id: str, return_url: str) -> str:
    parsed = urlparse(endpoint)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"app_id": app_id, "jumpto": return_url})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _database_url(data_dir: Path) -> str:
    direct = os.getenv("DASHBOARD_DATABASE_URL", "").strip()
    if direct:
        return direct
    url_file_value = os.getenv("DASHBOARD_DATABASE_URL_FILE", "").strip()
    if not url_file_value:
        return f"sqlite:///{data_dir / 'triage.sqlite3'}"
    url_file = Path(url_file_value).expanduser().absolute()
    descriptor = os.open(url_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("DASHBOARD_DATABASE_URL_FILE 必须是普通文件。")
        if metadata.st_uid != os.getuid():
            raise RuntimeError("DASHBOARD_DATABASE_URL_FILE 必须属于当前服务用户。")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("DASHBOARD_DATABASE_URL_FILE 权限必须为 0600。")
        value = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(value) > 16 * 1024:
        raise RuntimeError("DASHBOARD_DATABASE_URL_FILE 内容过长。")
    database_url = value.decode("utf-8").strip()
    if not database_url:
        raise RuntimeError("DASHBOARD_DATABASE_URL_FILE 不能为空。")
    return database_url


@dataclass(frozen=True)
class Settings:
    app_root: Path
    build_commit: str
    base_path: str
    static_dir: Path
    data_dir: Path
    database_url: str
    postgres_persistent_data: bool
    ra_auto_triage_root: Path
    ares_manifest: Path
    camera_root: Path
    ares_video_root: Path
    baseline_label_xlsx: Path
    baseline_dataset: str
    baseline_scope: str
    baselines_file: Path | None
    baseline_overlap_mode: str
    bootstrap_model_json: Path | None
    trail_view_id: int
    trail_sync_on_start: bool
    trail_sync_chunk_size: int
    gt_sync_enabled: bool
    gt_sync_interval_seconds: int
    gt_sync_startup_delay_seconds: int
    gt_sync_baseline_id: str
    gt_sync_view_id: int
    gt_sync_chunk_size: int
    trail_detail_metadata_enabled: bool
    trail_detail_metadata_cache_seconds: int
    voyager_issue_base_url: str
    voyager_issue_view_id: int
    ra_recording_base_url: str
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
    identity_diagnostics: bool
    identity_header: str
    deployment_mode: str
    trusted_ingress_header: str
    trusted_ingress_token_file: Path | None
    kylin_sso_enabled: bool
    kylin_sso_app_id: str
    kylin_sso_check_url: str
    kylin_sso_logout_url: str
    kylin_sso_return_url: str
    kylin_sso_timeout_seconds: float
    kylin_sso_cache_seconds: int
    sso_write_users: tuple[str, ...]
    team_default_managers: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        app_root = Path(__file__).resolve().parents[1]
        base_path = normalize_base_path(os.getenv("DASHBOARD_BASE_PATH", ""))
        data_dir = _path("DASHBOARD_DATA_DIR", app_root / ".data")
        ra_root = _path(
            "RA_AUTO_TRIAGE_ROOT",
            Path("/volume/home/workspace/ra_auto_triage"),
        )
        manifest = _path(
            "ARES_CAPTURE_MANIFEST",
            ra_root
            / "bags/ares_capture_bev_ra_stuck_swag_planning_2k_from_cloud_server_2_20260804"
            / "7f4b2d9f-1218-4cd4-a93d-0654603173b9"
            / "manifest.jsonl",
        )
        camera_root = _path("CAMERA_CACHE_ROOT", ra_root / "bags/camera")
        ares_video_root = _path(
            "ARES_CAPTURE_VIDEO_ROOT",
            ra_root
            / "bags/ares_capture_video_0508_1071_ra_stuck_swag_planning_2k_aggregate_20260804",
        )
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
        deployment_mode = os.getenv(
            "DASHBOARD_DEPLOYMENT_MODE", "development"
        ).strip().lower()
        if deployment_mode not in {"development", "production"}:
            raise RuntimeError(
                "DASHBOARD_DEPLOYMENT_MODE 必须是 development 或 production。"
            )
        ingress_token_file_value = os.getenv(
            "DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE", ""
        ).strip()
        ingress_token_file = (
            Path(ingress_token_file_value).expanduser().absolute()
            if ingress_token_file_value
            else None
        )
        sso_write_users = tuple(
            username.strip()
            for username in os.getenv("DASHBOARD_SSO_WRITE_USERS", "").split(",")
            if username.strip()
        )
        if any(not IDENTITY_NAME_RE.fullmatch(username) for username in sso_write_users):
            raise RuntimeError("DASHBOARD_SSO_WRITE_USERS 包含非法用户名。")
        trust_proxy_headers = _bool(
            "DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS", False
        )
        identity_diagnostics = _bool("DASHBOARD_IDENTITY_DIAGNOSTICS", False)
        identity_header = (
            os.getenv("DASHBOARD_IDENTITY_HEADER", "X-SSO-User").strip()
            or "X-SSO-User"
        )
        trusted_ingress_header = (
            os.getenv(
                "DASHBOARD_TRUSTED_INGRESS_HEADER", "X-RA-Triage-Ingress"
            ).strip()
            or "X-RA-Triage-Ingress"
        )
        kylin_sso_enabled = _bool("DASHBOARD_KYLIN_SSO_ENABLED", True)
        kylin_sso_app_id = (
            os.getenv("DASHBOARD_KYLIN_SSO_APP_ID", "2103794").strip()
            or "2103794"
        )
        if not kylin_sso_app_id.isdigit():
            raise RuntimeError("DASHBOARD_KYLIN_SSO_APP_ID 必须是数字。")
        try:
            kylin_sso_timeout_seconds = float(
                os.getenv("DASHBOARD_KYLIN_SSO_TIMEOUT_SECONDS", "1.5")
            )
        except ValueError as exc:
            raise RuntimeError(
                "DASHBOARD_KYLIN_SSO_TIMEOUT_SECONDS 必须是数字。"
            ) from exc
        if not 0.1 <= kylin_sso_timeout_seconds <= 5.0:
            raise RuntimeError("DASHBOARD_KYLIN_SSO_TIMEOUT_SECONDS 必须在 0.1 到 5 秒之间。")
        kylin_sso_check_url = _company_sso_url(
            "DASHBOARD_KYLIN_SSO_CHECK_URL",
            os.getenv(
                "DASHBOARD_KYLIN_SSO_CHECK_URL",
                "https://mis.diditaxi.com.cn/auth/sso/api/check_user_ticket",
            ).strip(),
        )
        kylin_sso_logout_endpoint = _company_sso_url(
            "DASHBOARD_KYLIN_SSO_LOGOUT_URL",
            os.getenv(
                "DASHBOARD_KYLIN_SSO_LOGOUT_URL",
                "https://mis.diditaxi.com.cn/auth/ldap/logout",
            ).strip(),
        )
        kylin_sso_return_url = _dashboard_return_url(
            "DASHBOARD_KYLIN_SSO_RETURN_URL",
            os.getenv(
                "DASHBOARD_KYLIN_SSO_RETURN_URL",
                f"https://auto-triage.intra.xiaojukeji.com{base_path}/review",
            ).strip(),
            base_path,
        )
        kylin_sso_logout_url = _kylin_logout_url(
            kylin_sso_logout_endpoint,
            kylin_sso_app_id,
            kylin_sso_return_url,
        )
        if not HEADER_NAME_RE.fullmatch(identity_header):
            raise RuntimeError("DASHBOARD_IDENTITY_HEADER 不是合法的 HTTP header 名。")
        if not HEADER_NAME_RE.fullmatch(trusted_ingress_header):
            raise RuntimeError(
                "DASHBOARD_TRUSTED_INGRESS_HEADER 不是合法的 HTTP header 名。"
            )
        if identity_header.lower() == trusted_ingress_header.lower():
            raise RuntimeError("身份 header 与 ingress marker header 不能相同。")
        if deployment_mode == "production" and not kylin_sso_enabled and (
            not trust_proxy_headers or ingress_token_file is None
        ):
            raise RuntimeError(
                "production 模式必须启用 Kylin ticket 校验，或启用可信代理身份并配置 ingress token 文件。"
            )
        return cls(
            app_root=app_root,
            build_commit=(
                os.getenv("DASHBOARD_BUILD_COMMIT", "").strip()[:64]
                or "unverified"
            ),
            base_path=base_path,
            static_dir=app_root / "static",
            data_dir=data_dir,
            database_url=_database_url(data_dir),
            postgres_persistent_data=_bool(
                "DASHBOARD_POSTGRES_PERSISTENT_DATA", False
            ),
            ra_auto_triage_root=ra_root,
            ares_manifest=manifest,
            camera_root=camera_root,
            ares_video_root=ares_video_root,
            baseline_label_xlsx=baseline_xlsx,
            baseline_dataset=os.getenv("DASHBOARD_BASELINE_DATASET", "0508").strip() or "0508",
            baseline_scope=os.getenv(
                "DASHBOARD_BASELINE_SCOPE", "release0508_1071_20260729"
            ).strip()
            or "release0508_1071_20260729",
            baselines_file=(
                Path(os.getenv("DASHBOARD_BASELINES_FILE", "").strip()).expanduser()
                if os.getenv("DASHBOARD_BASELINES_FILE", "").strip()
                else (app_root / "config" / "baselines.json")
            ),
            baseline_overlap_mode=(
                os.getenv("DASHBOARD_BASELINE_OVERLAP_MODE", "fail_skip").strip()
                or "fail_skip"
            ),
            bootstrap_model_json=bootstrap,
            trail_view_id=_integer("DASHBOARD_TRAIL_VIEW_ID", 2410),
            trail_sync_on_start=_bool("DASHBOARD_SYNC_TRAIL_ON_START", True),
            trail_sync_chunk_size=_integer("DASHBOARD_TRAIL_SYNC_CHUNK_SIZE", 160, 1),
            gt_sync_enabled=_bool("DASHBOARD_GT_SYNC_ENABLED", True),
            gt_sync_interval_seconds=_integer(
                "DASHBOARD_GT_SYNC_INTERVAL_SECONDS", 900, 60
            ),
            gt_sync_startup_delay_seconds=_integer(
                "DASHBOARD_GT_SYNC_STARTUP_DELAY_SECONDS", 3, 0
            ),
            gt_sync_baseline_id=(
                os.getenv("DASHBOARD_GT_SYNC_BASELINE_ID", "0508").strip()
                or "0508"
            ),
            gt_sync_view_id=_integer("DASHBOARD_GT_SYNC_VIEW_ID", 1000),
            gt_sync_chunk_size=_integer(
                "DASHBOARD_GT_SYNC_CHUNK_SIZE", 160, 1
            ),
            trail_detail_metadata_enabled=_bool(
                "DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED", True
            ),
            trail_detail_metadata_cache_seconds=_integer(
                "DASHBOARD_TRAIL_DETAIL_METADATA_CACHE_SECONDS", 300, 0
            ),
            voyager_issue_base_url=os.getenv(
                "DASHBOARD_VOYAGER_ISSUE_BASE_URL",
                "https://voyager.intra.xiaojukeji.com/static/management/#/issue",
            ).strip()
            or "https://voyager.intra.xiaojukeji.com/static/management/#/issue",
            voyager_issue_view_id=_integer("DASHBOARD_VOYAGER_ISSUE_VIEW_ID", 2410),
            ra_recording_base_url=os.getenv(
                "DASHBOARD_RA_RECORDING_BASE_URL",
                "https://s3-gzpu-inter.didistatic.com/voyager-fe/operation-platform/ra/dashboard/index.html#/tasks",
            ).strip()
            or "https://s3-gzpu-inter.didistatic.com/voyager-fe/operation-platform/ra/dashboard/index.html#/tasks",
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
            trust_proxy_identity_headers=trust_proxy_headers,
            identity_diagnostics=identity_diagnostics,
            identity_header=identity_header,
            deployment_mode=deployment_mode,
            trusted_ingress_header=trusted_ingress_header,
            trusted_ingress_token_file=ingress_token_file,
            kylin_sso_enabled=kylin_sso_enabled,
            kylin_sso_app_id=kylin_sso_app_id,
            kylin_sso_check_url=kylin_sso_check_url,
            kylin_sso_logout_url=kylin_sso_logout_url,
            kylin_sso_return_url=kylin_sso_return_url,
            kylin_sso_timeout_seconds=kylin_sso_timeout_seconds,
            kylin_sso_cache_seconds=_integer(
                "DASHBOARD_KYLIN_SSO_CACHE_SECONDS", 300, 1
            ),
            sso_write_users=sso_write_users,
            team_default_managers=team_default_managers,
        )

    @property
    def db_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise RuntimeError("PostgreSQL 运行时没有本地 db_path。")
        return Path(self.database_url[len(prefix) :]).expanduser().resolve()

    @property
    def storage_backend(self) -> str:
        if self.database_url.startswith("sqlite:///"):
            return "sqlite"
        if self.database_url.startswith(("postgresql://", "postgres://")):
            return "postgresql"
        raise RuntimeError("DASHBOARD_DATABASE_URL 仅支持 sqlite:/// 或 postgresql://。")

    @property
    def postgres_migrations_dir(self) -> Path:
        return self.app_root / "migrations" / "postgres"

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
        if self.storage_backend == "sqlite":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
