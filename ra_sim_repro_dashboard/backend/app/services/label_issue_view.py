"""Read applied label results through their audited, per-scenario lineage."""
from sqlalchemy import select

from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import release_workflow as w
from app.services.label_recovery import INPUT_FIELDS, SCENE_FIELDS, same_inputs
from app.services.release_metrics import cohort_for_issue, excluded_issue
from app.services.release_watch import activity_identity
from app.services.result_publication import audit_hash, effective_publication, published_batch


def applied_rows(db, release, observed):
    lane = w.get_state(db, 'label_cycle:' + release)
    key = lane.get('revision_key')
    revision = w.get_state(db, key) if key else {}
    issues = observed.get('issues', [])
    if (not revision.get('summary', {}).get('available') or not issues
            or activity_identity(issues, 'issue_time') != revision.get('source_hash')):
        return None
    base = published_batch(db, release)
    metrics = effective_publication(db, base) if base else None
    if (not metrics or (metrics.get('label_revision') or {}).get('revision_key') != key):
        return None
    recovery = w.get_state(db, 'label_recovery:' + release)
    context = w.get_state(db, recovery.get('source_key', 'label_source:none'))
    frozen = context.get('source') if (context.get('base_fingerprint') == base.fingerprint
        and context.get('base_audit_hash') == revision.get('base_audit_hash')
        and context.get('source_hash') == revision.get('source_hash')) else None
    if frozen is None:
        snapshots = db.scalars(select(ReleaseIssueSnapshot).where(
            ReleaseIssueSnapshot.release == release).order_by(ReleaseIssueSnapshot.id.desc())
            .execution_options(yield_per=1))
        try:
            frozen = next((s.payload for s in snapshots
                if w.population_identity(s.payload) == base.payload['population_hash']), None)
        finally:
            snapshots.close()
    if not frozen or not same_inputs(frozen['issues'], issues, INPUT_FIELDS):
        return None
    lineage = revision.get('lineage')
    if lineage is None:
        # A pure GT edit can reuse the primary plus an existing bag-recovery ledger.
        recovery = w.get_state(db, metrics.get('backfill_revision') or 'backfill:none')
        base_hash = audit_hash(base.payload)
        lineage = recovery.get('lineage') or {
            str(s['scenario_id']): {'fingerprint': base.fingerprint,
                'job_id': base.payload['job_id'], 'audit_hash': base_hash}
            for s in base.payload['scenarios'] if str(s['scenario_id']) in base.payload.get('results', {})}
    executions = {base.fingerprint: base}
    for fingerprint in {item['fingerprint'] for item in lineage.values()} - executions.keys():
        batch = db.get(ReleaseSimulationBatch, fingerprint)
        if not batch:
            return None
        executions[fingerprint] = batch
    hashes = {fingerprint: audit_hash(batch.payload) for fingerprint, batch in executions.items()}
    if any(hashes[item['fingerprint']] != item['audit_hash']
           for item in lineage.values()):
        return None

    scenes = {str(s['scenario_id']): s for batch in executions.values() for s in batch.payload['scenarios']}
    snapshot = db.scalars(select(ReleaseIssueSnapshot).where(
        ReleaseIssueSnapshot.release == release).order_by(ReleaseIssueSnapshot.id.desc()).limit(1)).first()
    sources = [frozen, snapshot.payload if snapshot else {}]
    for source in sources:
        if not source.get('issues') or not same_inputs(source['issues'], issues, INPUT_FIELDS):
            continue
        for scene in source.get('scenarios', []):
            sid = str(scene['scenario_id'])
            if sid in scenes and any(scene.get(k) != scenes[sid].get(k) for k in SCENE_FIELDS):
                return None
            scenes[sid] = scene
    by_issue = {}
    for scene in scenes.values():
        by_issue.setdefault(str(scene['issue_id']), []).append(scene)
    revised = {str(i['issue_id']): i for i in revision['issues']}
    excluded = set(revision['excluded_issue_ids'])
    rows = []
    for issue in issues:
        iid = str(issue['issue_id'])
        cohort = cohort_for_issue(revised[iid])
        for scene in by_issue.get(iid) or [None]:
            sid = str(scene['scenario_id']) if scene else ''
            row = {'issue_id': iid, 'issue_topic': str(issue.get('issue_topic') or ''),
                'source_result': issue.get('ra_merge_result'), 'version_key': release,
                'road_version': str(issue.get('version', '')), 'ra_type': issue.get('ra_type'),
                'issue_time': issue.get('issue_time'), 'scenario_id': sid,
                'scenario_name': scene.get('scenario_name', '') if scene else '',
                'scenario_labels': scene.get('scenario_labels', []) if scene else [],
                'simulation_status': 'excluded' if excluded_issue(revised[iid]) else
                    'pending_gt' if not cohort else 'pending_simulation' if scene else 'pending_mapping',
                'sim_triggered': None, 'reproduced': None, 'precision_label': None}
            item = lineage.get(sid)
            if cohort and iid not in excluded and item:
                execution = executions[item['fingerprint']].payload
                result = execution.get('results', {}).get(sid, {})
                detail = execution.get('scenario_results', {}).get(sid, {})
                triggered = result.get('sim_triggered')
                if (not isinstance(triggered, bool) or detail.get('status') != 'result_ready'
                        or detail.get('errors')):
                    return None
                row.update(simulation_status='result_ready', sim_triggered=triggered,
                    reproduced=not triggered if cohort == 'positive_manual' else triggered,
                    precision_label=('FP' if triggered else 'TN') if cohort == 'negative_auto'
                        else ('TP' if triggered else 'FN'), job_id=item['job_id'])
            rows.append(row)
    return rows
