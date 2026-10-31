"""Persisted incremental recovery lane. Finished executions remain immutable.

A revision is a ledger of disjoint scene inputs and their audited execution IDs;
it never disguises a union as a single Orion job or picks a more favourable run.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import chain
from sqlalchemy import select
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import release_workflow as w
from app.services.release_cycle import digest
from app.services.release_metrics import cohort_for_issue, summarize_population
from ra_api.release_tolerance import POLICY, assess, grade, validate_frozen

INTERVAL_SECONDS = 6 * 3600
ACTIVE = ('queued', 'submitting', 'submission_uncertain', 'running', 'verifying')
MAX_ATTEMPTS = 3


def snapshots(db, release):
    # Stream until the frozen source is found; most reads only need the latest
    # snapshot. Fetching all historical JSON first multiplies memory and latency.
    return db.scalars(select(ReleaseIssueSnapshot).where(
        ReleaseIssueSnapshot.release == release).order_by(ReleaseIssueSnapshot.id.desc())
        .execution_options(yield_per=1))


def compatible_source(old, new):
    """Only scene additions are compatible. Source, GT and existing inputs must match."""
    old = deepcopy(old); new = deepcopy(new)
    prior = {str(s['scenario_id']): s for s in old['scenarios']}
    current = {str(s['scenario_id']): s for s in new['scenarios']}
    if len(current) != len(new['scenarios']) or not prior.keys() <= current.keys():
        return False
    new['scenarios'] = [s for s in new['scenarios'] if str(s['scenario_id']) in prior]
    return w.population_identity(old) == w.population_identity(new)


def frozen_snapshot_valid(db, batch):
    from app.services.read_views import read_projection
    return read_projection(db, ('frozen-source', batch.fingerprint, batch.updated_at),
                           lambda: _frozen_snapshot_valid(db, batch))


def _frozen_snapshot_valid(db, batch):
    rows = snapshots(db, batch.release)
    try:
        latest = next(rows, None)
        if latest is None:
            return False
        for snapshot in chain((latest,), rows):
            if w.population_identity(snapshot.payload) == batch.payload['population_hash']:
                return compatible_source(snapshot.payload, latest.payload)
        return False
    finally:
        rows.close()


def executions(db, release):
    return list(db.scalars(select(ReleaseSimulationBatch).where(
        ReleaseSimulationBatch.release == release).order_by(ReleaseSimulationBatch.created_at.asc())))


def original(db, release):
    return next((b for b in reversed(executions(db, release)) if not b.payload.get('backfill')
                 and b.payload.get('result_import', {}).get('primary')), None)


def collect_results(db, base, full):
    """First audited success is retained; failed scenes alone are eligible for retry."""
    from app.services.result_publication import audit_hash
    expected = {str(s['scenario_id']): s for s in full['scenarios']}
    results, lineage = {}, {}
    candidates = [base] + [b for b in executions(db, base.release)
        if b.payload.get('backfill', {}).get('base_fingerprint') == base.fingerprint]
    for b in candidates:
        p = b.payload
        if not p.get('result_import', {}).get('primary'):
            continue
        if any(p.get(k) != base.payload.get(k) for k in ('binary_id', 'simulation', 'driver_revision', 'template_job_id')):
            raise ValueError('execution_contract_changed')
        if b is not base and (not p['result_import'].get('execution_contract_hash')
                or p['result_import']['execution_contract_hash'] != base.payload['result_import'].get('execution_contract_hash')):
            raise ValueError('execution_contract_changed')
        execution_hash = None
        for scene in p['scenarios']:
            sid = str(scene['scenario_id'])
            if sid not in expected or any(scene.get(k) != expected[sid].get(k) for k in
                ('issue_id', 'cohort', 'scenario_revision', 'start_timestamp', 'end_timestamp')):
                raise ValueError('scene_input_changed')
            if sid in results or sid not in p.get('results', {}):
                continue
            detail = p.get('scenario_results', {}).get(sid, {})
            if detail.get('status') != 'result_ready' or detail.get('errors'):
                raise ValueError('result_audit_missing')
            if execution_hash is None:
                execution_hash = audit_hash(p)
            results[sid] = p['results'][sid]
            lineage[sid] = {'fingerprint':b.fingerprint, 'job_id':p['job_id'], 'audit_hash':execution_hash}
    return results, lineage


def delta_plan(db, base, full, results, *, force=False):
    pending = [s for s in full['scenarios'] if str(s['scenario_id']) not in results]
    if not pending:
        return None
    attempts = [b for b in executions(db, base.release) if b.payload.get('backfill', {}).get('base_fingerprint') == base.fingerprint]
    pending = [s for s in pending if sum(any(str(row['scenario_id']) == str(s['scenario_id'])
        for row in b.payload['scenarios']) for b in attempts) < (len(attempts)+1 if force else MAX_ATTEMPTS)]
    if not pending:
        raise ValueError('retry_limit')
    ids = {str(s['issue_id']) for s in pending}
    # Carry all scenes of an Issue when it has no successful result; partial scenes
    # can be retried individually, but metrics still require every associated scene.
    plan = {k:deepcopy(full[k]) for k in ('scenario_label','period','release','binary_id','template_job_id',
        'population_hash','query_attrs','simulation','driver_revision','acceptance_only')}
    plan['scenarios'] = pending
    plan['issues'] = [deepcopy(i) for i in full['issues'] if str(i['issue_id']) in ids]
    for i in plan['issues']:
        i.pop('evaluation_exclusion', None)
    plan['issue_tolerance'] = {'policy':dict(POLICY), 'population_hash':plan['population_hash'],
        'eligible_issue_ids':sorted(ids), 'preparation_failures':[]}
    plan['backfill'] = {'base_fingerprint':base.fingerprint, 'full_fingerprint':full['fingerprint'],
        'attempt':len(attempts)+1, 'kind':'missing_or_failed_scenes'}
    validate_frozen(plan)
    return {**plan, 'fingerprint':digest(plan)}


def validate_delta(db, batch, config):
    metadata = batch.payload['backfill']
    base = db.get(ReleaseSimulationBatch, metadata['base_fingerprint'])
    if not base or not frozen_snapshot_valid(db, base):
        raise ValueError('source_changed')
    full = w.make_plan(db, config, release=batch.release)
    if full['fingerprint'] != metadata['full_fingerprint']:
        raise ValueError('backfill_plan_changed')
    results, _ = collect_results(db, base, full)
    if any(str(s['scenario_id']) in results for s in batch.payload['scenarios']):
        raise ValueError('scene_already_complete')
    for key in ('binary_id','simulation','driver_revision','template_job_id'):
        if batch.payload.get(key) != base.payload.get(key):
            raise ValueError('execution_contract_changed')
    return True


def revision_metrics(db, base, metrics):
    if not metrics:
        return metrics
    state = w.get_state(db, 'backfill:' + base.release)
    revision = w.get_state(db, state.get('revision_key', 'backfill:none'))
    if not revision or revision.get('base_fingerprint') != base.fingerprint:
        return metrics
    from app.services.result_publication import audit_hash
    execution_hashes = {}
    for item in revision['lineage'].values():
        fingerprint = item['fingerprint']
        if fingerprint not in execution_hashes:
            execution = db.get(ReleaseSimulationBatch, fingerprint)
            execution_hashes[fingerprint] = audit_hash(execution.payload) if execution else None
        if execution_hashes[fingerprint] is None or execution_hashes[fingerprint] != item['audit_hash']:
            return metrics
    current = snapshots(db, base.release)
    try:
        latest = next(current, None)
    finally:
        current.close()
    if (not latest or w.population_identity(latest.payload) != revision['population_hash']
            or not frozen_snapshot_valid(db, base)):
        return metrics
    return {**metrics, **revision['summary'], 'generated_at':revision['applied_at'],
        'backfill_revision':revision['revision_key'],
        'publication':{**metrics['publication'], **revision['coverage'],
            'backfill_revision_key':revision['revision_key'], 'source_job_ids':revision['job_ids'],
            'scenario_count':revision['scenario_count'], 'valid_scenario_count':len(revision['lineage']),
            'coverage':len(revision['lineage'])/revision['scenario_count'],
            'excluded_issue_ids':revision['excluded_issue_ids'],
            'excluded_scenario_ids':revision['excluded_scenario_ids']}}


def refresh_release(db, config, base, *, now=None, force=False):
    now = now or datetime.now(timezone.utc)
    key = 'backfill:' + base.release
    previous = w.get_state(db, key)
    def save(**values):
        state = {**previous, 'enabled':True, 'interval_seconds':INTERVAL_SECONDS, **values}
        w.put_state(db, key, state)
        return state
    children = [b for b in executions(db, base.release)
        if b.payload.get('backfill', {}).get('base_fingerprint') == base.fingerprint]
    active = next((b for b in children if b.status in ACTIVE), None)
    if active:
        return save(status='simulating', fingerprint=active.fingerprint, job_id=active.payload.get('job_id'))
    newly_finished = previous.get('status') == 'simulating' and bool(children)
    if not force and not newly_finished:
        try:
            if now < datetime.fromisoformat(previous['next_check_at']):
                return previous
        except (KeyError, TypeError, ValueError):
            pass
    timing = {'checked_at':now.isoformat(), 'next_check_at':(now+timedelta(seconds=INTERVAL_SECONDS)).isoformat()}
    try:
        if w.get_state(db, 'settings', {'mode':'manual'}).get('mode') != 'auto':
            return save(status='paused', reason='manual_mode', **timing)
        if any(b.status in ACTIVE for b in executions(db, base.release)):
            return save(status='waiting', reason='active_execution', **timing)
        save(status='syncing', reason=None, **timing)
        w.sync_once(db, config, release=base.release)
        if not frozen_snapshot_valid(db, base):
            raise ValueError('source_changed')
        save(status='preparing', **timing)
        w.prepare_missing_scenes(db, config, release=base.release)
        full = w.make_plan(db, config, release=base.release)
        results, lineage = collect_results(db, base, full)
        eligible = set(full['issue_tolerance']['eligible_issue_ids'])
        mapping = {}
        for s in full['scenarios']:
            mapping.setdefault(str(s['issue_id']), []).append(str(s['scenario_id']))
        missing = {iid for iid in eligible if not mapping.get(iid) or any(sid not in results for sid in mapping[iid])}
        coverage = grade(eligible, missing)
        from app.services.result_publication import publication
        if publication(base) and coverage['quality_level'] != 'blocked':
            save(status='merging', **timing)
            rows = [i for i in full['issues'] if str(i['issue_id']) in eligible-missing]
            summary = summarize_population(rows, full['scenarios'], results)
            if not summary['available'] or summary['unclassified']:
                raise ValueError('revision_gate_failed')
            revision = {'base_fingerprint':base.fingerprint, 'population_hash':full['population_hash'],
                'summary':summary, 'coverage':coverage, 'lineage':lineage,
                'job_ids':sorted({item['job_id'] for item in lineage.values()}),
                'scenario_count':len(full['scenarios']), 'excluded_issue_ids':sorted(missing),
                'excluded_scenario_ids':sorted(str(s['scenario_id']) for s in full['scenarios'] if str(s['scenario_id']) not in results)}
            revision_key = 'backfill_revision:' + digest(revision)[:46]
            if not w.get_state(db, revision_key):
                w.put_state(db, revision_key, {**revision,'revision_key':revision_key,'applied_at':now.isoformat()})
            previous.update(revision_key=revision_key, applied_at=now.isoformat())
        plan = delta_plan(db, base, full, results, force=force)
        if plan:
            batch = db.get(ReleaseSimulationBatch, plan['fingerprint'])
            if not batch:
                batch = ReleaseSimulationBatch(fingerprint=plan['fingerprint'],release=base.release,status='queued',payload=plan)
                db.add(batch); db.commit()
            save(status='simulating', pending_count=len(missing), recovered_count=coverage['valid_issue_count'],
                 issue_count=coverage['issue_count'], fingerprint=batch.fingerprint, **timing)
            w.execute_batch(db, batch, config, release=base.release)
            return save(status='simulating' if batch.status in ACTIVE else 'blocked', reason=None if batch.status in ACTIVE else batch.status,
                pending_count=len(missing), recovered_count=coverage['valid_issue_count'], issue_count=coverage['issue_count'],
                fingerprint=batch.fingerprint,job_id=batch.payload.get('job_id'),**timing)
        return save(status='waiting_bags' if missing else 'complete', reason=None, pending_count=len(missing),
            recovered_count=coverage['valid_issue_count'],issue_count=coverage['issue_count'],job_id=None,**timing)
    except Exception as exc:
        db.rollback()
        return save(status='blocked', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__, **timing)


def tick(db, config):
    # Run under the workflow lock. Only already watched/new-policy releases opt in.
    releases = set(db.scalars(select(ReleaseSimulationBatch.release)))
    for release in sorted(releases):
        base = original(db, release)
        if (base and base.payload.get('issue_tolerance', {}).get('policy') == POLICY
                and w.get_state(db, 'release_monitor:' + release)):
            refresh_release(db, config, base)


def public_state(db, release):
    state = w.get_state(db, 'backfill:' + release)
    return {k:v for k,v in state.items() if k not in ('revision_key',)} or {
        'enabled':bool(w.get_state(db,'release_monitor:' + release)),'status':'waiting','interval_seconds':INTERVAL_SECONDS}
