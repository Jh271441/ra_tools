"""Single-writer small-result reconciliation, including failed native tasks.

No Bag access, renderer, planner, lazy worker, or database rebuild is allowed here.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ra_triage_dashboard.app.planning_text_artifact import identity, object_key, load_artifact
from ra_triage_dashboard.app.planning_text_daily import import_artifact
from ra_triage_dashboard.scripts.planning_text.hook import save
from ra_triage_dashboard.scripts.planning_text.runner import selected_control

PREFIX = 'all_data/value_files/planning_text_v1/'


def bootstrap():
    """Use the same SDK/ROS environment as Ares, without depending on shell rc."""
    if os.environ.get('PLANNING_TEXT_SDK_ENV') == '1':
        return
    from ares_animation.adapters.voyager import load_voyager_environment
    _, env = load_voyager_environment()
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env.pop(key, None)
    env.update(PLANNING_TEXT_SDK_ENV='1', NO_PROXY='*', no_proxy='*',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env)


def list_files(job_id, root, members, imported_keys=(), cursor=0):
    """Exact Task/version addresses; never depend on CloudFile list filters."""
    target = root/'native-observations'/f'{job_id}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    request = target.with_suffix('.request.json')
    save(request, dict(job_id=job_id, members=members, imported_keys=list(imported_keys), cursor=cursor))
    script = '''import json,os,resource,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024**2,)*2)
resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
from orion.db_accessor.cloud_file_accessor import CloudFileAccessor
from orion.db_accessor.job_accessor import JobAccessor
from orion.db_accessor.task_accessor import TaskAccessor
from orion_protos.orion_task_pb2 import OrionTask
from orion.utils.storage_locator import StorageLocator
from voy_data_utils.regions import Regions,TrailRegionMgr
from ra_triage_dashboard.app.planning_text_artifact import identity,object_key
request=json.loads(Path(sys.argv[1]).read_text());jid=request['job_id']
tasks=[];last=0
with TrailRegionMgr(Regions.CN):
 for page in range(1,22):
  rows=TaskAccessor.query_one_page(dict(job_id=jid,kind=OrionTask.MAPPER,id__gt=last,extra_fields='task_args'),1,500,timeout=10,max_attempts=1)
  if any(r['job_id']!=jid or r['id']<=last for r in rows): raise ValueError('planning_task_listing_identity_mismatch')
  tasks.extend(rows)
  if len(tasks)>10000: raise ValueError('oversized_planning_task_listing')
  if len(rows)<500: break
  last=max(r['id'] for r in rows)
 else: raise ValueError('oversized_planning_task_listing')
 job=JobAccessor.get(jid,timeout=10,max_attempts=1)
pending=[]
for task in tasks:
 args=task['task_args']
 for key,member in request['members'].items():
  if (key not in request['imported_keys'] and args.get('--issue-id')==member['issue_id'] and args.get('--trip-id')==member['trip_id'] and str(args.get('--capture-timestamp-ms'))==str(member['anchor_ms'])):
   pending.append((task,member,key));break
cursor=request['cursor']%len(pending) if pending else 0
batch=(pending[cursor:]+pending[:cursor])[:100]
def read(item):
 task,member,key=item
 locator='gift3x:cn_nmg:'+object_key(member,jid,task['id'],task['version'])
 try:
  row=CloudFileAccessor.get_by_storage_location(locator,region=Regions.CN,timeout=5,max_attempts=1)
 except Exception as exc:
  # A worker may have uploaded before its CloudFile registration was interrupted.
  # Query the exact object too; a transport failure never proves source absence.
  try:
   exists=StorageLocator.from_string(locator).check_exist(max_attempts=1)
  except Exception as transport:
   return dict(capture_key=key,task_id=task['id'],task_version=task['version'],task_status=task['status'],missing_confirmed=False,error_type=type(transport).__name__)
  if not exists:
   return dict(capture_key=key,task_id=task['id'],task_version=task['version'],task_status=task['status'],missing_confirmed=True,error_type=type(exc).__name__)
  row=dict(storage_location=locator,job_id=jid,task_id=task['id'],task_version=task['version'],file_size=8*1024**2)
 if (row.get('storage_location')!=locator or row.get('job_id')!=jid or row.get('task_id')!=task['id'] or row.get('task_version')!=task['version']):raise ValueError('planning_native_file_identity_mismatch')
 return {**{k:row.get(k) for k in ('job_id','task_id','task_version','file_size','storage_location')},'capture_key':key}
with ThreadPoolExecutor(max_workers=4) as pool:
 observed=list(pool.map(read,batch))
value=dict(files=[r for r in observed if 'storage_location' in r],missing=[r for r in observed if 'storage_location' not in r],job_state=job['state'],task_count=len(tasks),pending_task_count=len(pending),next_cursor=(cursor+len(batch))%len(pending) if pending else 0)
raw=json.dumps(value).encode()
if len(raw)>2*1024**2: raise ValueError('oversized_planning_file_listing')
target=Path(sys.argv[2]);pending=target.with_suffix('.pending')
pending.write_bytes(raw);pending.replace(target)
'''
    with target.with_suffix('.private.log').open('ab') as log:
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3])+os.pathsep+os.environ.get('PYTHONPATH', ''))
        subprocess.run([sys.executable, '-c', script, str(request), str(target)], env=env,
                       stdout=log, stderr=log, timeout=180, check=True)
    if target.stat().st_size > 2*1024**2:
        raise ValueError('oversized_planning_file_listing')
    return json.loads(target.read_text())


def unpack(archive, destination):
    expected = {'frames.jsonl', 'result.json', 'receipt.json'}
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if (len(members) != 3 or {m.name for m in members} != expected
                or any(not m.isfile() or m.size > 2*1024**2 for m in members)
                or sum(m.size for m in members) > 5*1024**2):
            raise ValueError('invalid_planning_archive')
        destination.mkdir(parents=True, exist_ok=False)
        stream.extractall(destination)
    load_artifact(destination)


def download(locator, target):
    # SDK/transport diagnostics stay in a private file. Bound its whole process.
    script = '''import resource,sys
resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,)*2)
resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
from orion.utils.storage_locator import StorageLocator
StorageLocator.from_string(sys.argv[1]).download_file(sys.argv[2],max_attempts=1,timeout=100)
'''
    pending = target.with_suffix('.pending')
    with target.with_suffix('.private.log').open('ab') as log:
        subprocess.run([sys.executable, '-c', script, locator, str(pending)],
                       stdout=log, stderr=log, timeout=120, check=True)
    if not 0 < pending.stat().st_size <= 8*1024**2:
        raise ValueError('oversized_planning_download')
    pending.replace(target)


def tick(profile, state):
    root = Path(profile['data_dir'])/'planning_constraints'
    imports, failures = state.setdefault('imports', {}), state.setdefault('failures', {})
    imported_keys = {item['capture_key'] for item in imports.values()}
    for registration in sorted((root/'runs').glob('*.json'))[:10000]:
        record = json.loads(registration.read_text())
        run = Path(record['run'])
        members = {identity(m): m for m in record['members'] if m.get('extract')}
        if not members:
            continue
        if set(members) <= imported_keys:
            continue
        launch = run/'launch.receipt.json'
        if launch.exists():
            native = json.loads(launch.read_text())
            if native.get('status') != 'submitted':
                continue  # Submission unknown must never become a new job.
            jid = native['job_id']
            observations = state.setdefault('native_observations', {})
            prior = observations.get(str(jid), {})
            try:
                observed = list_files(jid, root, members, imported_keys, prior.get('next_cursor', 0))
            except Exception as exc:
                observations[str(jid)] = {**prior, 'error': type(exc).__name__, 'failed_at': time.time()}
                continue  # Observation failure is never evidence of task exit.
            files = observed['files']
            observations[str(jid)] = dict(last_success_at=time.time(), file_count=len(files),
                missing_count=len(observed['missing']), job_state=observed['job_state'],
                pending_task_count=observed['pending_task_count'], next_cursor=observed['next_cursor'])
            for file in files:
                locator = file.get('storage_location', '')
                key = file['capture_key']
                if key not in members or file.get('job_id') != jid:
                    raise ValueError('planning_native_file_identity_mismatch')
                member = members[key]
                if locator != 'gift3x:cn_nmg:'+object_key(member, jid, file['task_id'], file['task_version']):
                    raise ValueError('planning_native_file_identity_mismatch')
                transfer_key = f"{file['task_id']}_v{file['task_version']}:{key}"
                failure = failures.get(transfer_key, {})
                if failure.get('terminal') or time.time() < failure.get('next_at', 0):
                    continue
                destination = root/'artifacts'/key/f"{file['task_id']}_v{file['task_version']}"
                target = destination.with_suffix('.tgz')
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        if not target.exists():
                            if not 0 < file.get('file_size', 0) <= 8*1024**2:
                                raise ValueError('oversized_planning_download')
                            download(locator, target)
                        unpack(target, destination)
                    result, receipt, actual_sha = load_artifact(destination, member)
                    producer = receipt['producer']
                    if (producer.get('job_id') != jid
                            or producer.get('task_id') != file.get('task_id')
                            or producer.get('task_version') != file.get('task_version')
                            or producer.get('owner') != member['owner']
                            or producer.get('worker_source_sha256') != record['worker_source_sha256']):
                        raise ValueError('planning_native_receipt_identity_mismatch')
                    imports[actual_sha] = import_artifact(profile['data_dir'], destination, member, member['owner'])
                    imported_keys.add(key)
                    failures.pop(transfer_key, None)
                except Exception as exc:
                    attempts = failure.get('attempts', 0)+1
                    failures[transfer_key] = dict(code=type(exc).__name__, attempts=attempts,
                        terminal=isinstance(exc, ValueError) or attempts >= 3,
                        next_at=time.time()+min(1800,60*2**attempts))
                    # Preserve partial or conflicting evidence; do not reread Bags.
        else:
            for folder in (run/'work/prepared').glob('planning-text-*/artifact'):
                result, receipt, receipt_sha = load_artifact(folder)
                if result['capture_key'] not in members or receipt_sha in imports:
                    continue
                member = members[result['capture_key']]
                if receipt['producer'].get('owner') != member['owner']:
                    raise ValueError('planning_local_owner_mismatch')
                imports[receipt_sha] = import_artifact(profile['data_dir'], folder, member, member['owner'])
    state.update(checked_at=time.time(), pid=os.getpid(), imported=len(imports), failure_count=len(failures))
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    profile = selected_control()
    if not profile:
        return
    root = Path(profile['data_dir'])/'planning_constraints'
    root.mkdir(parents=True, exist_ok=True)
    with (root/'importer.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = root/'importer-state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        while True:
            try:
                tick(profile, state)
                state.pop('observation_error', None)
            except Exception as exc:
                state['observation_error'] = dict(code=type(exc).__name__, at=time.time())
            save(state_path, state)
            if args.once:
                return
            time.sleep(30)


if __name__ == '__main__':
    bootstrap()
    main()
