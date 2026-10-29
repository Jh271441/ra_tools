"""Recover interrupted claims only with the worker lock and no live owned process.

The default is a read-only plan. --apply validates completed videos before
requeueing incomplete claims; it never signals processes or resets failed jobs.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from contract import LAYOUT, publish, save, verify_case
from coordinator import connect, event


def process_identity(pid, proc_root=Path('/proc'), strict=False):
    try:
        folder = proc_root / str(pid)
        fields = (folder / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return dict(pid=int(pid), start_ticks=int(fields[19]),
                    argv=(folder / 'cmdline').read_bytes().decode().strip('\0').split('\0'))
    except PermissionError:
        if strict:
            raise RuntimeError('recorded_process_identity_unreadable:' + str(pid))
        return None
    except (OSError, ValueError, IndexError):
        return None


def live_owned(root, records, proc_root=Path('/proc')):
    scripts = {str(root / 'code/ra_triage_dashboard/scripts/bev_closeup' / name)
               for name in ('coordinator.py', 'renderer.py')}
    recorded = {(r.get('pid'), r.get('start_ticks')) for r in records}
    for pid, _ in recorded:
        process_identity(pid, proc_root, strict=True)
    found = []
    for path in proc_root.glob('[0-9]*'):
        row = process_identity(path.name, proc_root)
        if row and row['pid'] != os.getpid() and (
                scripts.intersection(row['argv']) or (row['pid'], row['start_ticks']) in recorded):
            found.append(row)
    return found


def recover(root, publish_root, apply=False):
    root = Path(root).resolve()
    with (root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect(root)
        jobs = db.execute("SELECT * FROM jobs WHERE state='running'").fetchall()
        records = []
        for batch in {r['batch'] for r in jobs if r['batch']}:
            record = json.loads((Path(batch) / 'process.json').read_text())
            records.extend([record, *record.get('children', [])])
        active = live_owned(root, records)
        if active:
            raise RuntimeError('owned_process_still_live:' + ','.join(str(r['pid']) for r in active))
        result = dict(checked_at=time.time(), apply=apply, claims=[])
        for job in jobs:
            row = json.loads(job['row_json'])
            batch = Path(job['batch']).resolve()
            batch.relative_to(root / 'batches')
            folder = batch / 'capture' / LAYOUT / f'{row["issue_id"]}_{row["capture_timestamp_ms"]}'
            item = dict(issue_id=row['issue_id'], batch=str(batch), previous_attempts=job['attempts'])
            if not apply:
                item.update(action='verify_existing_then_retry_if_incomplete', meta_exists=(folder / 'meta.json').is_file())
            else:
                try:
                    evidence = batch / 'verification' / row['issue_id']
                    path, verified = verify_case(folder, row, evidence)
                    publish(path, folder / 'meta.json', evidence, verified, publish_root)
                    db.execute("UPDATE jobs SET state='verified',error=NULL,finished_at=? WHERE job_key=?", (time.time(), job['job_key']))
                    item.update(action='verified_existing', sha256=verified['sha256'])
                except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                    state = 'failed' if job['attempts'] >= 3 else 'retry_wait'
                    error = type(exc).__name__ + ':' + str(exc)[:400]
                    db.execute("UPDATE jobs SET state=?,error=?,next_at=?,finished_at=? WHERE job_key=?", (state, error, time.time() + 300, time.time(), job['job_key']))
                    item.update(action=state, error=error)
                db.commit()
                event(db, 'interrupted_claim_recovered', **item)
            result['claims'].append(item)
        if apply:
            save(root / 'recoveries' / f'{time.time_ns()}.json', result)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--publish-root', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(recover(args.root, args.publish_root, args.apply), ensure_ascii=False))
