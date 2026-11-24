"""Compatibility re-export of unified settings from `app.infra.settings`."""

from __future__ import annotations

from app.infra.settings import (
    AppSettings as Settings,
    BACKEND_DIR,
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_REPORT_DIR,
    ROOT_DIR,
    config_hash,
    load_versions_config,
    mock_data_disabled,
    settings,
    ssl_verify_setting,
)

__all__ = [
    "BACKEND_DIR",
    "CONFIG_DIR",
    "DATA_DIR",
    "DEFAULT_REPORT_DIR",
    "ROOT_DIR",
    "Settings",
    "config_hash",
    "load_versions_config",
    "mock_data_disabled",
    "settings",
    "ssl_verify_setting",
]
