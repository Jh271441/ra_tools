"""Read-only cached-evidence preflight. Never contacts Orion or reads source Bags."""
import json
import sqlite3
from pathlib import Path

from offline_daily import TASK, read, sha, identity, recovery_plan, published_identities


def plan(root=TASK):
    with sqlite3.connect((root/'queue.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        published = published_identities(db)
        counts = dict(db.execute('SELECT state, count(*) FROM jobs GROUP BY state'))
    jobs = read(root/'orion/jobs.json', [])
    inferred_terminal = []
    for job in jobs:
        if job.get('state') in {'terminal', 'audited'}:
            continue
        if not job.get('job_id'):
            raise ValueError('unresolved_submission_requires_review')
        run = Path(job['run'])
        status = read(run/'status.json')
        counts_native = status.get('counts', {})
        if (status.get('job_id') != job['job_id'] or status.get('total') != job['count']
                or sum(counts_native.get(k, 0) for k in ('completed','failed','cancelled')) != job['count']):
            continue
        source = Path(job['source_rows'])
        if sha(source) != job['source_sha256']:
            raise ValueError('source_changed')
        failed = {str(t.get('signature', '')).rsplit('-',2)[0] for t in read(run/'native-failed-tasks.json', [])}
        failures = read(run/'validation-failures.json')
        if all(identity(row) in published or row['issue_id'] in failed
               or (row['issue_id'] in failures and
                   (not failures[row['issue_id']].get('retryable') or failures[row['issue_id']].get('attempts',0) >= 3))
               for row in read(source, [])):
            # This is a preflight inference only, never written to jobs.json.
            job['state'] = 'terminal'
            inferred_terminal.append(job['job_id'])
    result = recovery_plan(root, jobs, published)
    return dict(states=counts, published=len(published), blocked_sources=result['blocked'],
                cached_terminal_inferences=inferred_terminal,
                retry_candidates=sum(len(g['rows']) for g in result['retry']),
                local_candidates=sum(len(g['rows']) for g in result['local']),
                task_root=str(root), read_only=True)


if __name__ == '__main__':
    print(json.dumps(plan(), indent=2))
