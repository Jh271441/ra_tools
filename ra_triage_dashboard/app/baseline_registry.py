"""Multi-baseline registry: immutable GT worksets and short-id mapping.

This module is configuration-only: it does not load Excel rows or touch the DB.
Bootstrap and media providers consume the parsed registry at startup.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_ENV_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class BaselineMediaConfig:
    provider: str
    layout_id: str = ""
    bev_frames_root: Path | None = None
    animation_root: Path | None = None
    animation_job_ids: tuple[int, ...] = ()
    camera_root: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BaselineEntry:
    id: str
    label: str
    scope: str
    loader: str
    xlsx: Path
    dataset: str = ""
    default_selected: bool = False
    media: BaselineMediaConfig = field(
        default_factory=lambda: BaselineMediaConfig(provider="product_layout")
    )
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BaselineRegistry:
    entries: tuple[BaselineEntry, ...]
    source_path: Path | None = None

    def by_id(self, baseline_id: str) -> BaselineEntry | None:
        key = str(baseline_id or "").strip()
        for entry in self.entries:
            if entry.id == key:
                return entry
        return None

    def by_scope(self, scope: str) -> BaselineEntry | None:
        key = str(scope or "").strip()
        for entry in self.entries:
            if entry.scope == key:
                return entry
        return None

    def id_to_scope(self, baseline_id: str) -> str | None:
        entry = self.by_id(baseline_id)
        return entry.scope if entry else None

    def scope_to_id(self, scope: str) -> str | None:
        entry = self.by_scope(scope)
        return entry.id if entry else None

    def default_ids(self) -> list[str]:
        selected = [entry.id for entry in self.entries if entry.default_selected]
        if selected:
            return selected
        return [self.entries[0].id] if self.entries else []

    def allowed_ids(self) -> set[str]:
        return {entry.id for entry in self.entries}

    def allowed_scopes(self) -> set[str]:
        return {entry.scope for entry in self.entries}

    def public_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "id": entry.id,
                "label": entry.label,
                "scope": entry.scope,
                "loader": entry.loader,
                "dataset": entry.dataset,
                "default_selected": entry.default_selected,
                "media_provider": entry.media.provider,
            }
            for entry in self.entries
        ]


def expand_path_template(value: str, env: Mapping[str, str] | None = None) -> str:
    """Replace ``${VAR}`` tokens using the process environment (or override map)."""

    mapping = env if env is not None else os.environ

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in mapping or mapping[name] is None:
            raise ValueError(f"baseline path template references unset env {name}")
        return str(mapping[name])

    return _ENV_TOKEN.sub(repl, str(value or ""))


def resolve_path(value: str, *, env: Mapping[str, str] | None = None) -> Path:
    expanded = expand_path_template(value, env=env)
    return Path(expanded).expanduser()


def normalize_baseline_ids(
    raw: Any,
    *,
    allowed: set[str] | Sequence[str],
    default: Sequence[str],
) -> list[str]:
    """Parse CSV / list / repeated values into ordered unique short ids.

    Empty input falls back to ``default``. Unknown ids are dropped; if nothing
    valid remains, ``default`` is used. Empty default is rejected.
    """

    allowed_set = {str(item).strip() for item in allowed if str(item).strip()}
    default_ids = [
        item
        for item in dict.fromkeys(str(x).strip() for x in default if str(x).strip())
        if item in allowed_set
    ]
    if not default_ids and allowed_set:
        # Last resort: first allowed id for fail-open empty configs.
        default_ids = [next(iter(sorted(allowed_set)))]
    if not default_ids:
        raise ValueError("baseline default ids are empty")

    values: list[str] = []
    if raw is None or raw == "":
        return list(default_ids)
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            text = str(item or "").strip()
            if not text:
                continue
            if "," in text:
                values.extend(part.strip() for part in text.split(",") if part.strip())
            else:
                values.append(text)
    else:
        text = str(raw).strip()
        if text:
            values.extend(part.strip() for part in text.split(",") if part.strip())

    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in allowed_set or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered or list(default_ids)


def ids_to_scopes(ids: Sequence[str], registry: BaselineRegistry) -> list[str]:
    scopes: list[str] = []
    for baseline_id in ids:
        scope = registry.id_to_scope(baseline_id)
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def _parse_media(raw: Mapping[str, Any] | None, *, env: Mapping[str, str] | None) -> BaselineMediaConfig:
    data = dict(raw or {})
    provider = str(data.get("provider") or "product_layout").strip() or "product_layout"
    layout_id = str(data.get("layout_id") or "").strip()
    job_ids_raw = data.get("animation_job_ids") or []
    job_ids: list[int] = []
    if isinstance(job_ids_raw, (list, tuple)):
        for item in job_ids_raw:
            try:
                job_ids.append(int(item))
            except (TypeError, ValueError):
                continue

    def optional_path(key: str) -> Path | None:
        value = data.get(key)
        if value in (None, ""):
            return None
        return resolve_path(str(value), env=env)

    known = {
        "provider",
        "layout_id",
        "bev_frames_root",
        "animation_root",
        "animation_job_ids",
        "camera_root",
    }
    extra = {key: value for key, value in data.items() if key not in known}
    return BaselineMediaConfig(
        provider=provider,
        layout_id=layout_id,
        bev_frames_root=optional_path("bev_frames_root"),
        animation_root=optional_path("animation_root"),
        animation_job_ids=tuple(job_ids),
        camera_root=optional_path("camera_root"),
        extra=extra,
    )


def _parse_entry(raw: Mapping[str, Any], *, env: Mapping[str, str] | None) -> BaselineEntry:
    baseline_id = str(raw.get("id") or "").strip()
    if not _ID_RE.fullmatch(baseline_id):
        raise ValueError(f"invalid baseline id: {baseline_id!r}")
    label = str(raw.get("label") or baseline_id).strip() or baseline_id
    scope = str(raw.get("scope") or "").strip()
    if not scope:
        raise ValueError(f"baseline {baseline_id} missing scope")
    loader = str(raw.get("loader") or "").strip()
    if loader not in {"trail_label_baseline", "spotcheck_zh"}:
        raise ValueError(f"baseline {baseline_id} has unsupported loader {loader!r}")
    xlsx_raw = str(raw.get("xlsx") or "").strip()
    if not xlsx_raw:
        raise ValueError(f"baseline {baseline_id} missing xlsx")
    xlsx = resolve_path(xlsx_raw, env=env)
    dataset = str(raw.get("dataset") or "").strip()
    default_selected = bool(raw.get("default_selected"))
    media = _parse_media(raw.get("media") if isinstance(raw.get("media"), dict) else {}, env=env)
    return BaselineEntry(
        id=baseline_id,
        label=label,
        scope=scope,
        loader=loader,
        xlsx=xlsx,
        dataset=dataset,
        default_selected=default_selected,
        media=media,
        raw=dict(raw),
    )


def load_baseline_registry(
    path: Path | None,
    *,
    env: Mapping[str, str] | None = None,
    ra_auto_triage_root: Path | None = None,
) -> BaselineRegistry:
    """Load a baselines JSON file.

    When ``path`` is None or missing, return an empty registry (callers should
    fall back to legacy single-scope Settings fields).
    """

    if path is None:
        return BaselineRegistry(entries=())
    path = Path(path).expanduser()
    if not path.is_file():
        return BaselineRegistry(entries=(), source_path=path)

    env_map: dict[str, str]
    if env is not None:
        env_map = {str(k): str(v) for k, v in env.items()}
    else:
        env_map = {str(k): str(v) for k, v in os.environ.items()}
    if ra_auto_triage_root is not None:
        env_map.setdefault("RA_AUTO_TRIAGE_ROOT", str(ra_auto_triage_root))

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"baselines registry must be a non-empty list: {path}")

    entries: list[BaselineEntry] = []
    seen_ids: set[str] = set()
    seen_scopes: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"baselines[{index}] must be an object")
        entry = _parse_entry(item, env=env_map)
        if entry.id in seen_ids:
            raise ValueError(f"duplicate baseline id: {entry.id}")
        if entry.scope in seen_scopes:
            raise ValueError(f"duplicate baseline scope: {entry.scope}")
        seen_ids.add(entry.id)
        seen_scopes.add(entry.scope)
        entries.append(entry)
    return BaselineRegistry(entries=tuple(entries), source_path=path)


def legacy_registry_from_settings(
    *,
    baseline_id: str = "0508",
    label: str = "0508",
    scope: str,
    dataset: str,
    xlsx: Path,
    media_provider: str = "product_layout",
    layout_id: str = "",
) -> BaselineRegistry:
    """Build a one-entry registry from legacy single-scope Settings fields."""

    entry = BaselineEntry(
        id=baseline_id,
        label=label or baseline_id,
        scope=scope,
        loader="trail_label_baseline",
        xlsx=Path(xlsx),
        dataset=dataset,
        default_selected=True,
        media=BaselineMediaConfig(
            provider=media_provider,
            layout_id=layout_id or scope,
        ),
    )
    return BaselineRegistry(entries=(entry,), source_path=None)


def detect_issue_scope_overlaps(
    memberships: Iterable[tuple[str, str]],
) -> dict[str, list[str]]:
    """Return ``issue_id → [scopes…]`` for ids that appear under >1 scope."""

    by_issue: dict[str, list[str]] = {}
    for issue_id, scope in memberships:
        issue = str(issue_id or "").strip()
        scope_key = str(scope or "").strip()
        if not issue or not scope_key:
            continue
        bucket = by_issue.setdefault(issue, [])
        if scope_key not in bucket:
            bucket.append(scope_key)
    return {issue: scopes for issue, scopes in by_issue.items() if len(scopes) > 1}
