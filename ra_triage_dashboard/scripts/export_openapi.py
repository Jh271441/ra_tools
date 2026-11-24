#!/usr/bin/env python3
"""Export deterministic OpenAPI schema JSON from FastAPI without starting a server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


def build_openapi_schema() -> dict:
    from ra_triage_dashboard.app.main import app

    return app.openapi()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export RA Triage Workbench OpenAPI JSON")
    parser.add_argument(
        "--output",
        default="",
        help="Optional file path to write JSON (defaults to stdout).",
    )
    args = parser.parse_args(argv)
    schema = build_openapi_schema()
    rendered = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
