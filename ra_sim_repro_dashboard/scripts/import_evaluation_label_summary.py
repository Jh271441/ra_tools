"""Register a verified offline Scenario publication for the matching evaluation revision."""
import argparse
import json
from pathlib import Path

from app.database import SessionLocal
from app.services import evaluation_label_summary as summary, evaluation_pipeline as pipeline, release_workflow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, help="Directory containing dashboard_data, plan.private and complete JSON")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data, plan, receipt = [json.loads((args.directory / name).read_text(encoding="utf-8"))
                           for name in ("dashboard_data.json", "plan.private.json", "complete.json")]
    with SessionLocal() as db:
        revision = pipeline.current_revision(db, data["release"], data["profile"], data["date_start"], data["date_end"])
        if revision.get("revision_key") != args.revision:
            raise ValueError("evaluation_revision_changed")
        value = summary.project(data, plan, receipt, revision)
        key = summary.state_key(value["context"], args.revision)
        if args.apply:
            previous = release_workflow.get_state(db, key)
            if previous and previous != value:
                raise ValueError("summary_already_registered_with_different_snapshot")
            if not previous:
                release_workflow.put_state(db, key, value)
        print(key, args.revision, list(value["scopes"]), "stored" if args.apply else "validated")


if __name__ == "__main__":
    main()
