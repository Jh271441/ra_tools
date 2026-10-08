"""Shared source fixtures for legacy frontend contract checks.

These presence assertions complement, not replace, Node behavior/API/browser
checks. Workflow sources follow implementation modules rather than facades.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from frontend_js import (  # type: ignore  # unittest discover puts tests/ on sys.path
    JS_DIR,
    MANIFEST_PATH,
    STATIC_DIR,
    load_app_entry_js,
    load_app_js,
)


APP_JS = load_app_js()
APP_ENTRY_JS = load_app_entry_js()
CSS_PATHS = (
    "styles.css",
    "css/base.css",
    "css/layout-shared.css",
    "css/trail-update.css",
    "css/review-comment.css",
    "css/case-labeling.css",
    "css/assignment-composer.css",
    "css/analysis.css",
    "css/intent-labeling.css",
    "css/media-dialog.css",
    "css/comparison.css",
    "css/batch-gateway.css",
    "css/runs.css",
    "css/campaigns.css",
    "css/labeling-summary.css",
    "css/mobile.css",
)
STYLES_CSS = "\n".join(
    (STATIC_DIR / path).read_text(encoding="utf-8") for path in CSS_PATHS
)
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
RUN_COMPARISON_JS = (JS_DIR / "run-comparison.js").read_text(encoding="utf-8")
RUN_COLLECTION_JS = (JS_DIR / "run-collections.js").read_text(encoding="utf-8")
CAMPAIGNS_JS = (JS_DIR / "campaigns.js").read_text(encoding="utf-8")
LABELING_SUMMARY_JS = (JS_DIR / "labeling-summary.js").read_text(encoding="utf-8")
CAMPAIGNS_CSS = (STATIC_DIR / "css/campaigns.css").read_text(encoding="utf-8")
FORMAT_API_JS = (JS_DIR / "format-api.js").read_text(encoding="utf-8")
APP_PY_LABELING_DB = "\n".join(p.read_text(encoding="utf-8") for p in sorted((STATIC_DIR.parent / "app" / "db_parts").glob("labeling*.py")))
APP_PY_SNAPSHOTS_DB = (
    STATIC_DIR.parent / "app" / "db_parts" / "snapshots.py"
).read_text(encoding="utf-8")
APP_PY_LABELING_ROUTER = "\n".join(p.read_text(encoding="utf-8") for p in sorted((STATIC_DIR.parent / "app" / "routers" / "labeling_api").glob("*.py")))
APP_PY_CASES_DB = (
    STATIC_DIR.parent / "app" / "db_parts" / "cases.py"
).read_text(encoding="utf-8")
APP_PY_CAMPAIGNS_DB = (
    STATIC_DIR.parent / "app" / "db_parts" / "campaigns.py"
).read_text(encoding="utf-8")
APP_PY_CAMPAIGNS_ROUTER = (
    STATIC_DIR.parent / "app" / "routers" / "campaigns.py"
).read_text(encoding="utf-8")
APP_PY_RUN_COLLECTIONS_DB = "\n".join(p.read_text(encoding="utf-8") for p in sorted((STATIC_DIR.parent / "app" / "db_parts").glob("run_collection*.py")))
APP_PY_CASES_ROUTER = (
    STATIC_DIR.parent / "app" / "routers" / "cases.py"
).read_text(encoding="utf-8")
APP_PY_COMMENTS_DB = (
    STATIC_DIR.parent / "app" / "db_parts" / "comments.py"
).read_text(encoding="utf-8")
