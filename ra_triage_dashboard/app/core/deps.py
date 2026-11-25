"""Standard FastAPI Depends() providers for services and verified RBAC identities."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from fastapi import Request
from fastapi.params import Depends as DependsParam

from ..auth import SessionIdentity
from ..support.identity import (
    _admin_identity,
    _intent_identity,
    _resolve_request_identity_and_role,
    _writer_identity,
)
from .container import AppContainer

T = TypeVar("T")


def resolve_dep(value: Any, fallback: Callable[[], T]) -> T:
    """Support both FastAPI DI and direct Python handler invocations in legacy tests."""
    if value is None or isinstance(value, DependsParam):
        return fallback()
    return value


def get_container(request: Request) -> AppContainer:
    """Return the active AppContainer, preferring explicit app.state overrides."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None) if app is not None else None
    container = getattr(state, "container", None) if state is not None else None
    if isinstance(container, AppContainer):
        if getattr(container, "_tracks_runtime", False):
            return AppContainer.from_runtime()
        return container
    return AppContainer.from_runtime()


def get_settings(request: Request) -> Any:
    return get_container(request).settings


def get_db(request: Request) -> Any:
    return get_container(request).database


def get_session_factory(request: Request) -> Any:
    return get_container(request).session_factory


def get_case_repo(request: Request) -> Any:
    return get_container(request).cases_repo


def get_campaign_repo(request: Request) -> Any:
    return get_container(request).campaigns_repo


def get_work_split_repo(request: Request) -> Any:
    return get_container(request).work_splits_repo


def get_media_registry(request: Request) -> Any:
    return get_container(request).media_registry


def get_baseline_registry(request: Request) -> Any:
    return get_container(request).baseline_registry


async def require_session(request: Request) -> tuple[SessionIdentity, str]:
    """Resolve current identity and access role, reusing middleware auth cache."""
    return await asyncio.to_thread(_resolve_request_identity_and_role, request)


async def require_writer(request: Request) -> SessionIdentity:
    """FastAPI Depends guard requiring verified writer or admin access."""
    return await asyncio.to_thread(_writer_identity, request)


async def require_admin(request: Request) -> SessionIdentity:
    """FastAPI Depends guard requiring verified Dashboard administrator access."""
    return await asyncio.to_thread(_admin_identity, request)


def require_intent_perm(permission: str = "view") -> Callable[[Request], Any]:
    """Factory returning a FastAPI Depends guard for an intent capability level."""

    async def _guard(request: Request) -> SessionIdentity:
        return await asyncio.to_thread(_intent_identity, request, permission)

    return _guard
