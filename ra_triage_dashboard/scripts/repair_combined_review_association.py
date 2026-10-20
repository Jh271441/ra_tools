#!/usr/bin/env python3
"""Plan/apply one explicitly confirmed missing association without rewriting history."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.combined_review_repair import repair_association


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--label-revision-id", required=True, type=int)
    parser.add_argument("--model-review-revision-id", required=True, type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-fingerprint", default="")
    args = vars(parser.parse_args())
    url_file = args.pop("database_url_file")
    db = Database(url_file.read_text().strip())
    # Never initialize/migrate the live database as part of an association repair.
    try:
        print(json.dumps(repair_association(db, **args), ensure_ascii=False, default=str, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
