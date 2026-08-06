from __future__ import annotations

import re


BASE_PATH_TOKEN = "{{RA_TRIAGE_BASE_PATH}}"
_BASE_PATH_RE = re.compile(r"^(/[A-Za-z0-9._-]+)*$")


def normalize_base_path(value: str | None) -> str:
    """Return a safe, trailing-slash-free public URL prefix."""

    raw = "" if value is None else str(value)
    if raw in {"", "/"}:
        return ""
    if raw.endswith("/"):
        raw = raw[:-1]
    if not _BASE_PATH_RE.fullmatch(raw):
        raise RuntimeError(
            "DASHBOARD_BASE_PATH 必须为空或形如 /dashboard 的路径前缀。"
        )
    if ".." in raw:
        raise RuntimeError("DASHBOARD_BASE_PATH 不能包含 ..。")
    return raw


def with_base_path(base_path: str, path: str) -> str:
    """Prefix one application-local absolute path, idempotently."""

    if path.startswith(("http://", "https://", "//")):
        return path
    if not path.startswith("/"):
        raise ValueError("应用路径必须以 / 开头。")
    base = normalize_base_path(base_path)
    if not base:
        return path
    if path == base or path.startswith((f"{base}/", f"{base}?", f"{base}#")):
        return path
    return f"{base}{path}"


def render_index_html(template: str, base_path: str) -> str:
    """Inject the validated public prefix into explicit shell placeholders."""

    if BASE_PATH_TOKEN not in template:
        raise RuntimeError("index.html 缺少 RA Triage base path 占位符。")
    return template.replace(BASE_PATH_TOKEN, normalize_base_path(base_path))
