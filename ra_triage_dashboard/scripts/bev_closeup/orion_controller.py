"""Personal Orion production and bounded download controller for this task only."""
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import offline_daily as daily

ROOT = Path('/volume/home/workspace/ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029')
REPO = Path('/volume/home/workspace/ra_auto_triage')
HERE = ROOT / 'orion'
PYTHON = REPO / '.venv-ares-animation/bin/python'
MAX_CONCURRENCY = 1000


def bootstrap():
    sys.path.insert(0, str(REPO))
    if os.environ.get('BEV_ORION_ENV_READY') != '1':
        from ares_animation.adapters.voyager import load_voyager_environment
        _, env = load_voyager_environment()
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
            env.pop(key, None)
        env.update(BEV_ORION_ENV_READY='1', no_proxy='*', NO_PROXY='*')
        os.execve(str(PYTHON), [str(PYTHON), '-u', str(Path(__file__).resolve())], env)


def main():
    bootstrap()
    sys.path.insert(0, str(HERE))
    import pipeline as P
    sys.path.insert(0, str(ROOT / 'code/ra_triage_dashboard/scripts/bev_closeup'))
    import coordinator as legacy
    import inventory
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
    from voy_data_utils.storage_locator import StorageLocator
    from ares_animation.orion.download import _materialize_task

    canary = json.loads((HERE / 'canary-acceptance.json').read_text())
    P.require(canary.get('status') == 'passed' and canary.get('visual_review') == 'passed', 'canary_gate')
    migration = json.loads((ROOT/'updates/orion-migration-v1/activation.json').read_text())
    P.require(migration.get('state') == 'online_stopped_at_batch_boundary' and (ROOT/'STOP').exists(), 'online_must_stop_at_boundary')
    lock = (ROOT / 'worker.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Never overlap a legacy renderer/coordinator even if a stale state file says stopped.
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc/'cmdline').read_bytes().decode(errors='replace').split('\0')
            cwd = os.readlink(proc/'cwd')
            P.require(not (cwd in (str(ROOT),str(ROOT/'runtime')) and any(a.endswith('/coordinator.py') or a.endswith('/renderer.py') for a in argv)), 'online_process_still_active')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    db = sqlite3.connect(ROOT/'queue.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    frozen = json.loads((ROOT/'membership.json').read_text())
    members = frozen['members']
    ids = sorted(members if isinstance(members,dict) else [r['issue_id'] for r in members])
    P.require(hashlib.sha256('\n'.join(ids).encode()).hexdigest() == '0dccda0011faa90c15b9649b0aa08ecbd28ba5351bf4948279129e5a9441caa2', 'frozen_digest')
    P.require(set(ids) == {r[0] for r in db.execute('select issue_id from members where frozen=1')}, 'frozen_members_changed')
    backup = HERE/'queue-before-orion.sqlite3'
    if not backup.exists():
        target = sqlite3.connect(backup)
        db.backup(target)
        target.close()
    manifest_path = HERE/'jobs.json'
    jobs = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    # Reconcile already submitted, bounded recovery jobs under the same publisher lock.
    for registration_path in sorted((HERE/'recoveries').glob('*/recovery-registration.json')):
        registration = json.loads(registration_path.read_text())
        if registration.get('state') != 'submitted' or any(j.get('job_id') == registration.get('job_id') for j in jobs):
            continue
        run = registration_path.parent
        launch = json.loads((run/'launch.receipt.json').read_text())
        sources = run/'source-rows.json'
        rows = json.loads(sources.read_text())
        P.require(registration.get('attempt_number',99) <= registration.get('total_attempt_limit',3)
                  and launch.get('status') == 'submitted' and launch.get('username') == 'jasperchen'
                  and launch.get('job_id') == registration['job_id'] and launch.get('task_count') == len(rows)
                  and P.sha(sources) == registration['source_sha256'], 'recovery_registration_mismatch')
        parent = next(j for j in jobs if j.get('job_id') == registration['original_job_id'])
        originals = {r['issue_id']:r for r in json.loads(Path(parent['source_rows']).read_text())}
        P.require(all(row == originals.get(row['issue_id']) for row in rows), 'recovery_source_changed')
        jobs.append(dict(run=str(run),source_rows=str(sources),source_sha256=P.sha(sources),count=len(rows),
                         state='submitted',job_id=launch['job_id'],max_concurrency=launch['max_concurrency'],
                         original_job_id=registration['original_job_id'],attempt_number=registration['attempt_number']))
        P.save(manifest_path,jobs)

    def event(kind, **payload):
        db.execute('insert into events(at,kind,payload) values(?,?,?)', (time.time(),kind,json.dumps(payload)))
        db.commit()

    def progress(state, **extra):
        counts = dict(db.execute('select state,count(*) from jobs group by state').fetchall())
        versions, source = collections.defaultdict(dict), collections.defaultdict(dict)
        for version, status, count in db.execute('select m.version,j.state,count(*) from jobs j join members m using(issue_id) group by m.version,j.state'):
            versions[version][status] = count
        for version, status, ready, count in db.execute('select version,source_state,source_status,count(*) from members group by version,source_state,source_status'):
            source[version][status+':'+ready] = count
        P.save(ROOT/'progress.json', dict(state=state,checked_at=time.time(),pid=os.getpid(),cwd=str(ROOT),
            producer='ares_animation_orion',recipe_id=P.RECIPE,workers=MAX_CONCURRENCY,
            local_download_workers=4,total=sum(counts.values()),verified=counts.get('verified',0),
            states=counts,versions=dict(versions),source_members=dict(source),current=None,
            main_pipeline_affected=False,orion_jobs=[{'job_id':j.get('job_id'),'state':j.get('state'),'tasks':j.get('count')} for j in jobs],**extra))

    # Canary production is reusable; existing verified Capture media is retained.
    for row in json.loads((HERE/'canary-source-rows.json').read_text()):
        issue = row['issue_id']
        previous = db.execute('select state from jobs where issue_id=?',(issue,)).fetchone()
        if previous and previous['state'] == 'verified':
            continue
        evidence = HERE/'canary/verification'/issue
        result = json.loads((evidence/'verification.json').read_text())
        result['visual_review'] = 'passed'
        receipt = P.publish(HERE/'canary/downloads'/issue,evidence,result)
        if previous and previous['state'] != 'verified':
            db.execute("update jobs set state='verified',finished_at=?,error=NULL,batch=? where issue_id=?",(time.time(),str(HERE/'canary'),issue))
            event('orion_canary_verified',issue_id=issue,sha256=receipt['sha256'],job_id=48919603)
    db.commit()
    event('orion_controller_started',pid=os.getpid(),mapper_limit=MAX_CONCURRENCY,legacy_media_retained=True)
    last_discovery = 0
    validation_failures = {}
    for record in jobs:
        failure_path = Path(record['run'])/'validation-failures.json'
        if failure_path.exists():
            validation_failures.update(json.loads(failure_path.read_text()))
    while not (HERE/'STOP').exists():
        profile = daily.control(ROOT)
        needs_review = bool(validation_failures)
        observation_unavailable = False
        resource_wait = False
        progress('orion_results_require_review' if needs_review else 'collecting')
        if time.time()-last_discovery >= 3600:
            try:
                delta = inventory.build_snapshot('/volume/home/workspace/ra_triage_dashboard_data/media_layouts', incremental=True)
                P.save(ROOT/'discoveries'/f'{int(time.time())}.json', delta)
                legacy.enqueue(db,delta,False)
                legacy.sync_verified_scopes(db,P.MEDIA)
                last_discovery = time.time()
            except Exception as exc:
                event('orion_discovery_failed',code=type(exc).__name__)
                last_discovery = time.time()-3300
        if not daily.enabled(profile):
            progress('scheduled', next_action_at=profile['not_before'] if profile else None)
            time.sleep(30)
            continue
        if daily.resource_ready(ROOT):
            daily.publish_local_ready(ROOT, db, P, profile)
        try:
            daily.retry_tick(ROOT, jobs, db, profile, PYTHON) if daily.resource_ready(ROOT) else None
            P.save(ROOT/'daily-sidecar/recovery-error.json', dict(active=False, at=time.time()))
        except Exception as exc:
            event('automatic_recovery_requires_review', code=type(exc).__name__)
            P.save(ROOT/'daily-sidecar/recovery-error.json', dict(active=True, code=type(exc).__name__, at=time.time()))
            needs_review = True
        active = sorted([j for j in jobs if j.get('state') not in ('terminal','audited')],
                        key=lambda j: not bool(j.get('original_job_id')))
        if not active and daily.resource_ready(ROOT):
            eligible = db.execute("select issue_id,row_json from jobs where state in ('queued','retry_wait') order by issue_id").fetchall()
            if eligible:
                stamp = time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
                run = HERE/'runs'/stamp
                run.mkdir(parents=True)
                rows = [json.loads(r['row_json']) for r in eligible]
                sources = run/'source-rows.json'
                P.save(sources,rows)
                record = dict(run=str(run),source_rows=str(sources),source_sha256=P.sha(sources),count=len(rows),state='preparing',created_at=time.time())
                jobs.append(record)
                P.save(manifest_path,jobs)
                command = daily.orion_command(PYTHON,sources,run,profile['layout'],len(rows),'ra_bev_closeup_'+stamp)
                with (run/'submit.log').open('a') as log:
                    result = subprocess.run(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
                launch = run/'launch.receipt.json'
                launch_value = json.loads(launch.read_text()) if launch.exists() else {}
                if (not launch.exists() or launch_value.get('status') != 'submitted'
                        or launch_value.get('username') != 'jasperchen' or launch_value.get('task_count') != len(rows)):
                    record['state']='submission_requires_review'
                    record['returncode']=result.returncode
                    P.save(manifest_path,jobs)
                    progress('orion_submission_requires_review')
                    raise RuntimeError('Submission outcome requires read-only reconciliation; never resubmit blindly')
                receipt=json.loads(launch.read_text())
                record.update(job_id=receipt['job_id'],state='submitted',submitted_at=time.time(),max_concurrency=receipt['max_concurrency'])
                P.save(manifest_path,jobs)
                for row in rows:
                    db.execute("update jobs set state='running',batch=?,started_at=?,error=NULL where issue_id=? and state in ('queued','retry_wait')",(str(run),time.time(),row['issue_id']))
                event('orion_submitted',job_id=record['job_id'],count=len(rows),max_concurrency=record['max_concurrency'])
                active=[record]
        for record in active:
            if (HERE/'STOP').exists():
                break
            if not record.get('job_id'):
                progress('orion_submission_requires_review')
                raise RuntimeError('Unresolved submission registration')
            run=Path(record['run'])
            P.require(P.sha(record['source_rows']) == record['source_sha256'],'source_rows_changed')
            rows={r['issue_id']:r for r in json.loads(Path(record['source_rows']).read_text())}
            try:
                with TrailRegionMgr(Regions.CN):
                    tasks=list(TaskAccessor.query_by_job(record['job_id'],kind=OrionTask.MAPPER,extra_fields='user_result,task_args,outcome,outcome_detail'))
            except Exception as exc:
                event('orion_observation_unavailable',job_id=record['job_id'],code=type(exc).__name__)
                observation_unavailable = True
                continue
            counts=collections.Counter(OrionTask.Status.Name(t['status']).lower() for t in tasks)
            native_ids = set()
            for task in tasks:
                parts = str(task.get('signature','')).rsplit('-',2)
                P.require(task.get('job_id') == record['job_id'] and len(parts)==3
                          and parts[0] in rows and parts[1]==str(rows[parts[0]]['capture_timestamp_ms'])
                          and parts[0] not in native_ids, 'native_task_source_identity_mismatch')
                native_ids.add(parts[0])
            P.save(run/'status.json',dict(observed_at=time.time(),job_id=record['job_id'],total=len(tasks),counts=dict(counts),
                   failure_status_values=[OrionTask.FAILED,OrionTask.CANCELLED]))
            failed = [t for t in tasks if t['status'] in (OrionTask.FAILED,OrionTask.CANCELLED)]
            failure_evidence = run/'native-failed-tasks.json'
            if failed:
                P.save(failure_evidence,json.loads(json.dumps(failed,default=str)))
                failure_evidence.chmod(0o600)
                unresolved_failed = [t for t in failed if db.execute('select state from jobs where issue_id=?',
                    (str(t['signature']).rsplit('-',2)[0],)).fetchone()['state'] != 'verified']
                needs_review = needs_review or bool(unresolved_failed)
            run_failures = daily.read(run/'validation-failures.json')
            completed = {(task.get('user_result') or {}).get('issue_id'): task for task in tasks if task['status'] == OrionTask.COMPLETED}
            verified_ids = {r[0] for r in db.execute("select issue_id from jobs where state='verified'")}
            _, due = daily.completed_pending(rows,completed,verified_ids,run_failures)
            pending = [(completed[issue], rows[issue]) for issue in due]
            def download_verify(item):
                task,row=item
                folder=_materialize_task(task,run/'downloads',locator_type=StorageLocator,media_mode='video-only',directory_strategy='source',resume=True)
                evidence=run/'verification'/row['issue_id']
                checked=P.verify_download(folder,row,evidence)
                checked['visual_review']='representative_canary_passed'
                P.save(evidence/'verification.json',checked)
                return row,P.publish(folder,evidence,checked)
            resources = legacy.resource_state()
            disk = os.statvfs(ROOT)
            if disk.f_bavail * disk.f_frsize < 10*1024**3:
                resources = dict(resources,status='disk_wait')
            if pending and resources['status']!='ready':
                resource_wait = True
            if pending and resources['status']=='ready':
                with ThreadPoolExecutor(max_workers=4) as pool:
                    # Bounded batches keep status fresh and permit safe maintenance between files.
                    futures={pool.submit(download_verify,item):item[1]['issue_id'] for item in pending[:128]}
                    for future in as_completed(futures):
                        issue=futures[future]
                        try:
                            row,receipt=future.result()
                            db.execute("update jobs set state='verified',finished_at=?,error=NULL,batch=? where issue_id=?",(time.time(),str(run),issue))
                            validation_failures.pop(issue,None)
                            run_failures.pop(issue,None)
                            P.save(run/'validation-failures.json',run_failures)
                            event('orion_verified',issue_id=issue,job_id=record['job_id'],sha256=receipt['sha256'])
                            progress('orion_results_require_review' if validation_failures else 'collecting')
                        except Exception as exc:
                            # Keep the full evidence in its original output; public state carries a category only.
                            previous=run_failures.get(issue) or {}
                            attempts=previous.get('attempts',0)+1 if isinstance(previous,dict) else 1
                            run_failures[issue]=dict(code=type(exc).__name__,reason=str(exc)[:240],attempts=attempts,
                                retryable=not isinstance(exc,(ValueError,FileExistsError)),next_retry_at=time.time()+min(1800,60*2**attempts))
                            validation_failures[issue] = run_failures[issue]
                            P.save(run/'validation-failures.json',run_failures)
                            event('orion_verification_requires_review',issue_id=issue,code=type(exc).__name__)
                            needs_review = True
            terminal=all(t['status'] in (OrionTask.COMPLETED,OrionTask.FAILED,OrionTask.CANCELLED) for t in tasks) and len(tasks)==record['count']
            if terminal:
                verified_ids = {r[0] for r in db.execute("select issue_id from jobs where state='verified'")}
                waiting, _ = daily.completed_pending(rows,completed,verified_ids,run_failures)
                unresolved=[issue for issue in rows if db.execute('select state from jobs where issue_id=?',(issue,)).fetchone()['state']!='verified']
                if unresolved:
                    P.save(run/'unresolved.json',dict(issue_ids=unresolved,counts=dict(counts),validation_failures=validation_failures))
                    progress('orion_results_require_review')
                    needs_review = True
                if not waiting:
                    record.update(state='terminal' if unresolved else 'audited',completed_at=time.time())
                    P.save(manifest_path,jobs)
                    event('orion_batch_drained',job_id=record['job_id'],count=record['count'],unresolved=len(unresolved))
                if not unresolved:
                    record.update(state='audited',completed_at=time.time())
                    P.save(manifest_path,jobs)
                    event('orion_batch_verified',job_id=record['job_id'],count=record['count'])
        state=('orion_results_require_review' if needs_review or validation_failures else
               'orion_observation_unavailable' if observation_unavailable else
               'download_resource_wait' if resource_wait else 'collecting' if active else 'idle')
        progress(state)
        if not (HERE/'STOP').exists():
            time.sleep(10 if active else 60)
    progress('stopped')


if __name__ == '__main__':
    main()
