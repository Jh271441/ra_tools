from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
JS_DIR = STATIC_DIR / "js"
MANIFEST_PATH = JS_DIR / "MANIFEST"


def load_app_js() -> str:
    """Concatenate domain modules in MANIFEST order (classic-script SPA body)."""
    names = [
        line.strip()
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not names:
        raise AssertionError("static/js/MANIFEST has no module entries")
    parts: list[str] = []
    for name in names:
        path = JS_DIR / name
        if not path.is_file():
            raise AssertionError(f"missing frontend module listed in MANIFEST: {name}")
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def load_app_entry_js() -> str:
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")
