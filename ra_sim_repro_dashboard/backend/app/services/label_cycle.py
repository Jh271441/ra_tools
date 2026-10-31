"""Batch label edits and recover missing results, retaining primary receipts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
from sqlalchemy import select
from app.models import ReleaseSimulationBatch, ReleaseIssueSnapshot
from app.services import release_workflow as w
from app.services.release_watch import activity_identity, fetch_activity
from app.services.release_cycle import digest
from app.services.release_metrics import cohort_for_issue, excluded_issue, summarize_population
from app.services.result_publication import publication, published_batch, audit_hash, coverage_policy
from ra_api.release_tolerance import assess, LEGACY_POLICY, POLICY, policy_for

CHECK_SECONDS = 3600
MERGE_SECONDS = 6 * 3600


def plan_revision(payload, source, rows, *, recovery=None):
    """Re-score identical physical inputs, admitting only audited recovery results."""
    old = {str(i['issue_id']): i for i in source['issues']}
    new = {str(i['issue_id']): i for i in rows}
    if len(new) != len(rows) or not new:
        raise ValueError('invalid_observation')
    from app.services.label_recovery import same_inputs
    if not same_inputs(source['issues'], rows):
        return {'status': 'needs_simulation', 'reason': 'input_changed',
                'issue_ids': sorted(old.keys() ^ new.keys())[:30]}
    if {str(i['issue_id']) for i in payload['issues']} != old.keys():
        raise ValueError('snapshot_mismatch')
    issues = deepcopy(payload['issues'])
    for row in issues:
        row['ra_merge_result'] = new[str(row['issue_id'])].get('ra_merge_result')
    raw = [{k:v for k,v in row.items() if k != 'evaluation_exclusion' or v.get('approved_by') == 'user'} for row in issues]
    if any(not cohort_for_issue(i) and not excluded_issue(i) for i in raw):
        return {'status':'blocked', 'reason':'unknown_labels'}
    scenes = recovery['scenarios'] if recovery else payload['scenarios']
    results = recovery['results'] if recovery else payload['results']
    mapping = {}
    for scene in scenes:
        mapping.setdefault(str(scene['issue_id']), []).append(str(scene['scenario_id']))
    original_exclusions = set(payload.get('publication_approval', {}).get('excluded_issue_ids', []))
    original_exclusions.update(str(i['issue_id']) for i in payload['issues'] if i.get('evaluation_exclusion'))
    invalid_scenes = {str(f['scenario_id']) for f in payload.get('result_import', {}).get('failures', [])}
    original_exclusions.update(str(s['issue_id']) for s in scenes if str(s['scenario_id']) in invalid_scenes)
    eligible = {str(i['issue_id']) for i in raw if cohort_for_issue(i)}
    missing = {i for i in eligible if not mapping.get(i) or any(
        sid not in results or not isinstance(results[sid].get('sim_triggered'), bool) for sid in mapping[i])}
    if not recovery:
        missing |= eligible & original_exclusions
    additional = missing - original_exclusions
    if additional and not recovery:
        return {'status':'needs_simulation', 'reason':'missing_results', 'issue_ids':sorted(additional)[:30], 'count':len(additional)}
    try:
        coverage = assess(eligible, missing, POLICY if recovery else policy_for(payload) if payload.get("issue_tolerance") else LEGACY_POLICY)
    except ValueError:
        return {'status':'blocked', 'reason':'coverage_gate'}
    kept = [i for i in raw if str(i['issue_id']) not in missing]
    summary = summarize_population(kept, scenes, results)
    if not summary['available'] or summary['unclassified'] or summary['missing_results']:
        raise ValueError('revision_gate_failed')
    changed = [{'issue_id':i,'before':old[i].get('ra_merge_result'),'after':new[i].get('ra_merge_result')}
               for i in sorted(old) if old[i].get('ra_merge_result') != new[i].get('ra_merge_result')]
    return {'status':'updated', 'summary':summary, 'coverage':coverage, 'issues':raw,
            'changes':changed, 'change_count':len(changed), 'excluded_issue_ids':sorted(missing),
            **({'lineage':recovery['lineage'], 'recovery':recovery['state']} if recovery else {})}


def revision_metrics(db, batch, base):
    """Overlay an audited label revision for display, retaining original execution metadata."""
    if not base:
        return base
    state = w.get_state(db, 'label_cycle:' + batch.release)
    key = state.get('revision_key')
    if not key:
        return base
    revision = w.get_state(db, key)
    if revision.get('base_audit_hash') != audit_hash(batch.payload) or not revision.get('summary', {}).get('available'):
        return base
    if revision.get('basis_backfill_revision') != base.get('backfill_revision'):
        return base
    hashes = {}
    for item in revision.get('lineage', {}).values():
        fingerprint = item['fingerprint']
        if fingerprint not in hashes:
            execution = db.get(ReleaseSimulationBatch, fingerprint)
            hashes[fingerprint] = audit_hash(execution.payload) if execution else None
        if not hashes[fingerprint] or hashes[fingerprint] != item['audit_hash']:
            return base
    return {**base, **revision['summary'],
            'generated_at':revision['applied_at'],
            'label_revision':{k:revision[k] for k in ('revision_key','applied_at','source_hash','change_count')},
            'publication':{**base.get('publication', {}), **revision['coverage'],
                           'excluded_issue_ids':revision['excluded_issue_ids'],
                           'label_revision_key':key,
                           **({'source_job_ids':sorted({item['job_id'] for item in revision['lineage'].values()})}
                              if revision.get('lineage') else {})}}


def public_state(db, release, now=None):
    now = now or datetime.now(timezone.utc)
    state = w.get_state(db, 'label_cycle:' + release)
    if not state:
        return {'enabled':os.getenv('LABEL_REFRESH_ENABLED') == '1', 'status':'waiting',
                'check_seconds':CHECK_SECONDS,'merge_seconds':MERGE_SECONDS}
    value = {k:v for k,v in state.items() if k not in ('revision_key', 'candidate_hash')}
    value['enabled'] = os.getenv('LABEL_REFRESH_ENABLED') == '1'
    value.update(check_seconds=CHECK_SECONDS, merge_seconds=MERGE_SECONDS)
    if value.get('recovery', {}).get('job_id'):
        progress = w.get_state(db, f"job-progress:{value['recovery']['job_id']}")
        value['recovery'] = {**value['recovery'], 'progress':progress.get('value')}
    last = state.get('checked_at')
    if last:
        value['next_check_at'] = (datetime.fromisoformat(last)+timedelta(seconds=CHECK_SECONDS)).isoformat()
    if state.get('pending_since') and state.get('pending_count'):
        value['next_process_at'] = (datetime.fromisoformat(state['pending_since'])+timedelta(seconds=MERGE_SECONDS)).isoformat()
    if last and (now - datetime.fromisoformat(last)).total_seconds() > CHECK_SECONDS * 3:
        value.update(status='source_error', reason='stale')
    return value


def fetch_observed_activity(db, config, release, now):
    """Reuse a validated full observation instead of querying Trail twice per cycle."""
    from app.services.label_recovery import INPUT_FIELDS
    observed = w.get_state(db, 'release_observation:' + release)
    monitor = w.get_state(db, 'release_monitor:' + release)
    try:
        age = (now - datetime.fromisoformat(observed['observed_at'])).total_seconds()
        rows = observed['issues']
        if (0 <= age < CHECK_SECONDS and monitor.get('status') != 'source_error'
                and monitor.get('contract_hash') == digest(config.get('contract', {}))
                and observed.get('release') == release
                and all(all(k in row for k in INPUT_FIELDS) for row in rows)
                and activity_identity(rows, 'issue_time') == observed.get('activity_hash') == monitor.get('activity_hash')):
            return release, rows
    except (KeyError, TypeError, ValueError):
        pass
    target, rows = fetch_activity(config, release)
    # A fresh full query makes missing values explicit; old compact projections
    # cannot prove whether physical inputs changed.
    return target, [{**row, **{k:row.get(k) for k in INPUT_FIELDS}} for row in rows]


def refresh_release(db, config, batch, *, now=None, fetcher=None):
    now = now or datetime.now(timezone.utc)
    key = 'label_cycle:' + batch.release
    previous = w.get_state(db, key)
    base_hash = audit_hash(batch.payload)
    def save(**values):
        state = {**previous, 'enabled':True, 'check_seconds':CHECK_SECONDS, 'merge_seconds':MERGE_SECONDS,
                 'checked_at':now.isoformat(), 'next_check_at':(now+timedelta(seconds=CHECK_SECONDS)).isoformat(), **values}
        w.put_state(db, key, state)
        return state
    try:
        save(status='checking', reason=None)
        target, rows = fetcher(config, batch.release) if fetcher else fetch_observed_activity(db, config, batch.release, now)
        if target != batch.release:
            raise ValueError('version_mismatch')
        identity = activity_identity(rows, 'issue_time')
        snapshots = db.scalars(select(ReleaseIssueSnapshot).where(ReleaseIssueSnapshot.release == batch.release).order_by(ReleaseIssueSnapshot.id.desc()).execution_options(yield_per=1))
        try:
            source = next((s.payload for s in snapshots if s.payload.get('population_complete')
                           and w.population_identity(s.payload) == batch.payload.get('population_hash')), None)
        finally:
            snapshots.close()
        if not source:
            return save(status='blocked', reason='snapshot_missing')
        frozen_hash = activity_identity(source['issues'], 'issue_time')
        # Invalidate a previous revision when upstream returns to the frozen labels.
        if identity == frozen_hash:
            return save(status='idle', reason=None, change_count=0, pending_count=0,
                        revision_key=None, candidate_hash=None, pending_since=None, next_process_at=None,
                        applied_at=None, valid_issue_count=None, applied_source_hash=identity, recovery={})
        revision_key = 'label_revision:' + digest({'base':base_hash,'source':identity})[:48]
        existing = w.get_state(db, revision_key)
        from app.services.release_backfill import revision_metrics as backfill_metrics
        backfill_basis = (backfill_metrics(db, batch, publication(batch)) or {}).get('backfill_revision')
        recovery_state = w.get_state(db, 'label_recovery:' + batch.release)
        recovering = recovery_state.get('missing_count', 0) > 0
        pointed = w.get_state(db, previous.get('revision_key', 'label_revision:none'))
        if (not existing and pointed.get('source_hash') == identity
                and pointed.get('base_audit_hash') == base_hash):
            existing = pointed
            revision_key = pointed['revision_key']
        basis_changed = bool(existing) and existing.get('basis_backfill_revision') != backfill_basis
        if existing and not recovering and not basis_changed:
            return save(status='idle', reason=None, revision_key=revision_key, candidate_hash=None,
                        applied_source_hash=identity, change_count=existing['change_count'], pending_count=0,
                        applied_at=existing['applied_at'], valid_issue_count=existing['summary']['eligible'])
        original_labels = {i['issue_id']:i.get('ra_merge_result') for i in source['issues']}
        count = sum(r.get('ra_merge_result') != original_labels.get(r['issue_id']) for r in rows)
        # Fixed batching window: ongoing label edits do not keep postponing processing.
        pending_since = previous.get('pending_since') if previous.get('candidate_hash') else now.isoformat()
        due = datetime.fromisoformat(pending_since) + timedelta(seconds=MERGE_SECONDS)
        if now < due and not recovering and not basis_changed:
            return save(status='queued', reason=None, candidate_hash=identity, pending_since=pending_since,
                        next_process_at=due.isoformat(), pending_count=count)
        policy = coverage_policy(config)
        if not policy['enabled']:
            return save(status='paused', reason='publication_disabled', pending_count=count)
        if w.get_state(db, 'settings', {'mode':'manual'}).get('mode') != 'auto':
            return save(status='paused', reason='manual_mode', pending_count=count)
        revision = plan_revision(batch.payload, source, rows)
        from app.services import label_recovery
        has_children = bool(label_recovery.children(db, batch))
        if revision.get('reason') == 'missing_results' or ((recovering or has_children) and revision.get('reason') in (None, 'coverage_gate')):
            save(status='recovering', reason=None, pending_count=count)
            from app.services.label_recovery import recover
            recovered = recover(db, config, batch, source, rows, now)
            revision = plan_revision(batch.payload, source, rows, recovery=recovered)
        if revision['status'] != 'updated':
            return save(**revision, candidate_hash=identity, pending_since=pending_since, pending_count=count,
                        recovery=w.get_state(db, 'label_recovery:' + batch.release))
        if revision['coverage']['issue_coverage'] < policy['minimum_coverage']:
            return save(status='blocked', reason='coverage_gate', candidate_hash=identity,
                        pending_since=pending_since, pending_count=count)
        db.refresh(batch)
        if audit_hash(batch.payload) != base_hash or not publication(batch):
            return save(status='blocked', reason='execution_changed')
        revision_key = 'label_revision:' + digest({'base':base_hash, 'source':identity,
            'lineage':revision.get('lineage'), 'backfill':backfill_basis})[:48]
        revision.update(revision_key=revision_key,base_audit_hash=base_hash,source_hash=identity,
                        basis_backfill_revision=backfill_basis,
                        base_job_id=batch.payload['job_id'],applied_at=now.isoformat())
        # Ledger and pointer are committed together; original batch is never rewritten.
        from app.models import ReleaseWorkflowState
        existing_revision = db.get(ReleaseWorkflowState, revision_key)
        if not existing_revision:
            db.add(ReleaseWorkflowState(key=revision_key,payload=revision))
        else:
            revision = existing_revision.payload
        recovery_state = w.get_state(db, 'label_recovery:' + batch.release) if 'recovery' in revision else {}
        return save(status='recovering' if recovery_state.get('missing_count') else 'updated',
                    reason=None, revision_key=revision_key, applied_source_hash=identity, recovery=recovery_state,
                    candidate_hash=None,pending_since=None,next_process_at=None,pending_count=0,change_count=revision['change_count'],
                    applied_at=revision['applied_at'],valid_issue_count=revision['summary']['eligible'])
    except Exception as exc:
        db.rollback()
        return save(status='source_error', reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                    recovery=w.get_state(db, 'label_recovery:' + batch.release))


def tick():
    if os.getenv('LABEL_REFRESH_ENABLED') != '1':
        return
    from app.database import SessionLocal
    from app.config import DATA_DIR
    lock = Path(os.getenv('RELEASE_WORKFLOW_LOCK', str(DATA_DIR/'release-workflow.lock'))).with_name('label-cycle.lock')
    release_lock = Path(os.getenv('RELEASE_WORKFLOW_LOCK', str(DATA_DIR/'release-workflow.lock')))
    with release_lock.open('w') as release_stream, lock.open('w') as stream:
        try:
            fcntl.flock(release_stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with SessionLocal() as db:
            config = w.effective_config(db)
            releases = set(db.scalars(select(ReleaseSimulationBatch.release)))
            for release in sorted(releases):
                batch = published_batch(db,release)
                # Start from watched releases, never silently backfill the historical archive.
                if batch and w.get_state(db,'release_monitor:'+release):
                    previous = w.get_state(db, 'label_cycle:' + release)
                    try:
                        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(previous['checked_at'])).total_seconds()
                        if 0 <= elapsed < CHECK_SECONDS:
                            continue
                    except (KeyError, TypeError, ValueError):
                        pass
                    refresh_release(db,config,batch)
