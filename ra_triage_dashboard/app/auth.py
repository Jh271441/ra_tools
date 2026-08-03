from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from urllib import parse, request as urlrequest

from fastapi import Request

from .settings import Settings


IDENTITY_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
IDENTITY_DIAGNOSTIC_HEADER_RE = re.compile(
    r"(?:^|-)(?:user|username|account|staff|employee|login|sso)(?:$|-)",
    re.IGNORECASE,
)
SENSITIVE_HEADER_RE = re.compile(
    r"(?:cookie|authorization|token|secret|signature|api-key)",
    re.IGNORECASE,
)
MUTATION_REQUEST_MARKERS = frozenset({"browser-v1", "review-v1", "publish-v1"})
KYLIN_TICKET_COOKIE = "_kylin_ticket"
KYLIN_USERNAME_COOKIE = "_kylin_username"


@dataclass(frozen=True)
class SessionIdentity:
    username: str = ""
    source: str = "anonymous"
    authenticated: bool = False
    verified: bool = False
    trusted_ingress: bool = False

    def as_dict(self, *, trust_proxy_headers: bool) -> dict[str, object]:
        return {
            "username": self.username,
            "source": self.source,
            "authenticated": self.authenticated,
            "verified": self.verified,
            "trusted_ingress": self.trusted_ingress,
            "trust_proxy_headers": trust_proxy_headers,
        }


def normalise_username(value: str) -> str:
    username = value.strip()
    return username if IDENTITY_RE.fullmatch(username) else ""


def identity_header_candidates(request: Request) -> dict[str, str]:
    """Return only username-shaped values from explicitly non-secret headers.

    This is intended for a short, opt-in ingress integration diagnostic.  It
    must never be used to authenticate or authorize a request.
    """

    candidates: dict[str, str] = {}
    for name, value in request.headers.items():
        if SENSITIVE_HEADER_RE.search(name):
            continue
        if not IDENTITY_DIAGNOSTIC_HEADER_RE.search(name):
            continue
        username = normalise_username(value)
        if username:
            candidates[name.lower()] = username
    return candidates


def _read_ingress_token(settings: Settings) -> str:
    path = settings.trusted_ingress_token_file
    if path is None:
        return ""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("ingress token 文件必须是当前用户的普通文件。")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("ingress token 文件权限必须为 0600。")
        raw = os.read(descriptor, 513)
    finally:
        os.close(descriptor)
    if len(raw) > 512:
        raise RuntimeError("ingress token 文件内容过长。")
    token = raw.decode("utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("ingress token 至少需要 32 个字符。")
    return token


def validate_identity_settings(settings: Settings) -> None:
    """Fail startup if production identity trust cannot be established safely."""

    if settings.deployment_mode == "production" and settings.trust_proxy_identity_headers:
        _read_ingress_token(settings)


class KylinSSOValidator:
    """Validate Kylin cookies server-side without delaying media requests.

    Only callers that actually resolve identity invoke this client. Successful
    validations are cached briefly by a digest of the ticket; raw SSO tickets
    are never logged or retained as cache keys.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, str]] = {}

    def validate(self, ticket: str, username: str, settings: Settings) -> bool:
        if not settings.kylin_sso_enabled:
            return False
        normalized = normalise_username(username)
        if not normalized or not ticket or len(ticket) > 4096:
            return False
        cache_key = sha256(ticket.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return secrets.compare_digest(cached[1], normalized)

        payload = parse.urlencode(
            {"app_id": settings.kylin_sso_app_id, "ticket": ticket}
        ).encode("ascii")
        try:
            outbound = urlrequest.Request(
                settings.kylin_sso_check_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlrequest.urlopen(
                outbound, timeout=settings.kylin_sso_timeout_seconds
            ) as response:
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

        ttl = settings.kylin_sso_cache_seconds if valid else min(
            settings.kylin_sso_cache_seconds, 10
        )
        with self._lock:
            self._cache[cache_key] = (now + max(ttl, 1), returned)
            if len(self._cache) > 4096:
                self._cache = {
                    key: value for key, value in self._cache.items() if value[0] > now
                }
        return valid


_kylin_sso_validator = KylinSSOValidator()


def is_trusted_ingress(request: Request, settings: Settings) -> bool:
    if not settings.trust_proxy_identity_headers:
        return False
    expected = _read_ingress_token(settings)
    supplied = request.headers.get(settings.trusted_ingress_header, "").strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def request_identity(request: Request, settings: Settings) -> SessionIdentity:
    """Resolve identity from a server-validated Kylin ticket or trusted ingress.

    Direct-IP clients can forge cookies and request headers. Kylin cookies are
    accepted only after the company SSO API validates the ticket and returns
    the same username. Proxy headers require the separate trusted marker.
    """

    if settings.trust_proxy_identity_headers:
        if not is_trusted_ingress(request, settings):
            return SessionIdentity(source="untrusted_ingress")
        username = normalise_username(request.headers.get(settings.identity_header, ""))
        if not username:
            return SessionIdentity(source="trusted_proxy_header_missing")
        return SessionIdentity(
            username=username,
            source=f"trusted_proxy:{settings.identity_header.lower()}",
            authenticated=True,
            verified=True,
            trusted_ingress=True,
        )

    username = normalise_username(request.cookies.get(KYLIN_USERNAME_COOKIE, ""))
    ticket = request.cookies.get(KYLIN_TICKET_COOKIE, "")
    if (
        username
        and ticket
        and _kylin_sso_validator.validate(ticket, username, settings)
    ):
        return SessionIdentity(
            username=username,
            source="kylin_ticket",
            authenticated=True,
            verified=True,
        )
    source = "kylin_ticket_invalid" if username or ticket else "anonymous"
    return SessionIdentity(source=source)


def identity_can_write(identity: SessionIdentity, settings: Settings) -> bool:
    if not identity.verified or not identity.username:
        return False
    return not settings.sso_write_users or identity.username in settings.sso_write_users


def has_same_origin_mutation_marker(request: Request) -> bool:
    """Require a non-simple browser header so cross-site forms cannot mutate data."""

    return (
        request.headers.get("x-ra-triage-request", "").strip()
        in MUTATION_REQUEST_MARKERS
    )
