"""Identity HTTP helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..auth import normalise_username, request_identity
from ..runtime import database, settings
from .common import _as_text, _detail


def _action_actor(request: Request, submitted_name: Any = "") -> tuple[str, str, bool]:
    """Resolve an audit/display actor without trusting direct-IP client claims."""

    identity = request_identity(request, settings)
    if identity.verified and identity.username:
        return identity.username, identity.source, True
    username = normalise_username(_as_text(submitted_name))
    if username:
        return username, "client_claim_unverified", False
    return "", "anonymous", False

def _can_manage_team_default(request: Request) -> bool:
    identity = request_identity(request, settings)
    return bool(
        identity.verified
        and identity.username
        and database.access_role(identity.username) == "admin"
    )

def _admin_identity(request: Request):
    identity = request_identity(request, settings)
    if not (
        identity.verified
        and identity.username
        and database.access_role(identity.username) == "admin"
    ):
        raise _detail(403, "该操作仅限 Dashboard 管理员。")
    return identity

def _intent_identity(request: Request, permission: str = "view"):
    """Independent intent capability; neither SSO nor navigation grants writes."""

    identity = request_identity(request, settings)
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
