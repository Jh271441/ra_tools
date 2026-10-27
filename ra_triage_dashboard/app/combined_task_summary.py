"""Read-only labeling-side mirror of existing combined Campaign assignments."""
import json
from collections import defaultdict


def combined_task_summaries(database, scopes, *, issue_ids=()):
    scopes = list(dict.fromkeys(scopes))
    if not scopes:
        return []
    marks = ','.join('?' for _ in scopes)
    with database.connect() as conn:
        campaigns = conn.execute(
            "SELECT * FROM issue_work_splits WHERE purpose='model_review' "
            "AND workflow_mode='model_review_and_case_label' AND lifecycle='active' "
            "ORDER BY created_at DESC,id DESC"
        ).fetchall()
        result = []
        for campaign in campaigns:
            filters = campaign['filter_json'] or '{}'
            filters = json.loads(filters) if isinstance(filters, str) else filters
            dataset_id = filters.get('version_dataset_id') if filters.get('version_live') else None
            target_clause = (
                " AND EXISTS (SELECT 1 FROM version_dataset_items v "
                "WHERE v.dataset_id=? AND v.issue_id=m.issue_id AND v.is_target=1)"
                if dataset_id else ''
            )
            # Version cards mirror the whole current version, as on Review assignments.
            # The selected scopes decide visibility, not a second task denominator.
            visible = conn.execute(
                f"SELECT 1 FROM campaign_issue_members WHERE campaign_id=? AND baseline_scope IN ({marks}) LIMIT 1",
                [campaign['id'], *scopes],
            ).fetchone()
            if not visible:
                continue
            scope_clause = '' if dataset_id else f' AND m.baseline_scope IN ({marks})'
            rows = conn.execute(
                f"""SELECT m.issue_id,m.baseline_scope,a.assignee,
                           p.model_review_submitted,
                           CASE WHEN p.case_label_acknowledged AND r.id IS NOT NULL
                             AND lower(r.author)=lower(a.assignee)
                             AND lc.issue_id=m.issue_id
                             AND NOT EXISTS (SELECT 1 FROM label_import_suppressed_revisions s
                                             WHERE s.revision_id=r.id)
                           THEN 1 ELSE 0 END AS labeled
                    FROM campaign_issue_members m
                    JOIN review_work_assignments a ON a.split_id=m.campaign_id AND a.issue_id=m.issue_id
                    LEFT JOIN combined_review_progress p ON p.campaign_id=m.campaign_id
                      AND p.issue_id=m.issue_id AND lower(p.reviewer)=lower(a.assignee)
                    LEFT JOIN label_revisions r ON r.id=p.case_label_revision_id
                    LEFT JOIN label_cases lc ON lc.id=r.label_case_id
                    WHERE m.campaign_id=?{scope_clause}{target_clause}
                    ORDER BY m.issue_id, a.assignee""",
                [campaign['id'], *([dataset_id] if dataset_id else scopes)],
            ).fetchall()
            if issue_ids and not dataset_id:
                selected = set(issue_ids)
                rows = [row for row in rows if row['issue_id'] in selected]
            if not rows:
                continue
            people = defaultdict(lambda: dict(total=0, labeled=0, reviewed=0, completed=0))
            for row in rows:
                person = people[str(row['assignee']).strip().lower()]
                labeled = bool(row['labeled'])
                reviewed = bool(row['model_review_submitted'])
                person['total'] += 1
                person['labeled'] += int(labeled)
                person['reviewed'] += int(reviewed)
                person['completed'] += int(labeled and reviewed)
            counts = {key: sum(p[key] for p in people.values())
                      for key in ('total', 'labeled', 'reviewed', 'completed')}
            # Keep entry and progress within the exact same selected membership.
            # A version task is already restricted by the version baseline's targets.
            result.append(dict(
                split_id=str(campaign['id']), name=str(campaign['campaign_name'] or ''),
                model_run_id=str(campaign['evaluation_run_id']),
                workflow_mode='model_review_and_case_label',
                baseline_scopes=sorted({str(r['baseline_scope']) for r in rows}),
                baseline_ids=['version-' + dataset_id.removeprefix('release-').removesuffix('-odd2')]
                    if dataset_id else sorted({str(r['baseline_scope']) for r in rows}),
                member_count=len({r['issue_id'] for r in rows}),
                appendable=bool(dataset_id), dataset_id=dataset_id or '',
                release_family=dataset_id.removeprefix('release-').removesuffix('-odd2') if dataset_id else '',
                members=[dict(username=name, **counts) for name, counts in sorted(people.items())],
                **counts,
            ))
    return result
