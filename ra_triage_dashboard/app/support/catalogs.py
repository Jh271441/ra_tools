"""Catalogs HTTP helpers."""

from __future__ import annotations

import re
from typing import Any

from ..runtime import (
    MISSING_EVIDENCE_CATALOG,
    REVIEW_TAG_ALIASES,
    REVIEW_TAG_CATALOG,
    REVIEW_TAG_MANAGED_GROUPS,
    database,
)
from .common import _as_text, _detail


def _review_tag_catalog() -> tuple[dict[str, Any], ...]:
    """Return built-in tags plus shared scene tags from the database.

    Built-ins remain source-controlled, but a database row can override their
    label/hint/group or soft-delete them (same pattern as missing evidence).
    """

    merged: dict[str, dict[str, Any]] = {
        str(item["key"]): {
            **item,
            "builtin": True,
            "deleted": False,
        }
        for item in REVIEW_TAG_CATALOG
    }
    builtin_keys = set(merged)
    for row in database.list_review_tag_catalog(include_inactive=True):
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        item = {
            str(name): value
            for name, value in row.items()
            if str(name) != "active"
        }
        if "group_key" in item and "group" not in item:
            item["group"] = item.pop("group_key")
        item.setdefault("section", "scene")
        item.setdefault("group", "environment")
        item.setdefault("hint", "")
        item["builtin"] = key in builtin_keys
        item["deleted"] = not bool(row.get("active", 1))
        if key in merged:
            merged[key].update(item)
            merged[key]["builtin"] = True
        else:
            merged[key] = item
    return tuple(merged.values())

def _missing_evidence_catalog() -> tuple[dict[str, Any], ...]:
    """Return the merged catalog, including soft-deleted historical entries.

    Built-ins remain source-controlled, but a database row can override their
    label/hint or retire them.  Retired entries stay in the payload so old
    annotations remain readable; the Review form hides them unless selected
    by the current version.
    """

    merged: dict[str, dict[str, Any]] = {
        str(item["key"]): {
            **item,
            "builtin": True,
            "deleted": False,
        }
        for item in MISSING_EVIDENCE_CATALOG
    }
    builtin_keys = set(merged)
    for row in database.list_missing_evidence_catalog(include_inactive=True):
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        item = {
            str(name): value
            for name, value in row.items()
            if str(name) != "active"
        }
        item["builtin"] = key in builtin_keys
        item["deleted"] = not bool(row.get("active", 1))
        if key in merged:
            merged[key].update(item)
            merged[key]["builtin"] = True
        else:
            merged[key] = item
    return tuple(merged.values())

def _csv_filter_values(
    raw: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if raw is None:
        return ()
    parts = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    for part in parts:
        text = _as_text(part).strip()
        if text:
            values.append(text)
    return tuple(dict.fromkeys(values))

def resolve_review_exclusion_filter(value: str = "") -> tuple[str, bool | None]:
    """Normalize the analysis Issue-exclusion slice.

    ``all`` is deliberately the default: exclusion is a review dimension, not
    a data deletion rule.  The two explicit slices remain useful for auditing
    model-problem cases separately from Issues that were manually shielded.
    A few boolean aliases are accepted for bookmarked/API clients from the
    previous hard-filter release.
    """

    normalized = _as_text(value).strip().casefold() or "all"
    aliases = {
        "all": "all",
        "any": "all",
        "included": "included",
        "include": "included",
        "not_excluded": "included",
        "false": "included",
        "0": "included",
        "excluded": "excluded",
        "exclude": "excluded",
        "only_excluded": "excluded",
        "true": "excluded",
        "1": "excluded",
    }
    canonical = aliases.get(normalized)
    if canonical is None:
        raise _detail(
            400,
            "exclusion 仅支持 all、included 或 excluded。",
        )
    return canonical, {"all": None, "included": False, "excluded": True}[canonical]

def _parse_issue_id_filter(raw: str) -> list[str]:
    tokens = re.split(r"[\s,;|]+", _as_text(raw))
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        issue_id = token.strip()
        if not issue_id or issue_id in seen:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", issue_id):
            continue
        seen.add(issue_id)
        cleaned.append(issue_id)
        if len(cleaned) >= 2000:
            break
    return cleaned

def _review_tag_payload(
    item: dict[str, Any], *, builtin: bool = False
) -> dict[str, Any]:
    payload = {
        **item,
        "builtin": bool(item.get("builtin", builtin)),
        "deleted": not bool(item.get("active", 1))
        if "active" in item
        else bool(item.get("deleted", False)),
    }
    payload.pop("active", None)
    payload.setdefault("section", "scene")
    payload.setdefault("group", payload.pop("group_key", "environment"))
    payload.setdefault("hint", "")
    return payload

def _validate_review_tag_input(
    body: dict[str, Any], *, default_group: str = "environment"
) -> tuple[str, str, str, str]:
    """Return (label, hint, group, section) for managed Issue-tag rows."""

    label = _as_text(body.get("label"))
    hint = _as_text(body.get("hint"))
    group = _as_text(body.get("group") or default_group)
    if not label:
        raise _detail(400, "场景标签标题不能为空。")
    if len(label) > 48 or re.search(r"[\x00-\x1f\x7f]", label):
        raise _detail(400, "场景标签标题长度或字符不合法。")
    if len(hint) > 160 or re.search(r"[\x00-\x1f\x7f]", hint):
        raise _detail(400, "场景标签说明长度或字符不合法。")
    section = REVIEW_TAG_MANAGED_GROUPS.get(group)
    if section is None:
        raise _detail(400, "场景标签分组不合法。")
    return label, hint, group, section

def _normalise_review_tags(values: list[Any]) -> list[str]:
    if len(values) > 24:
        raise _detail(400, "每条 review 最多选择 24 个 tags。")
    catalog_keys = {str(item["key"]) for item in _review_tag_catalog()}
    normalized: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        if len(raw) > 48 or re.search(r"[\x00-\x1f\x7f]", raw):
            raise _detail(400, "tag 长度或字符不合法。")
        key = REVIEW_TAG_ALIASES.get(raw, raw)
        if key in catalog_keys:
            normalized.add(key)
        else:
            raise _detail(400, "tag 不在默认场景 Tags 目录中。")
    return [item["key"] for item in _review_tag_catalog() if item["key"] in normalized]

def _normalise_missing_evidence(values: list[Any]) -> list[str]:
    if len(values) > 24:
        raise _detail(400, "每条 review 最多选择 24 个缺失信息。")
    catalog_keys = {str(item["key"]) for item in _missing_evidence_catalog()}
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw or raw in seen:
            continue
        if len(raw) > 160 or re.search(r"[\x00-\x1f\x7f]", raw):
            raise _detail(400, "缺失信息字段长度或字符不合法。")
        # Legacy per-Review custom values remain readable and editable. New
        # values are opaque keys from the shared catalog above.
        if raw not in catalog_keys and not raw.startswith("custom:"):
            raise _detail(400, "缺失信息不在共享目录中。")
        seen.add(raw)
        normalized.append(raw)
    return normalized

def _normalise_review_excluded(value: Any) -> bool:
    """Parse the explicit Issue-level exclusion flag without truthiness traps."""

    if value is None or value is False or value == 0:
        return False
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"", "0", "false", "no", "否", "不排除"}:
            return False
        if normalized in {"1", "true", "yes", "是", "排除"}:
            return True
    raise _detail(400, "is_excluded 必须是布尔值。")
