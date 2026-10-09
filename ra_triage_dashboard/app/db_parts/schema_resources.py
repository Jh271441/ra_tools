"""SQLite schema resources, kept byte-identical to the former core initializer.

PostgreSQL's runtime adapter ignores executescript; its versioned migrations are
still applied before initialization. Keep each logical script one executescript
call: splitting calls would change SQLite's implicit commit behavior.
"""
from functools import lru_cache
from pathlib import Path

_SCHEMA_DIR = Path(__file__).with_name("sqlite_schema")
BASE_SCHEMA_PARTS = ('01_reviews.sql', '02_model_runs.sql', '03_inference_jobs.sql', '04_dashboard_change_revision.sql', '05_issue_work_splits.sql', '06_label_cases.sql', '07_label_migration_map.sql', '08_legacy_review_classifications.sql', '09_issue_work_assignments.sql', '10_intent_label_revisions.sql', '11_trail_issue_exclusion_history.sql')


# Preserve original logical script whitespace while keeping resource files lint-clean.
_SCRIPT_SUFFIXES = {'01_reviews.sql': '\n', '02_model_runs.sql': '\n', '03_inference_jobs.sql': '\n', '04_dashboard_change_revision.sql': '\n', '05_issue_work_splits.sql': '\n', '06_label_cases.sql': '\n', '07_label_migration_map.sql': '\n', '08_legacy_review_classifications.sql': '\n', '09_issue_work_assignments.sql': '\n', '10_intent_label_revisions.sql': '\n', '11_trail_issue_exclusion_history.sql': '                ', 'run_evaluations.sql': '                    '}

@lru_cache(maxsize=2)
def schema_sql(kind: str) -> str:
    if kind == "base":
        files = BASE_SCHEMA_PARTS
    elif kind == "run_evaluations":
        files = ("run_evaluations.sql",)
    else:
        raise ValueError("Unknown built-in SQLite schema")
    return "".join((_SCHEMA_DIR / name).read_text(encoding="utf-8") + _SCRIPT_SUFFIXES[name] for name in files)
