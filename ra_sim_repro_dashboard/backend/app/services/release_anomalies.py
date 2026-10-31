"""Read-only explanations of changes against the submitted, frozen population."""
from sqlalchemy import select
from app.models import ReleaseIssueSnapshot
from app.services import release_workflow as workflow
from app.services.release_watch import activity_identity
from app.services.result_publication import audit_hash

FIELDS = {'ra_merge_result': 'label_changed', 'ra_type': 'trigger_type_changed',
          'issue_time': 'issue_time_changed', 'version': 'road_version_changed'}
DETAIL_LIMIT = 30


def population_changes(before, after):
    old = {str(row['issue_id']): row for row in before}
    new = {str(row['issue_id']): row for row in after}
    result = []
    for code, ids in [('issues_added', new.keys() - old.keys()), ('issues_removed', old.keys() - new.keys())]:
        if ids:
            result.append({'code': code, 'count': len(ids),
                           'items': [{'issue_id': i} for i in sorted(ids)[:DETAIL_LIMIT]]})
    for field, code in FIELDS.items():
        changes = [{'issue_id': i, 'field': field, 'before': old[i].get(field), 'after': new[i].get(field)}
                   for i in sorted(old.keys() & new.keys()) if old[i].get(field) != new[i].get(field)]
        if changes:
            result.append({'code': code, 'count': len(changes), 'items': changes[:DETAIL_LIMIT]})
    return result


def collection_anomalies(db, release, collection, batches):
    if not collection or not collection.get('population_changed_after_submission'):
        return []
    observation = workflow.get_state(db, 'release_observation:' + release)
    if not observation.get('issues') or not observation.get('activity_hash'):
        return [{'code': 'collection_change_unresolved', 'count': None, 'items': []}]
    batches = [b for b in batches if b.release == release and not b.payload.get('backfill')]
    wanted = {b.payload.get('population_hash') for b in batches}
    sources = {}
    snapshots = db.scalars(select(ReleaseIssueSnapshot).where(
        ReleaseIssueSnapshot.release == release).order_by(ReleaseIssueSnapshot.id.desc())
        .execution_options(yield_per=1))
    try:
        for snapshot in snapshots:
            if snapshot.payload.get('population_complete'):
                identity = workflow.population_identity(snapshot.payload)
                if identity in wanted:
                    sources.setdefault(identity, snapshot.payload)
                if wanted <= sources.keys():
                    break
    finally:
        snapshots.close()
    lane = workflow.get_state(db, 'label_cycle:' + release)
    revision = workflow.get_state(db, lane['revision_key']) if lane.get('revision_key') else {}
    result = []
    for batch in batches:
        plan = batch.payload
        expected = plan.get('period', {}).get('activity_hash')
        if batch.release != release or not expected or expected == observation.get('activity_hash'):
            continue
        # Match the exact frozen source; never compare against an arbitrary latest snapshot.
        source = sources.get(plan.get('population_hash'))
        if source and activity_identity(source['issues'], 'issue_time') == expected:
            changes = population_changes(source['issues'], observation.get('issues', []))
        else:
            changes = []
        # A zero pending count alone is not a receipt. Only the revision actually
        # applied to this batch and this exact observation can resolve its labels.
        labels_applied = bool(revision.get('summary', {}).get('available')
                              and revision.get('base_audit_hash') == audit_hash(plan)
                              and revision.get('source_hash') == observation.get('activity_hash')
                              and activity_identity(observation['issues'], 'issue_time') == revision.get('source_hash'))
        result.extend({**item, **({'resolved': True, 'resolved_at': revision.get('applied_at')}
                                  if labels_applied and item['code'] == 'label_changed' else {}),
                       'job_id': plan.get('job_id'), 'fingerprint': batch.fingerprint,
                       'observed_at': observation.get('observed_at')} for item in
                      (changes or [{'code': 'collection_change_unresolved', 'count': None, 'items': []}]))
    return result or [{'code': 'collection_change_unresolved', 'count': None, 'items': []}]
