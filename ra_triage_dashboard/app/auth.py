from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Request

from .settings import Settings


IDENTITY_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


@dataclass(frozen=True)
class SessionIdentity:
    username: str = ""
    source: str = "anonymous"
    authenticated: bool = False
    verified: bool = False

    def as_dict(self, *, trust_proxy_headers: bool) -> dict[str, object]:
        return {
            "username": self.username,
            "source": self.source,
            "authenticated": self.authenticated,
            "verified": self.verified,
            "trust_proxy_headers": trust_proxy_headers,
        }


def _normalise_username(value: str) -> str:
    username = value.strip()
    return username if IDENTITY_RE.fullmatch(username) else ""


def request_identity(request: Request, settings: Settings) -> SessionIdentity:
    """Resolve an identity only from an explicitly trusted ingress header.

    Direct-IP clients can forge request headers, so this path is disabled by
    default.  The future SSO ingress must strip the client header, inject the
    configured header itself, and be the only network path to this service
    before ``DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS`` is enabled.
    """

    if not settings.trust_proxy_identity_headers:
        return SessionIdentity()
    username = _normalise_username(request.headers.get(settings.identity_header, ""))
    if not username:
        return SessionIdentity(source="trusted_proxy_header_missing")
    return SessionIdentity(
        username=username,
        source=f"trusted_proxy:{settings.identity_header.lower()}",
        authenticated=True,
        verified=True,
    )
