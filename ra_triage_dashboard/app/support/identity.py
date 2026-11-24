"""Identity HTTP helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..auth import normalise_username, request_identity
from ..runtime import database, settings
from .common import _as_text, _detail


def _cached_verified_auth(request: Request) -> tuple[Any, str] | None:
    """Reuse identity/role resolved by production_write_guard on the same request."""
    state = getattr(request, "state", None)
    cached = getattr(state, "_verified_auth", None) if state is not None else None
    if (
        isinstance(cached, tuple)
        and len(cached) == 4
        and cached[0] == id(settings)
        and cached[1] == id(database)
    ):
        return cached[2], str(cached[3] or "")
    return None


def _resolve_request_identity_and_role(request: Request) -> tuple[Any, str]:
    cached = _cached_verified_auth(request)
    if cached is not None:
        return cached
    identity = request_identity(request, settings)
    role = (
        database.access_role(identity.username)
        if identity.verified and identity.username
        else ""
    )
    return identity, role


def _action_actor(request: Request, submitted_name: Any = "") -> tuple[str, str, bool]:
    """Resolve an audit/display actor without trusting direct-IP client claims."""

    cached = _cached_verified_auth(request)
    identity = cached[0] if cached is not None else request_identity(request, settings)
    if identity.verified and identity.username:
        return identity.username, identity.source, True
    username = normalise_username(_as_text(submitted_name))
    if username:
        return username, "client_claim_unverified", False
    return "", "anonymous", False

def _is_dashboard_admin(request: Request) -> bool:
    identity, role = _resolve_request_identity_and_role(request)
    return bool(identity.verified and identity.username and role == "admin")

def _can_manage_team_default(request: Request) -> bool:
    return _is_dashboard_admin(request)

def _admin_identity(request: Request):
    identity, role = _resolve_request_identity_and_role(request)
    if not (identity.verified and identity.username and role == "admin"):
        raise _detail(403, "该操作仅限 Dashboard 管理员。")
    return identity


def _writer_identity(request: Request):
    """Require a verified Dashboard writer while preserving the actor identity."""

    identity, role = _resolve_request_identity_and_role(request)
    if role not in {"writer", "admin"}:
        raise _detail(403, "该操作需要 Dashboard writer 或管理员权限。")
    return identity

def _intent_identity(request: Request, permission: str = "view"):
    """Independent intent capability; neither SSO nor navigation grants writes."""

    cached = _cached_verified_auth(request)
    identity = cached[0] if cached is not None else request_identity(request, settings)
    if not (
        identity.verified
        and identity.username
        and database.intent_permission(identity.username) in {
            "view": {"view", "annotate", "manage"},
            "annotate": {"annotate", "manage"},
            "manage": {"manage"},
        }[permission]
    ):
        raise _detail(403, "当前账号没有此标注操作的权限，请联系管理员。")
    return identity
