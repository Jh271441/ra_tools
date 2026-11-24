#!/usr/bin/env python3
"""Server-side atomic publisher for dynamic RA Triage Workbench artifacts.

Reads a single artifact JSON object or a batch payload ``{"items": [...]}``
from stdin (or ``--input``) and upserts into ``DASHBOARD_DATA_DIR/artifacts``
using the exact same advisory-locked ``ArtifactStore`` as FastAPI.

No service restart or git release is required after publishing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DASHBOARD_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ra_triage_dashboard.app.artifact_store import ArtifactStore  # noqa: E402


DEFAULT_PROD_DATA_DIR = Path(
    "/volume/home/workspace/ra_triage_dashboard_deploy/experiments/"
    "manual_dashboard_product_ux_20260922/production-readiness-20261009/candidate/data"
)


def _resolve_artifacts_dir(explicit_data_dir: str | None) -> Path:
    override = os.getenv("DASHBOARD_ARTIFACTS_DIR", "").strip()
    if override and not explicit_data_dir:
        return Path(override).expanduser().resolve()
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve() / "artifacts"
    env_data = os.getenv("DASHBOARD_DATA_DIR", "").strip()
    if env_data:
        return Path(env_data).expanduser().resolve() / "artifacts"
    if DEFAULT_PROD_DATA_DIR.is_dir():
        return DEFAULT_PROD_DATA_DIR / "artifacts"
    return (DASHBOARD_ROOT / ".data" / "artifacts").resolve()


def _publish_one(
    store: ArtifactStore,
    item: dict[str, Any],
    *,
    base_url: str,
) -> dict[str, Any]:
    html_content = item.get("html_content")
    if html_content is None and item.get("html_file"):
        html_content = Path(str(item["html_file"])).read_text(encoding="utf-8")
    result = store.upsert_artifact(
        slug=str(item["slug"]),
        html_content=str(html_content or ""),
        title=item.get("title"),
        title_en=item.get("title_en"),
        summary=item.get("summary"),
        summary_en=item.get("summary_en"),
        group=item.get("group"),
        group_label=item.get("group_label"),
        group_label_en=item.get("group_label_en"),
        tags=item.get("tags"),
        conversation_id=item.get("conversation_id"),
        conversation_label=item.get("conversation_label"),
        source_filename=item.get("source_filename"),
        source_host=item.get("source_host"),
        source_path=item.get("source_path"),
        source_updated_at=item.get("source_updated_at"),
        pinned=item.get("pinned") if "pinned" in item else None,
        archived=item.get("archived") if "archived" in item else None,
        updated_by=str(item.get("updated_by") or "hook-sync"),
        preserve_manual_edits=bool(item.get("preserve_manual_edits", True)),
    )
    pub_item = result["item"]
    return {
        "slug": pub_item["slug"],
        "url": f"{base_url.rstrip('/')}{pub_item['url_path']}",
        "revision": pub_item["revision"],
        "created": result["created"],
        "unchanged": result["unchanged"],
        "size_bytes": pub_item["size_bytes"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atomically publish dynamic HTML artifacts to RA Triage Workbench."
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override DASHBOARD_DATA_DIR (defaults to env or active production data dir).",
    )
    parser.add_argument(
        "--input",
        default="-",
        help="JSON payload path or '-' for stdin.",
    )
    parser.add_argument(
        "--public-base-url",
        default="https://auto-triage.intra.xiaojukeji.com/manual",
        help="Public URL prefix for receipt output.",
    )
    args = parser.parse_args(argv)

    raw_text = (
        sys.stdin.read()
        if args.input == "-"
        else Path(args.input).read_text(encoding="utf-8")
    )
    payload = json.loads(raw_text)
    artifacts_dir = _resolve_artifacts_dir(args.data_dir)
    store = ArtifactStore(artifacts_dir, static_dir=DASHBOARD_ROOT / "static")

    items_list = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else [payload]
    receipts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in items_list:
        if not isinstance(entry, dict):
            errors.append({"slug": "", "error": "Entry must be a JSON object."})
            continue
        try:
            receipts.append(_publish_one(store, entry, base_url=args.public_base_url))
        except Exception as exc:
            errors.append({"slug": str(entry.get("slug") or ""), "error": str(exc)})

    output = {
        "ok": len(errors) == 0,
        "artifacts_dir": str(artifacts_dir),
        "published": receipts,
        "errors": errors,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
