from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._/@:+-]{1,160}$")
WORKER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
BASE_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
_DASHBOARD_HOSTS = {"127.0.0.1", "localhost"}
_MODEL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "ra-model.intra.xiaojukeji.com",
    "tokenservice-gateway-ys.intra.xiaojukeji.com",
}
_RELAY_HOSTS = {"127.0.0.1", "localhost", "ra-model.intra.xiaojukeji.com"}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 必须是 true 或 false。")


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数字。") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须在 {minimum} 到 {maximum} 之间。")
    return value


def _base_path(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    if not BASE_PATH_RE.fullmatch(value):
        raise RuntimeError(f"{name} 必须是形如 /dchat 的非根路径。")
    return value


def _fixed_url(value: str, *, hosts: set[str], path: str | None = None) -> str:
    parsed = urlsplit(value.strip().rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "").lower() not in hosts
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (path is not None and parsed.path.rstrip("/") != path.rstrip("/"))
    ):
        raise RuntimeError("Bot 服务地址配置不在允许的固定主机范围内。")
    return parsed.geturl().rstrip("/")


@dataclass(frozen=True)
class Settings:
    enabled: bool
    smoke_enabled: bool
    base_path: str
    allowed_users: frozenset[str]
    allow_all_users: bool
    host: str
    port: int
    data_dir: Path
    webhook_auth_mode: str
    webhook_secret_file: Path
    dashboard_base_url: str
    dashboard_timeout_seconds: float
    dashboard_review_url: str
    delivery_mode: str
    dchat_base_url: str
    dchat_credentials_file: Path
    dchat_timeout_seconds: float
    model_chat_url: str
    model_api_key_file: Path
    model_id: str
    model_timeout_seconds: float
    model_temperature: float
    max_question_chars: int
    max_answer_chars: int
    relay_url: str
    relay_worker_secret_file: Path
    relay_worker_id: str
    relay_poll_seconds: float
    relay_lease_seconds: int
    relay_max_attempts: int
    worker_base_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(
            os.getenv("AUTOTRIAGE_BOT_DATA_DIR", "auto_triage_bot/.data")
        ).expanduser().resolve()
        auth_mode = os.getenv("AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE", "hmac").strip().lower()
        if auth_mode not in {"hmac", "token"}:
            raise RuntimeError("AUTOTRIAGE_BOT_WEBHOOK_AUTH_MODE 必须是 hmac 或 token。")
        delivery_mode = os.getenv("AUTOTRIAGE_BOT_DELIVERY_MODE", "loopback").strip().lower()
        if delivery_mode not in {"openapi", "loopback"}:
            raise RuntimeError("AUTOTRIAGE_BOT_DELIVERY_MODE 必须是 openapi 或 loopback。")
        model_id = os.getenv("AUTOTRIAGE_BOT_MODEL_ID", "").strip()
        if model_id and not MODEL_ID_RE.fullmatch(model_id):
            raise RuntimeError("AUTOTRIAGE_BOT_MODEL_ID 格式非法。")
        max_question = int(os.getenv("AUTOTRIAGE_BOT_MAX_QUESTION_CHARS", "3000"))
        max_answer = int(os.getenv("AUTOTRIAGE_BOT_MAX_ANSWER_CHARS", "2800"))
        if not 100 <= max_question <= 10000 or not 200 <= max_answer <= 3000:
            raise RuntimeError("Bot 问题或答案长度配置非法。")
        allowed_users = frozenset(
            value.strip().lower()
            for value in os.getenv("AUTOTRIAGE_BOT_ALLOWED_USERS", "").split(",")
            if value.strip()
        )
        if any(not re.fullmatch(r"[A-Za-z0-9._@-]{1,128}", value) for value in allowed_users):
            raise RuntimeError("AUTOTRIAGE_BOT_ALLOWED_USERS 含非法 LDAP。")
        relay_worker_id = os.getenv(
            "AUTOTRIAGE_BOT_RELAY_WORKER_ID", "cloud-server-1"
        ).strip()
        if not WORKER_ID_RE.fullmatch(relay_worker_id):
            raise RuntimeError("AUTOTRIAGE_BOT_RELAY_WORKER_ID 格式非法。")
        relay_lease_seconds = int(
            _number("AUTOTRIAGE_BOT_RELAY_LEASE_SECONDS", 120.0, 30.0, 600.0)
        )
        relay_max_attempts = int(
            _number("AUTOTRIAGE_BOT_RELAY_MAX_ATTEMPTS", 5.0, 1.0, 20.0)
        )
        enabled = _bool("AUTOTRIAGE_BOT_ENABLED", False)
        smoke_enabled = _bool("AUTOTRIAGE_BOT_SMOKE_ENABLED", False)
        allow_all_users = _bool("AUTOTRIAGE_BOT_ALLOW_ALL_USERS", False)
        if enabled and not allowed_users and not allow_all_users:
            raise RuntimeError(
                "启用 Bot 前必须配置 AUTOTRIAGE_BOT_ALLOWED_USERS，"
                "或显式设置 AUTOTRIAGE_BOT_ALLOW_ALL_USERS=true。"
            )
        return cls(
            enabled=enabled,
            smoke_enabled=smoke_enabled,
            base_path=_base_path("AUTOTRIAGE_BOT_BASE_PATH", "/dchat"),
            allowed_users=allowed_users,
            allow_all_users=allow_all_users,
            host=os.getenv("AUTOTRIAGE_BOT_HOST", "127.0.0.1").strip(),
            port=int(os.getenv("AUTOTRIAGE_BOT_PORT", "8790")),
            data_dir=data_dir,
            webhook_auth_mode=auth_mode,
            webhook_secret_file=Path(
                os.getenv(
                    "AUTOTRIAGE_BOT_WEBHOOK_SECRET_FILE",
                    str(data_dir / "webhook_secret"),
                )
            ).expanduser().resolve(),
            dashboard_base_url=_fixed_url(
                os.getenv("AUTOTRIAGE_BOT_DASHBOARD_URL", "http://127.0.0.1:8785"),
                hosts=_DASHBOARD_HOSTS,
            ),
            dashboard_timeout_seconds=_number(
                "AUTOTRIAGE_BOT_DASHBOARD_TIMEOUT_SECONDS", 3.0, 0.2, 10.0
            ),
            dashboard_review_url=os.getenv(
                "AUTOTRIAGE_BOT_REVIEW_URL",
                "https://auto-triage.intra.xiaojukeji.com/manual/review",
            ).strip(),
            delivery_mode=delivery_mode,
            dchat_base_url=os.getenv(
                "AUTOTRIAGE_BOT_DCHAT_BASE_URL",
                "https://oapi-dichat.intra.xiaojukeji.com",
            ).strip(),
            dchat_credentials_file=Path(
                os.getenv(
                    "AUTOTRIAGE_BOT_DCHAT_CREDENTIALS_FILE",
                    str(data_dir / "dchat_credentials.json"),
                )
            ).expanduser().resolve(),
            dchat_timeout_seconds=_number(
                "AUTOTRIAGE_BOT_DCHAT_TIMEOUT_SECONDS", 3.0, 0.2, 10.0
            ),
            model_chat_url=_fixed_url(
                os.getenv(
                    "AUTOTRIAGE_BOT_MODEL_CHAT_URL",
                    "http://ra-model.intra.xiaojukeji.com/v1/chat/completions",
                ),
                hosts=_MODEL_HOSTS,
                path="/v1/chat/completions",
            ),
            model_api_key_file=Path(
                os.getenv(
                    "AUTOTRIAGE_BOT_MODEL_API_KEY_FILE",
                    str(data_dir / "model_gateway_api_key"),
                )
            ).expanduser().resolve(),
            model_id=model_id,
            model_timeout_seconds=_number(
                "AUTOTRIAGE_BOT_MODEL_TIMEOUT_SECONDS", 20.0, 1.0, 60.0
            ),
            model_temperature=_number(
                "AUTOTRIAGE_BOT_MODEL_TEMPERATURE", 0.2, 0.0, 1.0
            ),
            max_question_chars=max_question,
            max_answer_chars=max_answer,
            relay_url=_fixed_url(
                os.getenv(
                    "AUTOTRIAGE_BOT_RELAY_URL",
                    "https://ra-model.intra.xiaojukeji.com/dchat-worker",
                ),
                hosts=_RELAY_HOSTS,
                path="/dchat-worker",
            ),
            relay_worker_secret_file=Path(
                os.getenv(
                    "AUTOTRIAGE_BOT_RELAY_WORKER_SECRET_FILE",
                    str(data_dir / "relay_worker_secret"),
                )
            ).expanduser().resolve(),
            relay_worker_id=relay_worker_id,
            relay_poll_seconds=_number(
                "AUTOTRIAGE_BOT_RELAY_POLL_SECONDS", 1.0, 0.2, 30.0
            ),
            relay_lease_seconds=relay_lease_seconds,
            relay_max_attempts=relay_max_attempts,
            worker_base_path=_base_path(
                "AUTOTRIAGE_BOT_WORKER_BASE_PATH", "/dchat-worker"
            ),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def user_allowed(self, username: str) -> bool:
        return self.allow_all_users or username.strip().lower() in self.allowed_users
