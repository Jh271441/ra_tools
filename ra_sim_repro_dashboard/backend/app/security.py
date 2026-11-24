"""Kylin SSO verification, same-origin write guard, CORS allowlist, and audit logging.

Aligned with the sibling `/manual` Workbench (`ra_triage_dashboard/app/auth.py`)
operating under the same `auto-triage.intra.xiaojukeji.com` Kylin SSO domain
(`app_id=2103794`). Direct-IP callers cannot forge company SSO tickets; in
production mode all mutating API calls require a server-verified SSO ticket and
a non-simple browser header (`X-RA-Sim-Request`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable
from urllib import parse, request as urlrequest
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

audit_logger = logging.getLogger("app.audit")

IDENTITY_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MUTATION_REQUEST_MARKERS = frozenset({"browser-v1", "workflow-v1", "evaluation-v1"})
KYLIN_TICKET_COOKIE = "_kylin_ticket"
KYLIN_USERNAME_COOKIE = "_kylin_username"
DEFAULT_KYLIN_CHECK_URL = "https://mis.diditaxi.com.cn/auth/sso/api/check_user_ticket"
DEFAULT_KYLIN_APP_ID = "2103794"
DEFAULT_PROD_ORIGINS = ("https://auto-triage.intra.xiaojukeji.com",)
DEFAULT_DEV_ORIGINS = (
    "https://auto-triage.intra.xiaojukeji.com",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:8787",
    "http://localhost:8787",
)

# Optional sink registered by P1 to persist audit records into `admin_audit_logs`.
_audit_db_sink: Callable[[dict[str, object]], None] | None = None


def register_audit_sink(sink: Callable[[dict[str, object]], None] | None) -> None:
    global _audit_db_sink
    _audit_db_sink = sink


@dataclass(frozen=True)
class SecurityConfig:
    deployment_mode: str
    cors_origins: tuple[str, ...]
    kylin_sso_enabled: bool
    kylin_sso_check_url: str
    kylin_sso_app_id: str
    kylin_sso_timeout_seconds: float
    kylin_sso_cache_seconds: int
    sso_write_users: tuple[str, ...]
    sso_read_required: bool
    trust_proxy_identity_headers: bool
    identity_header: str
    trusted_ingress_header: str
    trusted_ingress_token_file: Path | None


@dataclass(frozen=True)
class SessionIdentity:
    username: str = ""
    source: str = "anonymous"
    authenticated: bool = False
    verified: bool = False
    trusted_ingress: bool = False

    def as_dict(self, *, can_write: bool, deployment_mode: str) -> dict[str, object]:
        return {
            "username": self.username,
            "source": self.source,
            "authenticated": self.authenticated,
            "verified": self.verified,
            "trusted_ingress": self.trusted_ingress,
            "can_write": can_write,
            "deployment_mode": deployment_mode,
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _validate_sso_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "mis.diditaxi.com.cn":
        raise RuntimeError("SIM_KYLIN_SSO_CHECK_URL must be an HTTPS URL on mis.diditaxi.com.cn")
    return url


def load_security_config() -> SecurityConfig:
    mode = os.getenv("SIM_DEPLOYMENT_MODE", "development").strip().lower() or "development"
    if mode not in {"development", "production"}:
        raise RuntimeError("SIM_DEPLOYMENT_MODE must be 'development' or 'production'")

    raw_origins = os.getenv("SIM_CORS_ORIGINS", "").strip()
    if raw_origins:
        origins = tuple(item.strip().rstrip("/") for item in raw_origins.split(",") if item.strip())
        if "*" in origins:
            raise RuntimeError(
                "SIM_CORS_ORIGINS must not contain wildcard '*' when credentials are enabled"
            )
    else:
        origins = DEFAULT_PROD_ORIGINS if mode == "production" else DEFAULT_DEV_ORIGINS

    kylin_sso_enabled = _env_bool("SIM_KYLIN_SSO_ENABLED", True)
    check_url = _validate_sso_url(
        os.getenv("SIM_KYLIN_SSO_CHECK_URL", DEFAULT_KYLIN_CHECK_URL).strip()
    )
    app_id = os.getenv("SIM_KYLIN_SSO_APP_ID", DEFAULT_KYLIN_APP_ID).strip() or DEFAULT_KYLIN_APP_ID
    if not app_id.isdigit():
        raise RuntimeError("SIM_KYLIN_SSO_APP_ID must be numeric")

    timeout = float(os.getenv("SIM_KYLIN_SSO_TIMEOUT_SECONDS", "1.5"))
    if not 0.1 <= timeout <= 5.0:
        raise RuntimeError("SIM_KYLIN_SSO_TIMEOUT_SECONDS must be between 0.1 and 5.0")
    cache_seconds = max(1, int(os.getenv("SIM_KYLIN_SSO_CACHE_SECONDS", "60")))

    write_users = tuple(
        u.strip() for u in os.getenv("SIM_SSO_WRITE_USERS", "").split(",") if u.strip()
    )
    if any(not IDENTITY_RE.fullmatch(u) for u in write_users):
        raise RuntimeError("SIM_SSO_WRITE_USERS contains an invalid username")

    identity_header = os.getenv("SIM_IDENTITY_HEADER", "X-SSO-User").strip() or "X-SSO-User"
    trusted_ingress_header = (
        os.getenv("SIM_TRUSTED_INGRESS_HEADER", "X-RA-Sim-Ingress").strip() or "X-RA-Sim-Ingress"
    )
    if not HEADER_NAME_RE.fullmatch(identity_header) or not HEADER_NAME_RE.fullmatch(
        trusted_ingress_header
    ):
        raise RuntimeError("Invalid identity or trusted ingress header name")

    token_file_raw = os.getenv("SIM_TRUSTED_INGRESS_TOKEN_FILE", "").strip()
    token_file = Path(token_file_raw).expanduser().absolute() if token_file_raw else None

    return SecurityConfig(
        deployment_mode=mode,
        cors_origins=origins,
        kylin_sso_enabled=kylin_sso_enabled,
        kylin_sso_check_url=check_url,
        kylin_sso_app_id=app_id,
        kylin_sso_timeout_seconds=timeout,
        kylin_sso_cache_seconds=cache_seconds,
        sso_write_users=write_users,
        sso_read_required=_env_bool("SIM_SSO_READ_REQUIRED", False),
        trust_proxy_identity_headers=_env_bool("SIM_TRUST_PROXY_IDENTITY_HEADERS", False),
        identity_header=identity_header,
        trusted_ingress_header=trusted_ingress_header,
        trusted_ingress_token_file=token_file,
    )


def normalise_username(value: str) -> str:
    username = value.strip()
    return username if IDENTITY_RE.fullmatch(username) else ""


def _read_ingress_token(cfg: SecurityConfig) -> str:
    path = cfg.trusted_ingress_token_file
    if path is None:
        return ""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError(
                "SIM_TRUSTED_INGRESS_TOKEN_FILE must be a regular file owned by current user"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("SIM_TRUSTED_INGRESS_TOKEN_FILE permissions must be 0600")
        raw = os.read(descriptor, 513)
    finally:
        os.close(descriptor)
    if len(raw) > 512:
        raise RuntimeError("SIM_TRUSTED_INGRESS_TOKEN_FILE is too large")
    token = raw.decode("utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("SIM_TRUSTED_INGRESS_TOKEN_FILE must contain at least 32 characters")
    return token


def validate_security_settings(cfg: SecurityConfig | None = None) -> SecurityConfig:
    resolved = cfg or load_security_config()
    if resolved.deployment_mode == "production" and (
        resolved.trust_proxy_identity_headers or resolved.trusted_ingress_token_file is not None
    ):
        _read_ingress_token(resolved)
    return resolved


class KylinSSOValidator:
    """Validate Kylin SSO cookies server-side with bounded SHA-256 digest caching."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, str]] = {}

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def validate(self, ticket: str, username: str, cfg: SecurityConfig) -> bool:
        if not cfg.kylin_sso_enabled:
            return False
        normalized = normalise_username(username)
        if not normalized or not ticket or len(ticket) > 4096:
            return False
        cache_key = sha256(f"{cfg.kylin_sso_app_id}:{ticket}".encode("utf-8")).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return secrets.compare_digest(cached[1], normalized)

        payload = parse.urlencode({"app_id": cfg.kylin_sso_app_id, "ticket": ticket}).encode(
            "ascii"
        )
        try:
            outbound = urlrequest.Request(
                cfg.kylin_sso_check_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlrequest.urlopen(outbound, timeout=cfg.kylin_sso_timeout_seconds) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                return False
            result = json.loads(raw.decode("utf-8"))
            data = result.get("data") if isinstance(result, dict) else None
            returned = normalise_username(
                data.get("username", "") if isinstance(data, dict) else ""
            )
            valid = (
                result.get("errno") == 0
                and bool(returned)
                and secrets.compare_digest(returned, normalized)
            )
        except (OSError, TimeoutError, ValueError, TypeError):
            valid = False
            returned = ""

        ttl = cfg.kylin_sso_cache_seconds if valid else min(cfg.kylin_sso_cache_seconds, 10)
        with self._lock:
            self._cache[cache_key] = (now + max(ttl, 1), returned)
            if len(self._cache) > 4096:
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        return valid


_kylin_sso_validator = KylinSSOValidator()


def is_trusted_ingress(request: Request, cfg: SecurityConfig) -> bool:
    if cfg.trusted_ingress_token_file is None:
        return False
    expected = _read_ingress_token(cfg)
    supplied = request.headers.get(cfg.trusted_ingress_header, "").strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def request_identity(request: Request, cfg: SecurityConfig) -> SessionIdentity:
    if cfg.trust_proxy_identity_headers:
        if not is_trusted_ingress(request, cfg):
            return SessionIdentity(source="untrusted_ingress")
        username = normalise_username(request.headers.get(cfg.identity_header, ""))
        if not username:
            return SessionIdentity(source="trusted_proxy_header_missing")
        return SessionIdentity(
            username=username,
            source=f"trusted_proxy:{cfg.identity_header.lower()}",
            authenticated=True,
            verified=True,
            trusted_ingress=True,
        )

    username = normalise_username(request.cookies.get(KYLIN_USERNAME_COOKIE, ""))
    ticket = request.cookies.get(KYLIN_TICKET_COOKIE, "")
    if username and ticket and _kylin_sso_validator.validate(ticket, username, cfg):
        return SessionIdentity(
            username=username,
            source="kylin_ticket",
            authenticated=True,
            verified=True,
        )
    if cfg.deployment_mode == "development":
        return SessionIdentity(
            username="local-dev", source="development", authenticated=False, verified=False
        )
    return SessionIdentity(source="kylin_ticket_invalid" if username or ticket else "anonymous")


def identity_can_write(identity: SessionIdentity, cfg: SecurityConfig) -> bool:
    if cfg.deployment_mode == "development":
        return True
    if not identity.verified or not identity.username:
        return False
    return not cfg.sso_write_users or identity.username in cfg.sso_write_users


def has_same_origin_mutation_marker(request: Request) -> bool:
    return request.headers.get("x-ra-sim-request", "").strip() in MUTATION_REQUEST_MARKERS


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    return (request.client.host if request.client else "")[:64]


def emit_audit_record(
    *,
    identity: SessionIdentity,
    request: Request,
    status_code: int,
    latency_ms: float,
    reason: str = "",
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": identity.username or "anonymous",
        "identity_source": identity.source,
        "client_ip": _client_ip(request),
        "method": request.method,
        "path": request.url.path,
        "target_release": (
            request.query_params.get("release") or request.query_params.get("version") or ""
        )[:64],
        "status_code": status_code,
        "latency_ms": round(latency_ms, 1),
        "reason": reason,
    }
    audit_logger.info("sim_mutation_audit %s", json.dumps(record, ensure_ascii=False))
    if _audit_db_sink is not None:
        try:
            _audit_db_sink(record)
        except Exception:
            audit_logger.warning("Failed to persist audit record to DB", exc_info=True)


async def security_middleware(request: Request, call_next):
    cfg = load_security_config()
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    is_mutation = request.method in MUTATION_METHODS
    started = time.perf_counter()

    # Optional strict gateway header check for non-loopback traffic if configured.
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in {"127.0.0.1", "::1", "localhost"}
    if (
        cfg.deployment_mode == "production"
        and cfg.trusted_ingress_token_file is not None
        and not cfg.trust_proxy_identity_headers
        and not is_loopback
        and path != "/api/health"
        and not is_trusted_ingress(request, cfg)
    ):
        response = JSONResponse(
            status_code=403,
            content={"detail": "Direct upstream access requires trusted Kylin gateway ingress."},
        )
        if is_mutation:
            emit_audit_record(
                identity=SessionIdentity(source="untrusted_ingress"),
                request=request,
                status_code=403,
                latency_ms=(time.perf_counter() - started) * 1000,
                reason="untrusted_ingress",
            )
        return response

    if cfg.deployment_mode == "production" and cfg.sso_read_required and not is_mutation:
        if path != "/api/health" and not is_loopback:
            identity = await asyncio.to_thread(request_identity, request, cfg)
            if not identity.verified:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "请通过获准的企业 SSO 域名访问。"},
                )

    if not is_mutation:
        return await call_next(request)

    identity = await asyncio.to_thread(request_identity, request, cfg)
    if cfg.deployment_mode == "production":
        if not has_same_origin_mutation_marker(request):
            emit_audit_record(
                identity=identity,
                request=request,
                status_code=403,
                latency_ms=(time.perf_counter() - started) * 1000,
                reason="missing_same_origin_marker",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "写请求缺少同源校验标记，请刷新页面后重试。"},
            )
        if not identity_can_write(identity, cfg):
            emit_audit_record(
                identity=identity,
                request=request,
                status_code=403,
                latency_ms=(time.perf_counter() - started) * 1000,
                reason="unauthorized_writer",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "当前入口为只读预览或无写权限；请通过获准的企业 SSO 域名访问。"},
            )

    request.state.identity = identity
    response = await call_next(request)
    emit_audit_record(
        identity=identity,
        request=request,
        status_code=response.status_code,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return response
