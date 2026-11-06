"""Project durable label-publication receipts into the shared immutable audit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

PUBLICATION_SOURCES = {'rd_upload', 'te_correction'}


def _time(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def sync_publication_audit(db, record):
    """Idempotent local reconciliation; never reads or writes Trail."""
    if record['state'] not in {'running', 'complete', 'needs_recheck'}:
        return
    rows = [row for row in record['items'] if row['eligible']]
    if not rows:
        return
    mode = record.get('mode', 'rd')
    field = 'ra_review_result_new' if mode == 'te-correction' else 'ra_rd_review_result'
    operation = 'publication-' + record['id']
    items = [dict(issue_id=row['issue_id'], field=field,
                  before={'value':row['before'].get(field)}, after={'value':row['desired']}) for row in rows]
    existing = db.trail_operation(operation)
    if existing is not None:
        if (existing['actor'] != record['actor'] or existing['source'] != ('te_correction' if mode == 'te-correction' else 'rd_upload')
                or sorted(existing['items'], key=lambda r:r['issue_id']) != sorted(items, key=lambda r:r['issue_id'])):
            raise ValueError('Publication audit snapshot conflict')
    else:
        db.begin_trail_operation(operation_id=operation, actor=record['actor'],
            actor_source=record.get('actor_source', 'publication_receipt'),
            actor_verified=record.get('actor_verified', False),
            source='te_correction' if mode == 'te-correction' else 'rd_upload',
            created_at=_time(record.get('started_at', record['created_at'])),
            reason=record.get('baselines', ''), items=items)
    if record['state'] == 'running':
        return
    results = {row['issue_id']: row for row in record.get('results', [])}
    outcomes = {}
    for row in rows:
        state = results.get(row['issue_id'], {}).get('state', 'not_attempted')
        outcomes[row['issue_id']] = ('succeeded' if state == 'verified' else 'unknown' if state in {'intent','unverified'}
            else 'not_attempted' if record['state'] != 'running' else 'pending')
    status = ('succeeded' if all(v == 'succeeded' for v in outcomes.values()) else 'partial' if 'succeeded' in outcomes.values()
        else 'pending' if record['state'] == 'running' else 'unknown')
    if existing is not None and existing['outcomes'] == outcomes:
        return
    digest = hashlib.sha256(json.dumps([operation, status, outcomes], sort_keys=True).encode()).hexdigest()
    db.append_trail_event(operation, status, outcomes, event_id=digest,
        created_at=_time(record.get('finished_at', record.get('started_at', record['created_at']))))


def reconcile_publication_history(db, directory):
    """Existing receipts enter the same history without replaying any upload."""
    for path in sorted((Path(directory) / 'rd_publications').glob('*.json')):
        if not re.fullmatch(r'[0-9a-f]{32}\.json', path.name):
            continue
        record = json.loads(path.read_text())
        if record['state'] == 'running':
            from .rd_results import PublicationStore
            store = PublicationStore(directory)
            store.receipt(record['id'])  # Recover interrupted local intents; never sends Trail I/O.
            record = store.get(record['id'])
        sync_publication_audit(db, record)
