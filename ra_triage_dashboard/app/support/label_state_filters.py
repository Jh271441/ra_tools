"""Shared Issue label/GT filtering for existing Review reason candidates."""
from ..db_parts.labeling_shared import matches_issue_label_states, resolved_label_gt_relation


def filter_reason_rows_by_label_gt(database, rows, *, scopes, label_states, gt_relations):
    """Filter before aggregation/pagination without inventing new Review rows."""
    if not rows:
        return []
    allowed = set()
    for candidates in database.iter_case_review_candidate_batches(
        batch_size=400, baseline_scopes=scopes,
        issue_ids=tuple(dict.fromkeys(row['issue_id'] for row in rows)),
        include_raw_gt=bool(gt_relations),
    ):
        by_scope = {}
        for item in candidates:
            by_scope.setdefault(item['baseline_scope'], []).append(item['issue_id'])
        projected = {}
        for scope, issue_ids in by_scope.items():
            projected.update(database.project_issue_label_states(scope, issue_ids, include_sources=False))
        for item in candidates:
            projection = projected.get(item['issue_id'], {})
            if not matches_issue_label_states(projection, label_states):
                continue
            relation = resolved_label_gt_relation(projection.get('state'), projection.get('expected_output'), item.get('gt_label') or item.get('gt_raw_label'))
            if gt_relations and relation not in gt_relations:
                continue
            allowed.add(item['issue_id'])
    return [row for row in rows if row['issue_id'] in allowed]
