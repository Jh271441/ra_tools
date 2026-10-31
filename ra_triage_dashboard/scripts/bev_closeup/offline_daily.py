"""Daily closeup policy. Called by the owned Orion and original media controllers.

Orion owns its task lock and publications. The original media controller owns
local admission, so both BEV tracks share its two slots and durable claims.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time

TASK = Path('/volume/home/workspace/ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029')
REPO = Path('/volume/home/workspace/ra_auto_triage')
LAYOUT_SHA = '613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575'
RECIPE = 'ego30-forward4-1080p-10fps-v1'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {} if default is None else default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.pending')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def control(root=TASK):
    value = read(root/'daily-sidecar/control.json')
    if value.get('enabled') is not True:
        return None
    if value.get('recipe_id') != RECIPE or value.get('layout_sha256') != LAYOUT_SHA:
        raise ValueError('daily_closeup_profile_mismatch')
    if sha(value['layout']) != LAYOUT_SHA:
        raise ValueError('daily_closeup_layout_changed')
    for file, expected in value.get('code_sha256', {}).items():
        target = (Path(value['code'])/file).resolve()
        target.relative_to(Path(value['code']).resolve())
        if sha(target) != expected:
            raise ValueError('daily_closeup_pinned_code_changed')
    for file, expected in value.get('frozen_executor_sha256', {}).items():
        if sha(file) != expected:
            raise ValueError('daily_closeup_dependency_changed')
    return value


def enabled(value, now=None):
    return bool(value and (time.time() if now is None else now) >= value['not_before'])


def identity(row):
    return row['issue_id'], row['trip_id'], row['capture_timestamp_ms']


def blocked_sources(root):
    blocked = set()
    for path in (root/'local-fallback').glob('*/state.json'):
        for row in read(path).get('remaining', []):
            if row.get('disposition') in {'source_planning_message_malformed',
                    'source_pose_gateway_missing_first_3_frozen_frames'}:
                blocked.add((row['issue_id'], row['trip_id'], row['anchor_ms']))
    return blocked


def failed_rows(record, root):
    """Require native terminal evidence and exact source identities; no SDK reads."""
    if record.get('state') not in {'terminal', 'audited'}:
        return []
    run = Path(record['run']).resolve()
    run.relative_to(root.resolve())
    source = Path(record['source_rows']).resolve()
    source.relative_to(root.resolve())
    if sha(source) != record['source_sha256']:
        raise ValueError('daily_retry_source_changed')
    rows = read(source, [])
    by_id = {r['issue_id']: r for r in rows}
    status = read(run/'status.json')
    counts = status.get('counts', {})
    if (status.get('job_id') != record['job_id'] or status.get('total') != len(rows)
            or record.get('count') != len(rows) or len(by_id) != len(rows)
            or any(type(n) is not int or n < 0 for n in counts.values())
            or sum(counts.values()) != len(rows)
            or sum(counts.get(k, 0) for k in ['completed', 'failed', 'cancelled']) != len(rows)):
        raise ValueError('daily_retry_requires_actual_terminal_status')
    failures = set()
    native = read(run/'native-failed-tasks.json', [])
    for task in native:
        parts = str(task.get('signature', '')).rsplit('-', 2)
        if (task.get('job_id') != record['job_id'] or len(parts) != 3
                or task.get('status') not in status.get('failure_status_values', [4])
                or parts[0] not in by_id
                or parts[1] != str(by_id[parts[0]]['capture_timestamp_ms'])):
            raise ValueError('daily_retry_task_identity_mismatch')
        failures.add(parts[0])
    if len(native) != counts.get('failed', 0) + counts.get('cancelled', 0) or len(failures) != len(native):
        raise ValueError('daily_retry_failure_count_mismatch')
    failures.update(set(read(run/'validation-failures.json')) & set(by_id))
    return [by_id[i] for i in sorted(failures)]


def completed_pending(rows, completed_ids, verified_ids, failures, now=None):
    """Include delayed download retries when deciding whether a batch is drained."""
    now = time.time() if now is None else now
    pending, due = [], []
    for issue in completed_ids:
        if issue not in rows:
            raise ValueError('unexpected_orion_result')
        if issue in verified_ids:
            continue
        failure = failures.get(issue)
        if failure and not (isinstance(failure, dict) and failure.get('retryable')
                            and failure.get('attempts', 0) < 3):
            continue
        pending.append(issue)
        if not failure or now >= failure.get('next_retry_at', 0):
            due.append(issue)
    return pending, due


def recovery_plan(root, jobs, published):
    """Preserve old manual/extra attempts; only allocate one automatic retry."""
    blocked = blocked_sources(root)
    attempts = {}
    for job in jobs:
        if not job.get('job_id'):
            raise ValueError('unresolved_submission_requires_review')
        if sha(job['source_rows']) != job['source_sha256']:
            raise ValueError('daily_source_changed')
        for row in read(job['source_rows'], []):
            attempts.setdefault(identity(row), []).append((job.get('attempt_number', 1), job))
    retry, local, failures_by_job = {}, {}, {}
    for key, history in attempts.items():
        if key in blocked or key in published:
            continue
        highest = max(n for n, _ in history)
        last = [(n, job) for n, job in history if n == highest]
        if len(last) != 1 or highest > 2:
            continue
        _, job = last[0]
        if job['job_id'] not in failures_by_job:
            failures_by_job[job['job_id']] = failed_rows(job, root)
        for row in failures_by_job[job['job_id']]:
            if identity(row) != key:
                continue
            target = retry if highest == 1 else local
            target.setdefault(job['job_id'], dict(parent=job, rows=[]))['rows'].append(row)
    return dict(retry=list(retry.values()), local=list(local.values()), blocked=len(blocked))


def published_identities(db):
    return {identity(json.loads(r[0])) for r in db.execute("SELECT row_json FROM jobs WHERE state='verified'")}


def orion_command(python, source, run, layout, count, designation):
    return [str(python), '-m', 'ares_animation', 'run-orion', '--source-rows', str(source),
            '--layout-json', str(layout), '--release', str(REPO/'ares_animation/releases/bd9f187.json'),
            '--video-size', '1920x1080', '--video-duration-ms', '40000', '--video-fps', '10',
            '--no-bev-frames', '--designation', designation, '--max-concurrency', str(min(1000, count)),
            '--reduce-workers', '2', '--map-margin-m', '250', '--deadline-sec', '1800',
            '--artifact-retention-days', '60', '--demand', 'cpu_cores>=8 AND memory_gb>=24',
            '--cluster', 'prod_gen4', '--region', 'CN', '--expect-user', 'jasperchen',
            '--out', str(run), '--submit']


def retry_tick(root, jobs, db, profile, python):
    if not enabled(profile):
        return
    plan = recovery_plan(root, jobs, published_identities(db))
    for group in plan['retry']:
        parent, rows = group['parent'], group['rows']
        run = root/'orion/recoveries'/f"automatic-{parent['job_id']}-retry1"
        run.mkdir(parents=True, exist_ok=True)
        source = run/'source-rows.json'
        if source.exists():
            # A persisted intent without a registered Job is uncertain, never replay it.
            raise ValueError('automatic_retry_intent_requires_reconciliation')
        save(source, rows)
        record = dict(run=str(run), source_rows=str(source), source_sha256=sha(source),
                      count=len(rows), state='preparing', original_job_id=parent['job_id'],
                      attempt_number=2, created_at=time.time())
        jobs.append(record)
        save(root/'orion/jobs.json', jobs)
        args = orion_command(python, source, run, profile['layout'], len(rows),
                             f"ra_bev_closeup_retry_{parent['job_id']}")
        with (run/'submit.private.log').open('a') as log:
            result = subprocess.run(args, cwd=REPO, stdout=log, stderr=log, timeout=1800)
        receipt = read(run/'launch.receipt.json')
        if (result.returncode or receipt.get('status') != 'submitted'
                or receipt.get('username') != 'jasperchen' or receipt.get('task_count') != len(rows)):
            record['state'] = 'submission_requires_review'
            save(root/'orion/jobs.json', jobs)
            raise ValueError('automatic_retry_submission_requires_reconciliation')
        record.update(job_id=receipt['job_id'], state='submitted', max_concurrency=receipt['max_concurrency'])
        save(root/'orion/jobs.json', jobs)
        save(run/'recovery-registration.json', dict(state='submitted',
             original_job_id=parent['job_id'], job_id=receipt['job_id'], attempt_number=2,
             total_attempt_limit=3, source_sha256=record['source_sha256']))


def local_tick(c, recovery, root=TASK):
    """Run only inside original controller.main's lock, after original daily work."""
    profile = control(root)
    if not enabled(profile):
        return
    with sqlite3.connect((root/'queue.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        plan = recovery_plan(root, read(root/'orion/jobs.json', []), published_identities(db))
    claims = list(c.BAGS.glob('daily/*/recovery/local/*/*/claim.json'))
    claims += list(c.BAGS.glob('versions/*/*/recovery/local/*/*/claim.json'))
    running = sum(recovery.alive(recovery.session_for(p.parent)) for p in claims)
    policy = read(Path(profile['code'])/'config/bev_closeup/recovery-policy.json')
    for group in plan['local']:
        rows, parent = group['rows'], group['parent']
        evidence = root/'local-fallback'/f"automatic-{parent['job_id']}"
        source = evidence/'source-rows.json'
        if not source.exists():
            save(source, dict(rows=rows))
            save(evidence/'fallback-registration.json', dict(recipe=RECIPE,
                 layout_sha256=LAYOUT_SHA, source_rows_sha256=sha(source)))
        elif any(row not in read(source)['rows'] for row in rows):
            raise ValueError('automatic_local_frozen_subset_changed')
        state = dict(updated_at=time.time(), cases=read(evidence/'state.json').get('cases', {}), remaining=[])
        for row in rows:
            family = '2026' + row['version']
            case = c.BAGS/'versions'/family/f"bev-closeup-{parent['job_id']}"/'recovery/local'/row['issue_id']
            for n in range(1, policy['local_max_attempts']+1):
                attempt = case/str(n)
                result = read(attempt/'result.json')
                started = read(attempt/'started.json')
                item = dict(state=result.get('state', 'registered'))
                if started.get('started_at'):
                    item['started_at'] = started['started_at']
                state['cases'][row['issue_id']] = item
                if result.get('state') in {'verified', 'rendered'}:
                    break
                if result.get('state') == 'failed':
                    continue
                session = recovery.session_for(attempt)
                if recovery.alive(session):
                    break
                if (attempt/'claim.json').exists():
                    save(attempt/'result.json', dict(state='failed', code='interrupted_claim_preserved', finished_at=time.time()))
                    continue
                if running >= policy['local_workers']:
                    break
                # A registered candidate waiting on resources has not consumed
                # a local attempt. The real claim is only written at admission.
                if not resource_ready(root):
                    break
                # Frozen intent precedes launch; original recovery counts this same namespace.
                save(attempt/'claim.json', dict(row=row, attempt=n, created_at=time.time(),
                     closeup_task_root=str(root), closeup_code=profile['code']))
                args = [str(c.PY), str(Path(profile['code'])/'scripts/bev_closeup/local_attempt.py'), str(attempt)]
                subprocess.run(['tmux', 'new-session', '-d', '-s', session, shlex.join(args)], check=True)
                running += 1
                break
            else:
                state['remaining'].append(dict(issue_id=row['issue_id'], trip_id=row['trip_id'],
                     anchor_ms=row['capture_timestamp_ms'], disposition='local_attempts_exhausted'))
        save(evidence/'state.json', state)


def resource_ready(root=TASK):
    # Reuse the original frozen memory threshold; importing does not start it.
    sys.path.insert(0, str(root/'code/ra_triage_dashboard/scripts/bev_closeup'))
    import coordinator
    disk = os.statvfs(root)
    return coordinator.resource_state()['status'] == 'ready' and disk.f_bavail*disk.f_frsize >= 10*1024**3


def publish_local_ready(root, db, pipeline, profile):
    if not enabled(profile):
        return
    bags = REPO/'bags/manual_sidecar_20261019'
    for claim_file in bags.glob('versions/*/bev-closeup-*/recovery/local/*/*/claim.json'):
        attempt = claim_file.parent
        result = read(attempt/'result.json')
        if result.get('state') != 'rendered':
            continue
        claim = read(claim_file)
        row = claim['row']
        if claim.get('closeup_task_root') != str(root):
            raise ValueError('local_claim_task_mismatch')
        current = db.execute('SELECT row_json FROM jobs WHERE issue_id=?', (row['issue_id'],)).fetchone()
        if not current or identity(json.loads(current[0])) != identity(row):
            raise ValueError('local_claim_current_identity_mismatch')
        if identity(row) in published_identities(db):
            save(attempt/'result.json', dict(result, state='verified', retained_existing=True))
            continue
        folder = attempt/'runs'/row['issue_id']/'outputs'/f"{row['issue_id']}_{row['capture_timestamp_ms']}"
        staged = attempt/'publish-input'
        staged.mkdir(exist_ok=True)
        try:
            for source, name in [(folder/'animation.mp4', 'video.mp4'), (folder/'report.json', 'report.json')]:
                if not (staged/name).exists():
                    os.link(source, staged/name)
            save(staged/'receipt.json', dict(issue_id=row['issue_id'], trip_id=row['trip_id'],
                 capture_timestamp_ms=row['capture_timestamp_ms'], task_id=None, producer='ares_animation_local'))
            checked = pipeline.verify_download(staged, row, attempt/'verification')
            checked.update(producer='ares_animation_local', visual_review='representative_canary_passed',
                           local_attempt=numeric_attempt(attempt), local_run=str(attempt/'runs'/row['issue_id']))
            checked.pop('orion_task_id', None)
            save(attempt/'verification/verification.json', checked)
            receipt = pipeline.publish(staged, attempt/'verification', checked)
            db.execute("UPDATE jobs SET state='verified',error=NULL,finished_at=?,batch=? WHERE issue_id=?",
                       (time.time(), str(attempt), row['issue_id']))
            db.commit()
            save(attempt/'result.json', dict(state='verified', sha256=receipt['sha256'], finished_at=time.time()))
        except Exception as exc:
            save(attempt/'result.json', dict(state='failed', code=type(exc).__name__, stage='publication_gate', finished_at=time.time()))


def numeric_attempt(attempt):
    number = int(attempt.name)
    if number not in (1, 2):
        raise ValueError('invalid_automatic_local_budget')
    return number
