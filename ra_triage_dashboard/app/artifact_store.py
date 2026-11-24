"""File-backed dynamic artifact catalog and sandboxed HTML frame renderer.

Dynamic artifacts live under ``DASHBOARD_DATA_DIR/artifacts`` with advisory
file locking and atomic file replacement so CLI/hook syncs and FastAPI web
management stay safe across concurrent processes without database migrations.
Built-in static artifacts (such as ``architecture-original-330``) remain
immutable on disk while participating in the unified portal catalog.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .contracts import (
    ARTIFACT_GROUP_RE,
    ARTIFACT_SLUG_RE,
    DEFAULT_ARTIFACT_PAGE_SIZE,
    MAX_ARTIFACT_HTML_BYTES,
    MAX_ARTIFACT_PAGE_SIZE,
    MAX_ARTIFACT_TAGS,
)
from .web_paths import normalize_base_path, with_base_path


RESERVED_ARTIFACT_SLUGS = frozenset(
    {
        "api",
        "static",
        "upload",
        "new",
        "health",
        "frame",
        "raw",
        "index",
        "export",
        "settings",
    }
)

DEFAULT_GROUP_LABELS: dict[str, tuple[str, str]] = {
    "vlm-architecture": ("VLM & PIPO 架构", "VLM & PIPO Architecture"),
    "workbench-ui": ("Workbench UI 原型", "Workbench UI Mockups"),
    "data-analysis": ("数据分析与评测", "Data Analysis & Evals"),
    "system-design": ("系统与流程设计", "System & Workflow Design"),
    "general": ("其他图表", "General Diagrams"),
}

BUILTIN_ARTIFACTS: dict[str, dict[str, Any]] = {
    "architecture-original-330": {
        "slug": "architecture-original-330",
        "title": "Original330 VLM 架构与推理流程图",
        "title_en": "Original330 VLM Architecture & Inference Flowchart",
        "summary": "Original330 VLM 多帧推理、LoRA 旁路、工程后处理与规则联动交互流程图（含高清 SVG / PNG 导出）。",
        "summary_en": "Interactive Original330 VLM multi-frame inference, LoRA adapter, and engineering pipeline flowchart with SVG/PNG exports.",
        "group": "vlm-architecture",
        "group_label": "VLM & PIPO 架构",
        "group_label_en": "VLM & PIPO Architecture",
        "tags": ["Original330", "VLM", "LoRA", "Flowchart"],
        "conversation_id": "a48156b5-c788-4588-9f9f-92fb205fd4a5",
        "conversation_label": "Original330 VLM Flowchart",
        "source_filename": "original330_vlm_flowchart_interactive.html",
        "source_host": "builtin",
        "source_path": "static/artifacts/architecture-original-330/index.html",
        "builtin": True,
        "url_path": "/architecture-original-330",
        "pinned": True,
        "archived": False,
        "revision": 1,
        "created_at": "2026-11-23T07:34:00Z",
        "updated_at": "2026-11-23T07:34:00Z",
        "source_updated_at": "2026-11-23T07:34:00Z",
        "updated_by": "builtin",
    }
}

MANUAL_EDITABLE_FIELDS = frozenset(
    {
        "title",
        "title_en",
        "summary",
        "summary_en",
        "group",
        "group_label",
        "group_label_en",
        "tags",
        "pinned",
        "archived",
    }
)

_TAILWIND_CDN_SCRIPT_RE = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*["']https?://(?:www\.gstatic\.com/antigravity/[^"']*tailwindcss[^"']*|cdn\.tailwindcss\.com[^"']*)["'][^>]*>\s*</script>""",
    re.IGNORECASE,
)
_EXTERNAL_FONT_LINK_RE = re.compile(
    r"""<link\b[^>]*\bhref\s*=\s*["']https?://(?:fonts\.googleapis\.com|fonts\.gstatic\.com|www\.gstatic\.com)[^"']*["'][^>]*>""",
    re.IGNORECASE,
)
_HTML_OPEN_TAG_RE = re.compile(r"<html\b([^>]*)>", re.IGNORECASE)
_HEAD_OPEN_TAG_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_BODY_CLOSE_TAG_RE = re.compile(r"</body\s*>", re.IGNORECASE)
_TITLE_TAG_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HEADING_TAG_RE = re.compile(r"<h[12]\b[^>]*>(.*?)</h[12]>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_STRIP_RE = re.compile(r"<[^>]+>")

TAILWIND_INLINE_SLOT = "<!--RA_TAILWIND_INLINE_SLOT-->"
FRAME_RENDERER_VERSION = "r3"
MAX_INLINE_FRAME_HTML_BYTES = 256 * 1024


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_artifact_slug(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw or ".." in raw or "/" in raw or "\\" in raw:
        raise ValueError(
            "Artifact slug 不能包含路径分隔符或 '..'。"
        )
    raw = re.sub(r"[_\s]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if not ARTIFACT_SLUG_RE.fullmatch(raw) or raw in RESERVED_ARTIFACT_SLUGS:
        raise ValueError(
            "Artifact slug 必须为 2-96 位小写字母、数字或连字符，且不能使用保留名称。"
        )
    return raw


def normalize_artifact_group(
    group: str | None,
    *,
    group_label: str | None = None,
    group_label_en: str | None = None,
) -> tuple[str, str, str]:
    raw = str(group or "").strip().lower()
    if not raw:
        raw = "general"
    raw = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    if not raw or not ARTIFACT_GROUP_RE.fullmatch(raw):
        raw = "general"
    default_zh, default_en = DEFAULT_GROUP_LABELS.get(
        raw,
        (raw.replace("-", " ").title(), raw.replace("-", " ").title()),
    )
    zh = _clean_text(group_label, max_len=64) or default_zh
    en = _clean_text(group_label_en, max_len=64) or default_en
    return raw, zh, en


def _clean_text(value: Any, *, max_len: int) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:max_len]


def _clean_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [part.strip() for part in re.split(r"[,，;\n]+", raw)]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(part).strip() for part in raw]
    else:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = _clean_text(item, max_len=36)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= MAX_ARTIFACT_TAGS:
            break
    return result


def infer_title_from_html(html_text: str, fallback: str) -> str:
    match = _TITLE_TAG_RE.search(html_text)
    if match:
        candidate = _clean_text(_HTML_TAG_STRIP_RE.sub(" ", match.group(1)), max_len=140)
        if candidate:
            return candidate
    match = _HEADING_TAG_RE.search(html_text)
    if match:
        candidate = _clean_text(_HTML_TAG_STRIP_RE.sub(" ", match.group(1)), max_len=140)
        if candidate:
            return candidate
    return _clean_text(fallback, max_len=140) or "Untitled Artifact"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def _frame_theme_style() -> str:
    return """<style id="ra-agy-theme-tokens">
:root {
  color-scheme: dark;
  --background: #0b0e14;
  --content: #0f141e;
  --card: #131926;
  --sidebar: #101520;
  --card-border: #253042;
  --border: #2c384d;
  --foreground: #edf2fb;
  --muted-foreground: #94a3b8;
  --placeholder: #64748b;
  --code-foreground: #7dd3fc;
  --primary: #22d3ee;
  --primary-foreground: #051923;
  --secondary: #1b2434;
  --secondary-foreground: #e2e8f0;
  --accent: #24d3ef;
  --link: #38bdf8;
  --success: #34d399;
  --warning: #fbbf24;
  --error: #f87171;
  --chart-1: #38bdf8;
  --chart-2: #a78bfa;
  --chart-3: #fb923c;
  --chart-4: #34d399;
  --chart-5: #f472b6;
  --chart-6: #fbbf24;
}
html.light,
html[data-color-theme="light"] {
  color-scheme: light;
  --background: #eef2f7;
  --content: #f8fafc;
  --card: #ffffff;
  --sidebar: #f1f5f9;
  --card-border: #d5dfec;
  --border: #c5d0de;
  --foreground: #0f172a;
  --muted-foreground: #475569;
  --placeholder: #64748b;
  --code-foreground: #0369a1;
  --primary: #08758d;
  --primary-foreground: #ffffff;
  --secondary: #e8eff7;
  --secondary-foreground: #1e293b;
  --accent: #08758d;
  --link: #0369a1;
  --success: #059669;
  --warning: #d97706;
  --error: #dc2626;
  --chart-1: #0284c7;
  --chart-2: #7c3aed;
  --chart-3: #ea580c;
  --chart-4: #059669;
  --chart-5: #db2777;
  --chart-6: #d97706;
}
html {
  height: auto !important;
  min-height: 0 !important;
  padding: 16px 20px 26px;
  box-sizing: border-box;
  background: transparent;
}
body {
  height: auto !important;
  min-height: 0 !important;
  margin: 0;
  background: transparent;
  color: var(--foreground);
  font-family: Inter, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  overflow-x: auto;
}
@media (max-width: 639px) {
  html { padding: 10px 10px 20px; }
}
</style>"""


def _frame_bridge_script() -> str:
    return """<script id="ra-agy-bridge">
(() => {
  const applyTheme = (mode) => {
    const isLight = String(mode || "").toLowerCase() === "light";
    document.documentElement.classList.toggle("light", isLight);
    document.documentElement.dataset.colorTheme = isLight ? "light" : "dark";
    document.documentElement.style.colorScheme = isLight ? "light" : "dark";
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: isLight ? "light" : "dark" } }));
  };

  let lastPostedHeight = 0;
  let rafId = 0;
  const measureHeight = () => {
    const htmlStyle = window.getComputedStyle(document.documentElement);
    const padTop = parseFloat(htmlStyle.paddingTop) || 0;
    const padBottom = parseFloat(htmlStyle.paddingBottom) || 0;
    const bodyRect = document.body ? document.body.getBoundingClientRect() : null;
    const bodyScroll = document.body ? document.body.scrollHeight : 0;
    const raw = Math.max(bodyRect ? bodyRect.height : 0, bodyScroll);
    return Math.max(180, Math.ceil(raw + padTop + padBottom + 4));
  };

  const postHeight = (force = false) => {
    if (window.parent === window) return;
    const height = measureHeight();
    if (!force && Math.abs(height - lastPostedHeight) < 2) return;
    lastPostedHeight = height;
    window.parent.postMessage({ type: "ra-artifact-height", height }, "*");
  };

  const scheduleMeasure = () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      postHeight(false);
    });
  };

  window.addEventListener("message", (event) => {
    const data = event && event.data;
    if (!data || typeof data !== "object") return;
    if (data.type === "ra-artifact-theme") {
      applyTheme(data.theme);
      setTimeout(() => postHeight(true), 40);
    } else if (data.type === "ra-artifact-ping") {
      postHeight(true);
    }
  });

  window.addEventListener("keydown", (event) => {
    if (window.parent === window) return;
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    const tag = target && target.tagName ? String(target.tagName).toUpperCase() : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable)) return;
    if (event.key === "ArrowLeft" || event.key === "[") {
      event.preventDefault();
      window.parent.postMessage({ type: "ra-artifact-nav", dir: -1 }, "*");
    } else if (event.key === "ArrowRight" || event.key === "]") {
      event.preventDefault();
      window.parent.postMessage({ type: "ra-artifact-nav", dir: 1 }, "*");
    }
  });

  let readySent = false;
  const postReady = () => {
    if (window.parent === window) return;
    const height = measureHeight();
    lastPostedHeight = height;
    if (!readySent) {
      readySent = true;
      window.parent.postMessage({ type: "ra-artifact-ready", height }, "*");
    } else {
      window.parent.postMessage({ type: "ra-artifact-height", height }, "*");
    }
  };

  if (typeof ResizeObserver === "function" && document.body) {
    new ResizeObserver(scheduleMeasure).observe(document.body);
  }
  if (typeof MutationObserver === "function" && document.body) {
    new MutationObserver(scheduleMeasure).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
    });
  }
  window.addEventListener("load", () => {
    requestAnimationFrame(() => postReady());
    setTimeout(() => postHeight(true), 120);
    setTimeout(() => postHeight(true), 420);
  });
  document.addEventListener("DOMContentLoaded", () => {
    requestAnimationFrame(() => postHeight(true));
    setTimeout(() => postReady(), 90);
  });
  setTimeout(() => postReady(), 180);
  setTimeout(() => postHeight(true), 450);
})();
</script>"""


def render_artifact_frame_html(
    raw_html: str,
    *,
    base_path: str | None = None,
    initial_theme: str = "dark",
    inline_tailwind_slot: bool = False,
) -> str:
    """Transform an Antigravity HTML artifact for intranet-safe sandboxed display."""
    theme = "light" if str(initial_theme or "").strip().lower() == "light" else "dark"
    if inline_tailwind_slot:
        rendered = _TAILWIND_CDN_SCRIPT_RE.sub(TAILWIND_INLINE_SLOT, raw_html)
    else:
        if base_path is None:
            # Relative from /artifacts/<slug>/frame -> /static/vendor/tailwindcss/tailwindcss.min.js
            # Works identically under strip-proxy prefixes (/manual/artifacts/<slug>/frame)
            # and direct-IP root deployments (/artifacts/<slug>/frame).
            vendor_tailwind = "../../static/vendor/tailwindcss/tailwindcss.min.js"
        else:
            normalized_base = normalize_base_path(base_path)
            vendor_tailwind = with_base_path(
                normalized_base,
                "/static/vendor/tailwindcss/tailwindcss.min.js",
            )
        rendered = _TAILWIND_CDN_SCRIPT_RE.sub(
            f'<script src="{vendor_tailwind}"></script>',
            raw_html,
        )
    rendered = _EXTERNAL_FONT_LINK_RE.sub("", rendered)

    # Inject initial theme class/attribute onto <html> so first paint has no flash.
    def _patch_html_tag(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        if theme == "light":
            if re.search(r'\bclass\s*=\s*"', attrs, re.IGNORECASE):
                attrs = re.sub(
                    r'(\bclass\s*=\s*")([^"]*)(")',
                    lambda m: f'{m.group(1)}{m.group(2)} light{m.group(3)}'
                    if "light" not in m.group(2).split()
                    else m.group(0),
                    attrs,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                attrs = f'{attrs} class="light"'
        if "data-color-theme=" not in attrs.lower():
            attrs = f'{attrs} data-color-theme="{theme}"'
        return f"<html{attrs}>"

    if _HTML_OPEN_TAG_RE.search(rendered):
        rendered = _HTML_OPEN_TAG_RE.sub(_patch_html_tag, rendered, count=1)
    else:
        html_cls = ' class="light"' if theme == "light" else ""
        rendered = f'<!DOCTYPE html><html lang="zh-CN"{html_cls} data-color-theme="{theme}"><head><meta charset="UTF-8" /></head><body>{rendered}</body></html>'

    csp_meta = (
        '<meta http-equiv="Content-Security-Policy" content="'
        "default-src 'none'; "
        "script-src 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'unsafe-inline'; "
        "img-src data: blob:; "
        "font-src data:; "
        "connect-src 'none'; "
        "object-src 'none';"
        '" />\n'
        if inline_tailwind_slot
        else ""
    )
    style_block = f"{csp_meta}{_frame_theme_style()}"
    if _HEAD_OPEN_TAG_RE.search(rendered):
        rendered = _HEAD_OPEN_TAG_RE.sub(
            lambda m: f"{m.group(0)}\n{style_block}\n",
            rendered,
            count=1,
        )
    else:
        rendered = f"{style_block}\n{rendered}"

    bridge_block = _frame_bridge_script()
    if _BODY_CLOSE_TAG_RE.search(rendered):
        rendered = _BODY_CLOSE_TAG_RE.sub(
            lambda m: f"\n{bridge_block}\n{m.group(0)}",
            rendered,
            count=1,
        )
    else:
        rendered = f"{rendered}\n{bridge_block}"
    return rendered


class ArtifactStore:
    """Atomic file-backed store for dynamic HTML artifacts + built-in catalog."""

    def __init__(self, artifacts_dir: Path, *, static_dir: Path | None = None):
        self.artifacts_dir = Path(artifacts_dir)
        self.static_dir = Path(static_dir) if static_dir is not None else None
        self.items_dir = self.artifacts_dir / "items"
        self.registry_path = self.artifacts_dir / "registry.json"
        self.lock_path = self.artifacts_dir / "registry.lock"

    def _ensure_layout(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.items_dir.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self, *, exclusive: bool) -> Iterator[None]:
        self._ensure_layout()
        with open(self.lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_registry_unlocked(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            return {"version": 1, "items": {}, "builtin_overrides": {}}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "items": {}, "builtin_overrides": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "items": {}, "builtin_overrides": {}}
        items = payload.get("items")
        overrides = payload.get("builtin_overrides")
        return {
            "version": 1,
            "items": items if isinstance(items, dict) else {},
            "builtin_overrides": overrides if isinstance(overrides, dict) else {},
        }

    def _write_registry_unlocked(self, registry: dict[str, Any]) -> None:
        payload = {
            "version": 1,
            "updated_at": _utc_now_iso(),
            "items": registry.get("items") or {},
            "builtin_overrides": registry.get("builtin_overrides") or {},
        }
        _atomic_write_text(
            self.registry_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def _builtin_item(self, slug: str, overrides: dict[str, Any]) -> dict[str, Any]:
        base = copy.deepcopy(BUILTIN_ARTIFACTS[slug])
        override = overrides.get(slug) if isinstance(overrides, dict) else None
        if isinstance(override, dict):
            for key in MANUAL_EDITABLE_FIELDS:
                if key in override:
                    base[key] = copy.deepcopy(override[key])
            if override.get("updated_at"):
                base["updated_at"] = override["updated_at"]
            if override.get("updated_by"):
                base["updated_by"] = override["updated_by"]
        if self.static_dir is not None and slug == "architecture-original-330":
            html_file = self.static_dir / "artifacts" / "architecture-original-330" / "index.html"
            if html_file.is_file():
                data = html_file.read_bytes()
                base["size_bytes"] = len(data)
                base["content_sha256"] = hashlib.sha256(data).hexdigest()
        base.setdefault("size_bytes", 0)
        base.setdefault("content_sha256", "")
        base["builtin"] = True
        base["url_path"] = BUILTIN_ARTIFACTS[slug]["url_path"]
        return base

    def _public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        builtin = bool(item.get("builtin"))
        url_path = item.get("url_path") if builtin else f"/artifacts/{slug}"
        group_id, group_zh, group_en = normalize_artifact_group(
            item.get("group"),
            group_label=item.get("group_label"),
            group_label_en=item.get("group_label_en"),
        )
        return {
            "slug": slug,
            "title": _clean_text(item.get("title"), max_len=160) or slug,
            "title_en": _clean_text(item.get("title_en"), max_len=160)
            or _clean_text(item.get("title"), max_len=160)
            or slug,
            "summary": _clean_text(item.get("summary"), max_len=600),
            "summary_en": _clean_text(item.get("summary_en"), max_len=600)
            or _clean_text(item.get("summary"), max_len=600),
            "group": group_id,
            "group_label": group_zh,
            "group_label_en": group_en,
            "tags": _clean_tags(item.get("tags")),
            "conversation_id": _clean_text(item.get("conversation_id"), max_len=80),
            "conversation_label": _clean_text(item.get("conversation_label"), max_len=120),
            "source_filename": _clean_text(item.get("source_filename"), max_len=160),
            "source_host": _clean_text(item.get("source_host"), max_len=80),
            "builtin": builtin,
            "url_path": url_path,
            "frame_path": "" if builtin else f"/artifacts/{slug}/frame",
            "pinned": bool(item.get("pinned")),
            "archived": bool(item.get("archived")),
            "revision": max(1, int(item.get("revision") or 1)),
            "size_bytes": max(0, int(item.get("size_bytes") or 0)),
            "content_sha256": str(item.get("content_sha256") or ""),
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
            "source_updated_at": str(item.get("source_updated_at") or ""),
            "updated_by": _clean_text(item.get("updated_by"), max_len=128),
        }

    def _all_items_unlocked(self, registry: dict[str, Any]) -> list[dict[str, Any]]:
        overrides = registry.get("builtin_overrides") or {}
        dynamic_items = registry.get("items") or {}
        combined: list[dict[str, Any]] = []
        for slug in BUILTIN_ARTIFACTS:
            combined.append(self._public_item(self._builtin_item(slug, overrides)))
        for slug, record in dynamic_items.items():
            if slug in BUILTIN_ARTIFACTS or not isinstance(record, dict):
                continue
            html_file = self.items_dir / slug / "source.html"
            if not html_file.is_file():
                continue
            rec = dict(record)
            rec["slug"] = slug
            rec["builtin"] = False
            combined.append(self._public_item(rec))
        return combined

    @staticmethod
    def _filter_and_order(
        all_items: list[dict[str, Any]],
        *,
        q: str = "",
        group: str = "",
        status: str = "active",
        sort: str = "updated_desc",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
        status_norm = str(status or "active").strip().lower()
        if status_norm not in {"active", "archived", "all"}:
            status_norm = "active"
        sort_norm = str(sort or "updated_desc").strip().lower()
        if sort_norm not in {"updated_desc", "updated_asc", "title_asc", "created_desc"}:
            sort_norm = "updated_desc"
        query = _clean_text(q, max_len=160).lower()
        group_filter = _clean_text(group, max_len=64).lower()

        active_count = sum(1 for item in all_items if not item["archived"])
        archived_count = sum(1 for item in all_items if item["archived"])

        status_filtered = [
            item
            for item in all_items
            if status_norm == "all"
            or (status_norm == "active" and not item["archived"])
            or (status_norm == "archived" and item["archived"])
        ]

        group_map: dict[str, dict[str, Any]] = {}
        for item in status_filtered:
            gid = item["group"]
            bucket = group_map.get(gid)
            if bucket is None:
                group_map[gid] = {
                    "id": gid,
                    "label": item["group_label"],
                    "label_en": item["group_label_en"],
                    "count": 1,
                }
            else:
                bucket["count"] += 1
        groups = sorted(
            group_map.values(),
            key=lambda g: (-g["count"], g["id"]),
        )

        filtered = status_filtered
        if group_filter and group_filter != "all":
            filtered = [item for item in filtered if item["group"] == group_filter]
        if query:
            terms = [term for term in query.split() if term]

            def _matches(item: dict[str, Any]) -> bool:
                haystack = " ".join(
                    [
                        item["slug"],
                        item["title"],
                        item["title_en"],
                        item["summary"],
                        item["summary_en"],
                        item["group"],
                        item["group_label"],
                        item["group_label_en"],
                        item["conversation_id"],
                        item["source_filename"],
                        " ".join(item["tags"]),
                    ]
                ).lower()
                return all(term in haystack for term in terms)

            filtered = [item for item in filtered if _matches(item)]

        if sort_norm == "updated_asc":
            filtered.sort(key=lambda item: (item["updated_at"], item["slug"]))
        elif sort_norm == "title_asc":
            filtered.sort(key=lambda item: (item["title"].lower(), item["slug"]))
        elif sort_norm == "created_desc":
            filtered.sort(key=lambda item: (item["created_at"], item["slug"]), reverse=True)
        else:
            filtered.sort(key=lambda item: (item["updated_at"], item["slug"]), reverse=True)
        pinned_items = [item for item in filtered if item["pinned"]]
        regular_items = [item for item in filtered if not item["pinned"]]
        ordered = pinned_items + regular_items
        return ordered, groups, active_count, archived_count

    @staticmethod
    def _neighbor_summary(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "slug": item["slug"],
            "title": item["title"],
            "title_en": item["title_en"],
            "group": item["group"],
            "group_label": item["group_label"],
            "group_label_en": item["group_label_en"],
            "url_path": item["url_path"],
            "builtin": bool(item.get("builtin")),
        }

    def list_artifacts(
        self,
        *,
        q: str = "",
        group: str = "",
        status: str = "active",
        sort: str = "updated_desc",
        page: int = 1,
        page_size: int = DEFAULT_ARTIFACT_PAGE_SIZE,
    ) -> dict[str, Any]:
        safe_page_size = max(1, min(MAX_ARTIFACT_PAGE_SIZE, int(page_size or DEFAULT_ARTIFACT_PAGE_SIZE)))
        safe_page = max(1, int(page or 1))

        with self._locked(exclusive=False):
            registry = self._read_registry_unlocked()
            all_items = self._all_items_unlocked(registry)

        ordered, groups, active_count, archived_count = self._filter_and_order(
            all_items,
            q=q,
            group=group,
            status=status,
            sort=sort,
        )

        total = len(ordered)
        total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        clamped_page = min(safe_page, total_pages)
        start = (clamped_page - 1) * safe_page_size
        page_items = ordered[start : start + safe_page_size]

        return {
            "items": page_items,
            "total": total,
            "page": clamped_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
            "groups": groups,
            "counts": {
                "active": active_count,
                "archived": archived_count,
                "all": len(all_items),
            },
        }

    def get_artifact_neighbors(
        self,
        slug: str,
        *,
        q: str = "",
        group: str = "",
        status: str = "active",
        sort: str = "updated_desc",
    ) -> dict[str, Any]:
        try:
            normalized = normalize_artifact_slug(slug)
        except ValueError:
            return {"index": 0, "total": 0, "prev": None, "next": None, "scope_matched": False}
        with self._locked(exclusive=False):
            registry = self._read_registry_unlocked()
            all_items = self._all_items_unlocked(registry)

        ordered, _, _, _ = self._filter_and_order(
            all_items,
            q=q,
            group=group,
            status=status,
            sort=sort,
        )
        pos = next((i for i, item in enumerate(ordered) if item["slug"] == normalized), -1)
        scope_matched = pos >= 0
        if pos < 0:
            # Fallback to full unfiltered catalog so archived or direct-linked items remain browsable.
            ordered, _, _, _ = self._filter_and_order(
                all_items,
                q="",
                group="",
                status="all",
                sort=sort,
            )
            pos = next((i for i, item in enumerate(ordered) if item["slug"] == normalized), -1)
        if pos < 0:
            return {"index": 0, "total": len(ordered), "prev": None, "next": None, "scope_matched": False}
        prev_item = self._neighbor_summary(ordered[pos - 1]) if pos > 0 else None
        next_item = self._neighbor_summary(ordered[pos + 1]) if pos + 1 < len(ordered) else None
        return {
            "index": pos + 1,
            "total": len(ordered),
            "prev": prev_item,
            "next": next_item,
            "scope_matched": scope_matched,
        }

    def get_artifact_bundle(
        self,
        slug: str,
        *,
        q: str = "",
        group: str = "",
        status: str = "active",
        sort: str = "updated_desc",
        include_frame: bool = False,
        max_inline_frame_bytes: int = MAX_INLINE_FRAME_HTML_BYTES,
    ) -> dict[str, Any] | None:
        """Read item metadata, neighbors, and optional slot-rendered frame in one lock pass."""
        try:
            normalized = normalize_artifact_slug(slug)
        except ValueError:
            return None
        with self._locked(exclusive=False):
            registry = self._read_registry_unlocked()
            all_items = self._all_items_unlocked(registry)
            item = next((entry for entry in all_items if entry["slug"] == normalized), None)
            if item is None:
                return None
            frame_html: str | None = None
            if include_frame and not item["builtin"]:
                html_file = self.items_dir / normalized / "source.html"
                if html_file.is_file() and html_file.stat().st_size <= max_inline_frame_bytes:
                    raw_html = html_file.read_text(encoding="utf-8")
                    frame_html = render_artifact_frame_html(
                        raw_html,
                        inline_tailwind_slot=True,
                        initial_theme="dark",
                    )

        ordered, _, _, _ = self._filter_and_order(
            all_items,
            q=q,
            group=group,
            status=status,
            sort=sort,
        )
        pos = next((i for i, entry in enumerate(ordered) if entry["slug"] == normalized), -1)
        scope_matched = pos >= 0
        if pos < 0:
            ordered, _, _, _ = self._filter_and_order(
                all_items,
                q="",
                group="",
                status="all",
                sort=sort,
            )
            pos = next((i for i, entry in enumerate(ordered) if entry["slug"] == normalized), -1)
        if pos < 0:
            navigation = {"index": 0, "total": len(ordered), "prev": None, "next": None, "scope_matched": False}
        else:
            navigation = {
                "index": pos + 1,
                "total": len(ordered),
                "prev": self._neighbor_summary(ordered[pos - 1]) if pos > 0 else None,
                "next": self._neighbor_summary(ordered[pos + 1]) if pos + 1 < len(ordered) else None,
                "scope_matched": scope_matched,
            }
        result: dict[str, Any] = {
            "item": item,
            "navigation": navigation,
            "renderer_version": FRAME_RENDERER_VERSION,
        }
        if frame_html is not None:
            result["frame_html"] = frame_html
        return result

    def get_artifact(self, slug: str) -> dict[str, Any] | None:
        try:
            normalized = normalize_artifact_slug(slug)
        except ValueError:
            return None
        with self._locked(exclusive=False):
            registry = self._read_registry_unlocked()
            if normalized in BUILTIN_ARTIFACTS:
                return self._public_item(
                    self._builtin_item(normalized, registry.get("builtin_overrides") or {})
                )
            record = (registry.get("items") or {}).get(normalized)
            if not isinstance(record, dict):
                return None
            if not (self.items_dir / normalized / "source.html").is_file():
                return None
            rec = dict(record)
            rec["slug"] = normalized
            rec["builtin"] = False
            return self._public_item(rec)

    def read_artifact_html(self, slug: str) -> tuple[dict[str, Any], str] | None:
        try:
            normalized = normalize_artifact_slug(slug)
        except ValueError:
            return None
        if normalized in BUILTIN_ARTIFACTS:
            return None
        with self._locked(exclusive=False):
            registry = self._read_registry_unlocked()
            record = (registry.get("items") or {}).get(normalized)
            html_file = self.items_dir / normalized / "source.html"
            if not isinstance(record, dict) or not html_file.is_file():
                return None
            html_text = html_file.read_text(encoding="utf-8")
            rec = dict(record)
            rec["slug"] = normalized
            rec["builtin"] = False
            return self._public_item(rec), html_text

    def upsert_artifact(
        self,
        *,
        slug: str,
        html_content: str,
        title: str | None = None,
        title_en: str | None = None,
        summary: str | None = None,
        summary_en: str | None = None,
        group: str | None = None,
        group_label: str | None = None,
        group_label_en: str | None = None,
        tags: Any = None,
        conversation_id: str | None = None,
        conversation_label: str | None = None,
        source_filename: str | None = None,
        source_host: str | None = None,
        source_path: str | None = None,
        source_updated_at: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        updated_by: str = "",
        preserve_manual_edits: bool = True,
    ) -> dict[str, Any]:
        normalized_slug = normalize_artifact_slug(slug)
        if normalized_slug in BUILTIN_ARTIFACTS:
            raise ValueError(f"内置 artifact '{normalized_slug}' 不可覆盖 HTML 内容。")
        if not isinstance(html_content, str) or not html_content.strip():
            raise ValueError("HTML 内容不能为空。")
        encoded = html_content.encode("utf-8")
        if len(encoded) > MAX_ARTIFACT_HTML_BYTES:
            raise ValueError(
                f"HTML 文件大小超过限制（最大 {MAX_ARTIFACT_HTML_BYTES // (1024 * 1024)} MiB）。"
            )
        content_sha = hashlib.sha256(encoded).hexdigest()
        now = _utc_now_iso()

        with self._locked(exclusive=True):
            registry = self._read_registry_unlocked()
            items = registry.setdefault("items", {})
            existing = items.get(normalized_slug) if isinstance(items.get(normalized_slug), dict) else None
            created = existing is None
            manual_fields = set(existing.get("manual_fields") or []) if existing else set()

            def _pick(field: str, incoming: Any, current: Any) -> Any:
                if preserve_manual_edits and field in manual_fields and existing is not None:
                    return current
                if incoming is None:
                    return current
                return incoming

            default_title = infer_title_from_html(
                html_content,
                source_filename or normalized_slug.replace("-", " ").title(),
            )
            resolved_title = _clean_text(
                _pick("title", title, existing.get("title") if existing else default_title),
                max_len=160,
            ) or default_title
            resolved_title_en = _clean_text(
                _pick("title_en", title_en, existing.get("title_en") if existing else resolved_title),
                max_len=160,
            ) or resolved_title
            resolved_summary = _clean_text(
                _pick("summary", summary, existing.get("summary") if existing else ""),
                max_len=600,
            )
            resolved_summary_en = _clean_text(
                _pick(
                    "summary_en",
                    summary_en,
                    existing.get("summary_en") if existing else resolved_summary,
                ),
                max_len=600,
            ) or resolved_summary
            resolved_group_raw = _pick("group", group, existing.get("group") if existing else "general")
            resolved_group_zh = _pick(
                "group_label",
                group_label,
                existing.get("group_label") if existing else None,
            )
            resolved_group_en = _pick(
                "group_label_en",
                group_label_en,
                existing.get("group_label_en") if existing else None,
            )
            group_id, group_zh, group_en = normalize_artifact_group(
                resolved_group_raw,
                group_label=resolved_group_zh,
                group_label_en=resolved_group_en,
            )
            resolved_tags = _clean_tags(
                _pick("tags", tags, existing.get("tags") if existing else [])
            )
            resolved_pinned = bool(
                _pick("pinned", pinned, existing.get("pinned") if existing else False)
            )
            resolved_archived = bool(
                _pick("archived", archived, existing.get("archived") if existing else False)
            )

            html_changed = (
                existing is None
                or existing.get("content_sha256") != content_sha
                or not (self.items_dir / normalized_slug / "source.html").is_file()
            )
            revision = 1 if existing is None else int(existing.get("revision") or 1) + (1 if html_changed else 0)
            source_ts = _clean_text(source_updated_at, max_len=64) or (
                existing.get("source_updated_at") if existing else now
            )

            new_record = {
                "slug": normalized_slug,
                "title": resolved_title,
                "title_en": resolved_title_en,
                "summary": resolved_summary,
                "summary_en": resolved_summary_en,
                "group": group_id,
                "group_label": group_zh,
                "group_label_en": group_en,
                "tags": resolved_tags,
                "conversation_id": _clean_text(
                    conversation_id if conversation_id is not None else (existing.get("conversation_id") if existing else ""),
                    max_len=80,
                ),
                "conversation_label": _clean_text(
                    conversation_label if conversation_label is not None else (existing.get("conversation_label") if existing else ""),
                    max_len=120,
                ),
                "source_filename": _clean_text(
                    source_filename if source_filename is not None else (existing.get("source_filename") if existing else f"{normalized_slug}.html"),
                    max_len=160,
                ),
                "source_host": _clean_text(
                    source_host if source_host is not None else (existing.get("source_host") if existing else ""),
                    max_len=80,
                ),
                "source_path": _clean_text(
                    source_path if source_path is not None else (existing.get("source_path") if existing else ""),
                    max_len=400,
                ),
                "pinned": resolved_pinned,
                "archived": resolved_archived,
                "revision": revision,
                "size_bytes": len(encoded),
                "content_sha256": content_sha,
                "created_at": (existing.get("created_at") if existing else None) or source_ts or now,
                "updated_at": now if (created or html_changed) else (existing.get("updated_at") or now),
                "source_updated_at": source_ts or now,
                "updated_by": _clean_text(updated_by, max_len=128)
                or (existing.get("updated_by") if existing else "sync"),
                "manual_fields": sorted(manual_fields),
            }

            meta_changed = existing is None or any(
                existing.get(k) != new_record.get(k)
                for k in (
                    "title",
                    "title_en",
                    "summary",
                    "summary_en",
                    "group",
                    "group_label",
                    "group_label_en",
                    "tags",
                    "conversation_id",
                    "conversation_label",
                    "source_filename",
                    "pinned",
                    "archived",
                )
            )
            unchanged = (not created) and (not html_changed) and (not meta_changed)
            if not unchanged:
                if not html_changed and not created:
                    new_record["updated_at"] = now
                item_dir = self.items_dir / normalized_slug
                if html_changed:
                    _atomic_write_text(item_dir / "source.html", html_content)
                _atomic_write_text(
                    item_dir / "meta.json",
                    json.dumps(new_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                )
                items[normalized_slug] = new_record
                self._write_registry_unlocked(registry)

            return {
                "item": self._public_item(new_record),
                "created": created,
                "unchanged": unchanged,
            }

    def update_artifact_metadata(
        self,
        slug: str,
        *,
        patch: dict[str, Any],
        updated_by: str = "",
    ) -> dict[str, Any] | None:
        normalized_slug = normalize_artifact_slug(slug)
        now = _utc_now_iso()
        with self._locked(exclusive=True):
            registry = self._read_registry_unlocked()
            if normalized_slug in BUILTIN_ARTIFACTS:
                overrides = registry.setdefault("builtin_overrides", {})
                current = dict(overrides.get(normalized_slug) or {})
                merged = self._builtin_item(normalized_slug, overrides)
                self._apply_metadata_patch(merged, patch)
                for key in MANUAL_EDITABLE_FIELDS:
                    if key in patch or (key in {"group_label", "group_label_en"} and "group" in patch):
                        current[key] = merged[key]
                current["updated_at"] = now
                current["updated_by"] = _clean_text(updated_by, max_len=128)
                overrides[normalized_slug] = current
                self._write_registry_unlocked(registry)
                return self._public_item(self._builtin_item(normalized_slug, overrides))

            items = registry.setdefault("items", {})
            record = items.get(normalized_slug)
            if not isinstance(record, dict) or not (self.items_dir / normalized_slug / "source.html").is_file():
                return None
            updated = dict(record)
            touched = self._apply_metadata_patch(updated, patch)
            manual_fields = set(updated.get("manual_fields") or [])
            manual_fields.update(touched)
            updated["manual_fields"] = sorted(manual_fields)
            updated["updated_at"] = now
            if updated_by:
                updated["updated_by"] = _clean_text(updated_by, max_len=128)
            items[normalized_slug] = updated
            _atomic_write_text(
                self.items_dir / normalized_slug / "meta.json",
                json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            self._write_registry_unlocked(registry)
            return self._public_item(updated)

    def _apply_metadata_patch(self, record: dict[str, Any], patch: dict[str, Any]) -> set[str]:
        touched: set[str] = set()
        if "title" in patch:
            title = _clean_text(patch["title"], max_len=160)
            if not title:
                raise ValueError("标题不能为空。")
            record["title"] = title
            touched.add("title")
        if "title_en" in patch:
            title_en = _clean_text(patch["title_en"], max_len=160)
            record["title_en"] = title_en or record.get("title") or record["slug"]
            touched.add("title_en")
        if "summary" in patch:
            record["summary"] = _clean_text(patch["summary"], max_len=600)
            touched.add("summary")
        if "summary_en" in patch:
            record["summary_en"] = _clean_text(patch["summary_en"], max_len=600)
            touched.add("summary_en")
        if any(k in patch for k in ("group", "group_label", "group_label_en")):
            group_id, group_zh, group_en = normalize_artifact_group(
                patch.get("group", record.get("group")),
                group_label=patch.get("group_label") if "group_label" in patch else None,
                group_label_en=patch.get("group_label_en") if "group_label_en" in patch else None,
            )
            record["group"] = group_id
            record["group_label"] = group_zh
            record["group_label_en"] = group_en
            touched.update({"group", "group_label", "group_label_en"})
        if "tags" in patch:
            record["tags"] = _clean_tags(patch["tags"])
            touched.add("tags")
        if "pinned" in patch:
            record["pinned"] = bool(patch["pinned"])
            touched.add("pinned")
        if "archived" in patch:
            record["archived"] = bool(patch["archived"])
            touched.add("archived")
        return touched

    def delete_artifact(self, slug: str) -> bool:
        normalized_slug = normalize_artifact_slug(slug)
        if normalized_slug in BUILTIN_ARTIFACTS:
            raise ValueError(f"内置 artifact '{normalized_slug}' 不可删除，可通过归档隐藏。")
        with self._locked(exclusive=True):
            registry = self._read_registry_unlocked()
            items = registry.setdefault("items", {})
            existed = normalized_slug in items
            item_dir = self.items_dir / normalized_slug
            if existed:
                items.pop(normalized_slug, None)
                self._write_registry_unlocked(registry)
            if item_dir.exists():
                shutil.rmtree(item_dir, ignore_errors=True)
                existed = True
            return existed
