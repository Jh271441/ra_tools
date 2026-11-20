"""Durable Resume requests consumed under the release workflow file lock."""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import ReleaseWorkflowState
from app.services import release_workflow as w
from app.services.release_backfill import ACTIVE, executions, original, refresh_release


def public_state(db, release):
    state = w.get_state(db, 'resume:' + release)
    batches = executions(db, release)
    last = batches[-1] if batches else None
    return {**state, 'enabled':bool(batches or w.get_state(db,'release_monitor:' + release)), 'fingerprint':last.fingerprint if last else None,
        'checkpoint': 'execute' if last and last.status in ACTIVE else
            'verify' if last and last.payload.get('result_import') else 'prepare'}


def request(db, release, fingerprint=None):
    config = w.effective_config(db)
    if (release not in {p['release'] for p in config.get('periods', [])}
            and not w.get_state(db, 'release_monitor:' + release)):
        raise ValueError('unknown_release')
    if w.get_state(db, 'settings', {'mode':'manual'}).get('mode') != 'auto':
        raise ValueError('manual_mode')
    batches = executions(db, release)
    if fingerprint != (batches[-1].fingerprint if batches else None):
        raise ValueError('checkpoint_changed')
    key = 'resume:' + release
    state = w.get_state(db, key)
    if state.get('status') in ('requested', 'running'):
        return state
    value = {'release':release,'status':'requested','requested_at':datetime.now(timezone.utc).isoformat()}
    try:
        w.put_state(db, key, value)
    except IntegrityError:
        db.rollback()
        return w.get_state(db, key)
    return value


def process_requests(db, config):
    requests = list(db.scalars(select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith('resume:'))))
    for item in requests:
        if item.payload.get('status') not in ('requested', 'running'):
            continue
        release = item.payload['release']; previous = dict(item.payload)
        def save(**values):
            w.put_state(db, 'resume:' + release, {**previous, **values})
        save(status='running')
        try:
            if w.get_state(db, 'settings', {'mode':'manual'}).get('mode') != 'auto':
                raise ValueError('manual_mode')
            batches = executions(db, release)
            active = next((b for b in reversed(batches) if b.status in ACTIVE), None)
            if active:
                if active.status == 'queued':
                    # Automatic plans require a fresh quiet-window observation.
                    if active.payload.get('backfill'):
                        w.execute_batch(db, active, config, release=release)
                    else:
                        from app.services.release_watch import monitor_tick
                        monitor_tick(db, config, release=release, update_latest=False)
                # Poll/reconcile an existing Job. Never reset uncertain submissions.
                w.poll_batches(db, config)
                save(status='complete', outcome='tracking', job_id=active.payload.get('job_id'))
                continue
            base = original(db, release)
            if base:
                result = refresh_release(db, config, base, force=True)
                save(status='blocked' if result['status'] == 'blocked' else 'complete',
                     outcome=result['status'],reason=result.get('reason'),job_id=result.get('job_id'))
                continue
            # Preflight has no external side effect. Retain its audit and recheck
            # the full source instead of blindly reusing a stale preparation plan.
            for b in batches:
                if not b.payload.get('job_id') and b.status == 'preflight_failed':
                    current = w.make_plan(db, config, release=release)
                    if current['fingerprint'] == b.fingerprint:
                        b.status='queued'; db.commit()
                    else:
                        b.status='cancelled_stale'; db.commit()
            period = next((p for p in config.get('periods',[]) if p['release']==release), {})
            if period and period.get('completion_rule') not in ('issue_inactivity_24h','issue_last_time_24h'):
                w.sync_once(db,config,release=release)
                w.prepare_missing_scenes(db,config,release=release)
                plan=w.make_plan(db,config,release=release)
                batch=w.queue_plan(db,plan['fingerprint'],config,release=release)
                if batch.status=='preflight_failed':
                    batch.status='queued';db.commit()
                w.execute_batch(db,batch,config,release=release)
                result={'status':batch.status,'job_id':batch.payload.get('job_id'),'error':batch.payload.get('error')}
            else:
                from app.services.release_watch import monitor_tick
                result = monitor_tick(db, config, release=release, update_latest=False)
            save(status='blocked' if result['status'] in ('blocked','source_error','preflight_failed','cancelled_stale') else 'complete',
                 outcome=result['status'],reason=result.get('error'),job_id=result.get('job_id'))
        except Exception as exc:
            db.rollback()
            save(status='blocked',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
