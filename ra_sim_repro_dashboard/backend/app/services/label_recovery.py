"""Recover missing label-revision inputs without changing the primary execution."""
from copy import deepcopy
from datetime import timedelta

from sqlalchemy import select

from app.models import ReleaseSimulationBatch
from app.services import release_workflow as w
from app.services.release_cycle import digest
from app.services.release_metrics import cohort_for_issue, excluded_issue
from app.services.release_watch import activity_identity
from app.services.result_publication import audit_hash
from ra_api.release_tolerance import POLICY, validate_frozen

INTERVAL_SECONDS = 6 * 3600
ACTIVE = ('queued', 'submitting', 'submission_uncertain', 'running', 'verifying')
INPUT_FIELDS = ('version', 'issue_time', 'ra_type', 'trip_id', 'ra_start_timestamp',
                'trip_start_time', 'trip_end_time')
SCENE_FIELDS = ('issue_id', 'scenario_revision', 'start_timestamp', 'end_timestamp')


def same_inputs(before, after):
    old = {str(i['issue_id']): i for i in before}
    new = {str(i['issue_id']): i for i in after}
    return (len(old) == len(before) and len(new) == len(after) and old.keys() == new.keys()
            and all(old[i].get(k) == new[i].get(k) for i in old for k in INPUT_FIELDS))


def children(db, base):
    return [b for b in db.scalars(select(ReleaseSimulationBatch).where(
        ReleaseSimulationBatch.release == base.release).order_by(ReleaseSimulationBatch.created_at))
        if b.payload.get('backfill', {}).get('base_fingerprint') == base.fingerprint]


def contract(db, config, base):
    value = base.payload.get('result_import', {}).get('execution_contract_hash')
    if value:
        return value
    key = 'label_runtime:' + base.fingerprint[:48]
    saved = w.get_state(db, key)
    if saved.get('base_audit_hash') == audit_hash(base.payload):
        return saved['execution_contract_hash']
    # Legacy executions predate runtime hashes. Audit actual task arguments once;
    # configured template IDs alone cannot establish runtime equivalence.
    receipt = w.driver_call(config, 'contract', base.payload)
    if receipt.get('job_id') != base.payload['job_id'] or not receipt.get('execution_contract_hash'):
        raise ValueError('execution_contract_changed')
    w.put_state(db, key, {**receipt, 'base_audit_hash': audit_hash(base.payload)})
    return receipt['execution_contract_hash']


def source_valid(db, batch):
    meta = batch.payload['backfill']
    context = w.get_state(db, meta.get('source_key', 'label_source:none'))
    base = db.get(ReleaseSimulationBatch, meta['base_fingerprint'])
    if (not base or context.get('base_audit_hash') != audit_hash(base.payload)
            or context.get('base_fingerprint') != base.fingerprint
            or context.get('source_hash') != meta.get('source_hash')
            or context.get('source_key') != 'label_source:' + digest({k:v for k,v in context.items() if k != 'source_key'})[:48]
            or w.population_identity(context['source']) != batch.payload['population_hash']):
        return False
    observed = w.get_state(db, 'release_observation:' + batch.release)
    if observed.get('issues') and not same_inputs(context['source']['issues'], observed['issues']):
        return False
    scenes = {str(s['scenario_id']): s for s in context['source']['scenarios']}
    return all(str(s['scenario_id']) in scenes and all(s.get(k) == scenes[str(s['scenario_id'])].get(k)
               for k in SCENE_FIELDS) for s in batch.payload['scenarios'])


def validate_delta(db, batch, config):
    if not source_valid(db, batch):
        raise ValueError('input_changed')
    observed = w.get_state(db, 'release_observation:' + batch.release)
    current = w.apply_issue_exclusions(db, batch.release, observed.get('issues', []))
    if any(not cohort_for_issue(i) and not excluded_issue(i) for i in current):
        raise ValueError('unknown_labels')
    meta = batch.payload['backfill']
    base = db.get(ReleaseSimulationBatch, meta['base_fingerprint'])
    if (meta.get('execution_contract_hash') != contract(db, config, base)
            or any(batch.payload.get(k) != base.payload.get(k)
                   for k in ('binary_id', 'simulation', 'driver_revision'))
            or batch.payload.get('template_job_id') != base.payload['job_id']):
        raise ValueError('execution_contract_changed')
    return True


def collect(db, base, scenes, expected_contract=None):
    expected = {str(s['scenario_id']): s for s in scenes}
    results, lineage = {}, {}
    for b in [base, *children(db, base)]:
        p = b.payload
        if not p.get('result_import', {}).get('primary'):
            continue
        if any(p.get(k) != base.payload.get(k) for k in ('binary_id', 'simulation', 'driver_revision')):
            raise ValueError('execution_contract_changed')
        if b is not base and (not expected_contract or p['result_import'].get('execution_contract_hash') != expected_contract):
            raise ValueError('execution_contract_changed')
        fingerprint = audit_hash(p)
        for scene in p['scenarios']:
            sid = str(scene['scenario_id'])
            if sid not in expected or any(scene.get(k) != expected[sid].get(k) for k in SCENE_FIELDS):
                raise ValueError('input_changed')
            if sid in results or sid not in p.get('results', {}):
                continue
            detail = p.get('scenario_results', {}).get(sid, {})
            if detail.get('status') != 'result_ready' or detail.get('errors'):
                raise ValueError('result_audit_missing')
            # Only the trigger signal is reused. GT and TP/FP/FN are recomputed.
            results[sid] = p['results'][sid]
            lineage[sid] = {'fingerprint': b.fingerprint, 'job_id': p['job_id'], 'audit_hash': fingerprint}
    return results, lineage


def recover(db, config, base, source, rows, now):
    key = 'label_recovery:' + base.release
    previous = w.get_state(db, key)
    candidates = children(db, base)
    active = next((b for b in candidates if b.status in ACTIVE), None)
    context = w.get_state(db, previous.get('source_key', 'label_source:none'))
    scenes = deepcopy(context.get('source', source)['scenarios'])
    known = {str(s['scenario_id']) for s in scenes}
    for candidate in candidates:
        if candidate.payload.get('result_import', {}).get('primary'):
            for scene in candidate.payload['scenarios']:
                if str(scene['scenario_id']) not in known:
                    scenes.append(deepcopy(scene)); known.add(str(scene['scenario_id']))
    expected_contract = contract(db, config, base) if candidates else None
    results, lineage = collect(db, base, scenes, expected_contract)
    issues = w.apply_issue_exclusions(db, base.release, rows)
    eligible = {str(i['issue_id']) for i in issues if cohort_for_issue(i)}

    def missing_ids():
        mapping = {}
        for scene in scenes:
            mapping.setdefault(str(scene['issue_id']), []).append(str(scene['scenario_id']))
        return {i for i in eligible if not mapping.get(i) or any(s not in results for s in mapping[i])}

    def finish(status, **values):
        missing = missing_ids()
        state = {**previous, 'status': status, 'missing_count': len(missing),
                 'valid_issue_count': len(eligible - missing), 'issue_count': len(eligible),
                 'interval_seconds': INTERVAL_SECONDS, **values}
        w.put_state(db, key, state)
        return {'scenarios': scenes, 'results': results, 'lineage': lineage, 'state': state}

    if active:
        return finish('simulating', job_id=active.payload.get('job_id'), fingerprint=active.fingerprint)
    newly_finished = previous.get('status') == 'simulating'
    if not missing_ids():
        return finish('complete', job_id=None)
    if not newly_finished and previous.get('next_check_at') and now.isoformat() < previous['next_check_at']:
        return finish(previous['status'])

    timing = {'checked_at': now.isoformat(), 'next_check_at': (now + timedelta(seconds=INTERVAL_SECONDS)).isoformat()}
    previous.update(timing)
    # The workflow dispatcher and label worker share the release lock. A running
    # primary/other lane must finish before another job can be queued.
    if db.scalars(select(ReleaseSimulationBatch).where(ReleaseSimulationBatch.release == base.release,
                  ReleaseSimulationBatch.status.in_(ACTIVE))).first():
        return finish('waiting', job_id=None)
    finish('preparing', job_id=None)
    period = source['period']
    current = w.fetch_scenarios(period)
    index = {str(s['scenario_id']): s for s in current}
    if len(index) != len(current) or any(str(s['scenario_id']) not in index or any(
            s.get(k) != index[str(s['scenario_id'])].get(k) for k in SCENE_FIELDS) for s in scenes):
        raise ValueError('input_changed')
    mapped = {str(s['issue_id']) for s in scenes}
    needed = eligible - mapped
    scenes.extend(s for s in current if str(s['issue_id']) in needed)
    needed -= {str(s['issue_id']) for s in scenes}
    if needed:
        receipt = w.driver_call(config, 'prepare_scenes', {'period': period, 'release': base.release,
            'label': base.payload['scenario_label'],
            'issues': [{**i, 'cohort': cohort_for_issue(i)} for i in issues if str(i['issue_id']) in needed]})
        current = w.fetch_scenarios(period)
        fresh = {str(s['scenario_id']):s for s in current}
        if len(fresh) != len(current) or any(str(s['scenario_id']) not in fresh or any(
                s.get(k) != fresh[str(s['scenario_id'])].get(k) for k in SCENE_FIELDS) for s in scenes):
            raise ValueError('input_changed')
        scenes.extend(s for s in current if str(s['issue_id']) in needed)
        remaining = needed - {str(s['issue_id']) for s in scenes}
        failures = receipt.get('failures') or []
        if (receipt.get('ready') is not (not remaining) or receipt.get('failed', 0) != len(failures)
                or {str(f.get('issue_id')) for f in failures} != remaining
                or len(failures) != len(remaining)
                or any(f.get('reason') not in ('missing_bag', 'upstream_error') for f in failures)):
            raise ValueError('preparation_receipt_invalid')
    snapshot = {**source, 'issues': issues, 'scenarios': scenes}
    context = {'base_fingerprint': base.fingerprint, 'base_audit_hash': audit_hash(base.payload),
               'source_hash': activity_identity(rows, 'issue_time'), 'source': snapshot}
    source_key = 'label_source:' + digest(context)[:48]
    context['source_key'] = source_key
    w.put_state(db, source_key, context)
    previous['source_key'] = source_key
    results, lineage = collect(db, base, scenes, expected_contract)
    pending = [s for s in scenes if str(s['issue_id']) in eligible and str(s['scenario_id']) not in results]
    if not pending:
        return finish('waiting_bags', job_id=None)
    attempts = [b for b in candidates if b.payload['backfill'].get('kind') == 'label_changes']
    pending = [s for s in pending if sum(any(str(s['scenario_id']) == str(old['scenario_id'])
        for old in b.payload['scenarios']) for b in attempts) < 3]
    if not pending:
        return finish('blocked', reason='retry_limit', job_id=None)
    expected_contract = contract(db, config, base)
    from ra_api.release_labels import validate_scene_labels
    by_issue = {str(i['issue_id']): i for i in issues}
    for scene in pending:
        validate_scene_labels(scene, base.payload['scenario_label'], base.release, cohort_for_issue(by_issue[str(scene['issue_id'])]))
    ids = {str(s['issue_id']) for s in pending}
    plan = {k:deepcopy(base.payload[k]) for k in ('scenario_label', 'period', 'release', 'binary_id',
            'query_attrs', 'simulation', 'driver_revision', 'acceptance_only')}
    plan.update(template_job_id=base.payload['job_id'], population_hash=w.population_identity(snapshot),
                issues=[{k:v for k,v in i.items() if k != 'evaluation_exclusion'} for i in issues if str(i['issue_id']) in ids],
                scenarios=[{**{k:s.get(k) for k in ('scenario_id', *SCENE_FIELDS)},
                    'cohort':cohort_for_issue(by_issue[str(s['issue_id'])])} for s in pending])
    plan['period']['template_job_id'] = plan['template_job_id']
    plan['issue_tolerance'] = {'policy':dict(POLICY), 'population_hash':plan['population_hash'],
                               'eligible_issue_ids':sorted(ids), 'preparation_failures':[]}
    plan['backfill'] = {'kind':'label_changes', 'base_fingerprint':base.fingerprint,
        'source_key':source_key, 'source_hash':context['source_hash'],
        'execution_contract_hash':expected_contract, 'attempt':len(attempts)+1}
    validate_frozen(plan)
    plan['fingerprint'] = digest(plan)
    child = db.get(ReleaseSimulationBatch, plan['fingerprint'])
    if not child:
        child = ReleaseSimulationBatch(fingerprint=plan['fingerprint'], release=base.release, status='queued', payload=plan)
        db.add(child); db.commit()
    finish('simulating', fingerprint=child.fingerprint, job_id=child.payload.get('job_id'), reason=None)
    w.execute_batch(db, child, config, release=base.release)
    return finish('simulating' if child.status in ACTIVE else 'blocked', fingerprint=child.fingerprint,
                  job_id=child.payload.get('job_id'), reason=None if child.status in ACTIVE else child.status)
