"""Failure-isolated pre-reduction hook, included in a versioned worker overlay."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

from ra_triage_dashboard.app.planning_text_artifact import digest, identity, object_key, write_artifact, load_artifact


def event(state, **fields):
    # Only operational facts; never source text, payloads, credentials or SDK errors.
    print(json.dumps(dict(planning_text_event=state, **fields), sort_keys=True), flush=True)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    with pending.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def context(trip_id, manifest):
    """Exact task args, never guessed from a directory name or neighboring frame."""
    override = os.environ.get('PLANNING_TEXT_LOCAL_CONTEXT')
    if override:
        value = json.loads(Path(override).read_text())
        member, producer = value['member'], value['producer']
    else:
        from orion.model.constants import TaskEnvirons
        from orion.db_accessor.task_accessor import TaskAccessor
        from voy_data_utils.regions import Regions, TrailRegionMgr
        task_id, job = int(os.environ[TaskEnvirons.TASK_ID]), int(os.environ[TaskEnvirons.JOB_ID])
        version = int(os.environ[TaskEnvirons.VERSION])
        with TrailRegionMgr(Regions.CN):
            # BaseAccessor.get ignores extra_fields passed as a keyword argument.
            tasks = list(TaskAccessor.query_one_page(
                dict(id=task_id, extra_fields='task_args'), 1, 2, timeout=10, max_attempts=1))
        if len(tasks) != 1:
            raise ValueError('planning_native_identity_mismatch')
        task = tasks[0]
        if task['id'] != task_id or task['job_id'] != job or task['version'] != version:
            raise ValueError('planning_native_identity_mismatch')
        args = task['task_args']
        candidates = [m for m in manifest['members'] if m['issue_id'] == args.get('--issue-id')
            and m['trip_id'] == args.get('--trip-id')
            and str(m['anchor_ms']) == str(args.get('--capture-timestamp-ms'))]
        if len(candidates) != 1:
            raise ValueError('planning_member_identity_mismatch')
        member = candidates[0]
        producer = dict(kind='orion', job_id=job, task_id=task_id, task_version=version)
    if member['trip_id'] != trip_id:
        raise ValueError('planning_trip_identity_mismatch')
    identity(member)
    producer.update(owner=member['owner'], worker_source_sha256=manifest['worker_source_sha256'],
                    base_tool_sha256=manifest['base_tool_sha256'])
    return member, producer


def resources_ready():
    """Same <85% and >=6GiB admission, within this worker's cgroup."""
    cgroup = Path('/sys/fs/cgroup')
    maximum, current = cgroup/'memory.max', cgroup/'memory.current'
    if not maximum.is_file():
        maximum, current = cgroup/'memory/memory.limit_in_bytes', cgroup/'memory/memory.usage_in_bytes'
    limit = maximum.read_text().strip()
    if limit == 'max' or int(limit) > 1 << 60:
        mem = {line.split(':')[0]: int(line.split()[1])*1024
               for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:'))}
        total, available = mem['MemTotal'], mem['MemAvailable']
    else:
        total = int(limit)
        available = total-int(current.read_text())
    return available >= 6*1024**3 and (total-available)/total < .85


def run_windows(inputs, member, root):
    observations, errors = [], []
    def window(start, end, depth=0):
        checkpoint = root/'checkpoints'/f'{start}-{end}.json'
        request = dict(inputs=[str(p) for p in inputs], start_ms=start, end_ms=end, output=str(checkpoint))
        request_file = checkpoint.with_suffix('.request.json')
        save(request_file, request)
        if checkpoint.exists():
            rows = json.loads(checkpoint.read_text())
        else:
            if not resources_ready():
                errors.append(dict(code='resource_wait', start_ms=start, end_ms=end))
                return
            with checkpoint.with_suffix('.private.log').open('ab') as log:
                process = subprocess.Popen([sys.executable, '-m', 'ra_triage_dashboard.scripts.planning_text.worker', str(request_file)],
                    stdout=log, stderr=log, start_new_session=True)
                timed_out = False
                try:
                    process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            if process.returncode != 0 or timed_out:
                # Split the read window, never change any source bytes or the limits.
                failure = json.loads(checkpoint.with_suffix('.error.json').read_text()) if checkpoint.with_suffix('.error.json').exists() else {}
                splittable = timed_out or process.returncode in {-signal.SIGXFSZ, -signal.SIGKILL} or failure.get('error_type') == 'MemoryError'
                if splittable and end-start > 262 and depth < 8:
                    middle = (start+end)//2
                    window(start, middle, depth+1)
                    window(middle, end, depth+1)
                else:
                    errors.append(dict(code='window_timeout' if timed_out else 'window_worker_failed',
                                       start_ms=start, end_ms=end, returncode=process.returncode))
                return
            rows = json.loads(checkpoint.read_text())
        observations.extend(rows)
    first, last = member['anchor_ms']-20150, member['anchor_ms']+20000
    for start in range(first, last, 8400):
        window(start, min(start+8400, last))
    return observations, errors


def _upload_artifact(folder, producer):
    from offboard_base.orion_external import OrionTaskEntity
    from orion.utils.storage_locator import StorageUploader
    from voy_data_utils.regions import Regions, TrailRegionMgr
    from voy_data_utils.idc_regions import IdcRegions
    from voy_data_utils.storage_locator import StorageKinds
    result, receipt, receipt_sha = load_artifact(folder)
    archive = folder.parent/'planning-text.tgz'
    with tarfile.open(archive, 'w:gz') as stream:
        for name in ('frames.jsonl', 'result.json', 'receipt.json'):
            stream.add(folder/name, arcname=name)
    task = OrionTaskEntity(job=producer['job_id'], id=producer['task_id'], ver=producer['task_version'])
    key = object_key(result, producer['job_id'], producer['task_id'], producer['task_version'])
    with TrailRegionMgr(Regions.CN):
        locator = StorageUploader(kind=StorageKinds.GIFT3X, key=key, local_file=str(archive),
            src_task=task, retention_days=60).upload(IdcRegions.CN_NMG, max_attempts=3, skip_if_exist=True)
    save(folder.parent/'upload-receipt.json', dict(status='published', locator=str(locator),
         bytes=archive.stat().st_size, sha256=digest(archive), receipt_sha256=receipt_sha))


def upload_artifact(folder, producer):
    intent = folder.parent/'upload-intent.json'
    if intent.exists():
        raise ValueError('planning_upload_unknown_requires_reconciliation')
    save(intent, dict(capture_key=load_artifact(folder)[0]['capture_key'], at=time.time()))
    with (folder.parent/'upload.private.log').open('ab') as log:
        subprocess.run([sys.executable, '-m', 'ra_triage_dashboard.scripts.planning_text.hook',
                        '--upload', str(folder)], stdout=log, stderr=log, timeout=120, check=True)


def export(inputs, member, producer, root, lock):
    """Only an owner may compute. Reuse a complete local receipt on replay."""
    root.mkdir(parents=True, exist_ok=True)
    with Path(lock).open('a+') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        folder = root/'artifact'
        if folder.exists():
            load_artifact(folder, member)
        else:
            observations, errors = run_windows(inputs, member, root)
            source_manifest = [dict(bytes=p.stat().st_size, sha256=digest(p)) for p in inputs]
            producer = {**producer, 'source_manifest_sha256': hashlib.sha256(
                json.dumps(source_manifest, sort_keys=True).encode()).hexdigest()}
            save(root/'source-manifest.json', source_manifest)
            write_artifact(folder, member, observations, producer, errors=errors)
        if producer['kind'] == 'orion' and not (root/'upload-receipt.json').exists():
            upload_artifact(folder, producer)
        save(root/'state.json', dict(state='persisted_before_reduction', capture_key=identity(member)))
    return folder


def before_reduce(inputs, trip_id, output, *, already_reduced=False):
    """No sidecar exception may turn a valid video into a failed recording."""
    root = Path(output).parent/('planning-text-'+Path(output).name)
    try:
        if already_reduced:
            event('skip_reduced_input')
            return
        event('original_inputs_acquired')
        manifest_path = Path(os.environ.get('PLANNING_TEXT_MANIFEST', str(Path(__file__).resolve().parents[3]/'planning-worker-manifest.json')))
        manifest = json.loads(manifest_path.read_text())
        member, producer = context(trip_id, manifest)
        if member.get('extract') is not True:
            save(root/'state.json', dict(state='reuse_existing_owner', capture_key=identity(member)))
            event('reuse_existing_owner', capture_key=identity(member))
            return
        lock = os.environ.get('PLANNING_TEXT_SHARED_LOCK', str(root.parent/'planning-text.worker.lock'))
        folder = export([Path(p) for p in inputs], member, producer, root, lock)
        result, _, receipt_sha = load_artifact(folder, member)
        event('persisted_before_reduction', capture_key=identity(member),
              frames=result['frame_count'], source_status=result['extraction_status'], receipt_sha256=receipt_sha)
    except Exception as exc:
        save(root/'state.json', dict(state='text_requires_review', error_type=type(exc).__name__))
        event('text_requires_review', error_type=type(exc).__name__)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--upload':
        raise SystemExit('Expected --upload ARTIFACT')
    folder = Path(sys.argv[2])
    _, receipt, _ = load_artifact(folder)
    _upload_artifact(folder, receipt['producer'])
