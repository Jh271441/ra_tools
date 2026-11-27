"""Read-only history of imported annotations predating task allocation."""
from collections import defaultdict


HISTORICAL_BASELINES = {
    "release0522_100_20260908": "0522",
    "release0626_300_spotcheck": "0626",
}


def historical_label_collections(db):
    scopes = tuple(HISTORICAL_BASELINES)
    with db.connect() as conn:
        # Keep the original source even when another Run has a prediction for the Issue.
        rows = conn.execute(f"""
            WITH sources AS (
                SELECT DISTINCT c.baseline_scope, c.issue_id, c.source_run_id
                FROM label_cases c
                JOIN label_revisions r ON r.label_case_id = c.id
                WHERE c.baseline_scope IN ({','.join('?' for _ in scopes)})
                  AND c.task_id = '' AND r.revision_kind = 'legacy'
                  AND NOT EXISTS (SELECT 1 FROM label_import_suppressed_revisions s
                                  WHERE s.revision_id = r.id)
            )
            SELECT s.baseline_scope, s.issue_id, orig.model_run_id AS original_run,
                   p.model_run_id AS run_id, run.name AS run_name
            FROM sources s
            LEFT JOIN model_predictions orig ON orig.issue_id = s.issue_id
                AND orig.model_run_id = s.source_run_id AND orig.model_label <> ''
            LEFT JOIN model_predictions p ON p.issue_id = s.issue_id AND p.model_label <> ''
                AND (orig.id IS NULL OR p.id = orig.id)
            LEFT JOIN model_runs run ON run.id = p.model_run_id
            ORDER BY s.baseline_scope, s.issue_id
        """, scopes).fetchall()

    issues = defaultdict(set)
    groups = defaultdict(lambda: defaultdict(set))
    for row in rows:
        scope, issue = row["baseline_scope"], row["issue_id"]
        issues[scope].add(issue)
        if not row["original_run"]:
            groups[scope][("label_only", "", "")].add(issue)
        if row["run_id"]:
            kind = "original" if row["original_run"] else "comparison"
            groups[scope][(kind, row["run_id"], row["run_name"])].add(issue)
    group_order = {"original": 0, "label_only": 1, "comparison": 2}
    return [
        {"baseline": scope, "version": version, "issue_ids": sorted(issues[scope]),
         "groups": [
             {"kind": kind, "run_id": run_id, "run_name": name, "issue_ids": sorted(ids)}
             for (kind, run_id, name), ids in sorted(
                 groups[scope].items(), key=lambda pair: (group_order[pair[0][0]], pair[0][2], pair[0][1])
             )
         ]}
        for scope, version in HISTORICAL_BASELINES.items() if scope in issues
    ]
