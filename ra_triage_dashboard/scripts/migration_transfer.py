#!/usr/bin/env python3
"""Resume allowlisted Manual media copies to an existing verified OFS mount.

Run on the source host. Destination is an unpublished migration staging tree.
No deletions, credentials, experimental models or unrelated source trees are used.
The completed receipt means rsync succeeded; SHA verification is a separate gate.
"""
import argparse
import concurrent.futures
import fcntl
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess


def run_transfer(spec, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    total = sum(r['logical_bytes'] for r in spec['roots'])
    if total > spec['budget_bytes']:
        raise ValueError('Media budget exceeded')
    dest_base = PurePosixPath(spec['destination'])
    required = '/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/services/manual/staging/'
    if not str(dest_base).startswith(required) or '..' in dest_base.parts:
        raise ValueError('Destination must be an unpublished Manual staging path')
    hop = spec['hop_script']
    for row in spec['roots']:
        rel = PurePosixPath(row['target'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Invalid target relative path')
        dest = str(dest_base / rel)
        receipt = report_dir / (row['id'] + '.json')
        if receipt.exists() and json.loads(receipt.read_text()).get('rsync_complete'):
            continue
        code = """from pathlib import Path
import os,json
mount=Path('/nfs/dataset-ofs-remote-assist-stuck')
assert any('orangefs:remote-assist-stuck-model' in l and str(mount) in l for l in Path('/proc/mounts').read_text().splitlines())
assert json.loads((mount/'user/jasperchen/services/manual/.manual-volume.json').read_text())['service']=='manual'
s=os.statvfs(mount);total=s.f_blocks*s.f_frsize;free=s.f_bavail*s.f_frsize
assert (total-free+%d)/total < 0.90,'OFS 90%% capacity gate'
assert free > %d + 30*1024**3,'Insufficient staging headroom'
Path(%r).mkdir(parents=True,exist_ok=True)
""" % (row['logical_bytes'], row['logical_bytes'], dest)
        subprocess.run([hop, spec['host'], 'python3 -c ' + shlex.quote(code)], check=True)
        started = datetime.now(timezone.utc).isoformat()
        args = ['rsync', '-rltpg', '--chown=:manual-media', '--chmod=D2750,F0640', '--safe-links', '--partial-dir=.rsync-partial',
                '--timeout=120', '--info=stats2', '-e', hop,
                row['path'].rstrip('/')+'/', spec['host']+':'+dest+'/']
        with (report_dir / (row['id']+'.log')).open('a') as log:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT)
        data = {'root': row, 'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                'rsync_complete': result.returncode == 0, 'returncode': result.returncode,
                'sha256_verified': False, 'published': False}
        receipt.write_text(json.dumps(data, indent=2))
        print(json.dumps({'id':row['id'], 'returncode':result.returncode}), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True)
    p.add_argument('--reports',type=Path,required=True)
    p.add_argument('--workers',type=int,choices=[1,2],default=1)
    a=p.parse_args();spec=json.loads(a.spec.read_text())
    if sum(r['logical_bytes'] for r in spec['roots'])>spec['budget_bytes']:
        raise ValueError('Total media budget exceeded')
    a.reports.mkdir(parents=True,exist_ok=True)
    with (a.reports/'.transfer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        groups=[[] for _ in range(a.workers)];sizes=[0]*a.workers
        for row in sorted(spec['roots'],key=lambda r:r['logical_bytes'],reverse=True):
            i=min(range(a.workers),key=lambda i:sizes[i]);groups[i].append(row);sizes[i]+=row['logical_bytes']
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures=[pool.submit(run_transfer,{**spec,'roots':group},a.reports) for group in groups]
            for future in futures:future.result()


if __name__=='__main__':main()
