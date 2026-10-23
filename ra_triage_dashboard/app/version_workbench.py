"""One read-only gallery for version processing and authoritative TE observations."""
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
import hashlib
import io
import json
import re

from .daily_review_source import project, SnapshotChanged


def occurrence(value):
    try:
        stamp = float(value)
        if stamp > 1e11:
            stamp /= 1000
        dt = datetime.fromtimestamp(stamp, timezone.utc)
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), stamp
    except (ValueError, TypeError, OSError, OverflowError):
        return '', 0


def te_snapshot(root, family):
    key = {'20261009': '1009', '20260821': '0821'}.get(family, family)
    try:
        return project(root, dataset=key)
    except (ValueError, OSError, TypeError, KeyError):
        return dict(source_status='error', last_success_at=None, snapshot_revision='', summary=None), []


def historical_dataset(root):
    te, rows = te_snapshot(root, '20260821')
    reasons = Counter(r['reason'] for r in rows)
    return dict(id='historical-0821', release_family='20260821', name='0821', historical=True,
                targets=len(rows) if te.get('summary') is not None else None, total=len(rows),
                sampled_targets=reasons['sample'], low_only=reasons['low'], assigned={}, states={},
                revision=te.get('snapshot_revision', ''))


def summarize(rows):
    counts = Counter(r['te_status'] for r in rows)
    total = len(rows)
    return dict(total=total, filled=counts['filled'], unfilled=counts['unfilled'], unknown=counts['unknown'],
                rate=counts['filled']/total if total else None)


def workbench(db, root, dataset_id, *, page=1, page_size=24, mode='targets', q='', sort='added',
              date='', te_status='all', revision='',assignee='',review_status='all'):
    if mode not in {'targets', 'samples', 'low', 'waiting', 'all'} or sort not in {'added', 'updated', 'occurred', 'issue'} or te_status not in {'all', 'filled', 'unfilled', 'unknown'}:
        raise ValueError('Invalid gallery filter')
    if review_status not in {'all','pending','completed'}:raise ValueError('Invalid joint-review status')
    if not 1 <= page <= 10000 or not 1 <= page_size <= 100:
        raise ValueError('Invalid gallery page')
    if date:
        datetime.strptime(date, '%Y-%m-%d')
    historical = dataset_id == 'historical-0821'
    if historical:
        if assignee or review_status!='all':raise ValueError('Historical review state is not part of the version registry')
        dataset = historical_dataset(root)
        family = '20260821'
    else:
        match = re.fullmatch(r'release-(20\d{6})-odd2', dataset_id)
        if not match:
            raise ValueError('Invalid version dataset')
        family = match[1]
        dataset = next((r for r in db.list_version_datasets() if r['id']==dataset_id), None)
        if dataset is None:
            raise ValueError('Unknown version dataset')
    te, observations = te_snapshot(root, family)
    by_id = {r['issue_id']: r for r in observations}
    if historical:
        rows = [dict(issue_id=r['issue_id'], software_version=r['version'], is_target=True,
                     is_sample=r['reason']=='sample', is_low=r['reason']=='low', state='historical',
                     binding={}, prediction=None, first_seen=None, updated_at=None) for r in observations]
    else:
        rows = db.version_dataset_gallery_rows(dataset_id)
    for row in rows:
        obs = by_id.get(row['issue_id'], {})
        row['date'], row['_occurred'] = occurrence(row.get('issue_time') or row.get('ra_start_timestamp'))
        if not row['date']:
            row['date'] = obs.get('date') or ''
        # New registry targets absent from an older TE snapshot remain unknown.
        row['te_status'] = obs.get('te_status', 'unknown') if row.get('is_target') else 'not_target'
        row['te_value'] = obs.get('te_value') if row['te_status']=='filled' else None
    date_options = sorted({r['date'] for r in rows if r['date']}, reverse=True)
    def in_scope(row, with_date=True):
        if assignee and (row.get('binding') or {}).get('assignee','').lower()!=assignee.lower():return False
        if review_status=='completed' and not row.get('review_submitted'):return False
        if review_status=='pending' and row.get('review_submitted'):return False
        if q and q.lower() not in row['issue_id'].lower():
            return False
        if with_date and date and row['date'] != date:
            return False
        if mode == 'targets':return bool(row.get('is_target'))
        if mode == 'low':return bool(row.get('is_target') and not row.get('is_sample'))
        if mode == 'samples':return bool(row.get('is_sample') and row['state']!='excluded')
        if mode == 'waiting':return row['state'] in {'waiting_metadata', 'retry_wait'}
        return True
    scoped = [r for r in rows if in_scope(r)]
    targets = [r for r in scoped if r.get('is_target')]
    grouped = {}
    for row in rows:
        if row.get('is_target') and row['date'] and in_scope(row, False):
            grouped.setdefault(row['date'], []).append(row)
    daily = [dict(date=day, summary=summarize(grouped[day])) for day in sorted(grouped)[-14:]]
    selected = [r for r in scoped if te_status=='all' or r['te_status']==te_status]
    if sort == 'issue':selected.sort(key=lambda r:int(r['issue_id'][2:]))
    else:
        field = {'added':'first_seen', 'updated':'updated_at', 'occurred':'_occurred'}[sort]
        selected.sort(key=lambda r:(r.get(field) or (0 if field=='_occurred' else ''), int(r['issue_id'][2:])), reverse=True)
    for row in rows:row.pop('_occurred', None)
    identity = json.dumps([dataset_id, dataset.get('revision'), te.get('snapshot_revision'), mode, q, date, te_status, sort,assignee,review_status], separators=(',', ':'))
    snapshot_revision = hashlib.sha256(identity.encode()).hexdigest()
    if revision and revision != snapshot_revision:
        raise SnapshotChanged('Gallery changed; refresh before exporting.')
    distribution = Counter(json.dumps(r['te_value'], ensure_ascii=False) for r in targets if r['te_status']=='filled')
    result = dict(dataset_id=dataset_id, dataset=dataset, page=page, page_size=page_size, total=len(selected),
                  items=selected[(page-1)*page_size:page*page_size], date_options=date_options,assignees=sorted({(r.get('binding') or {}).get('assignee') for r in rows if (r.get('binding') or {}).get('assignee')}),
                  snapshot_revision=snapshot_revision, te=dict(source_field='ra_review_result_new',
                      source_status=te['source_status'], last_success_at=te.get('last_success_at'), summary=summarize(targets),
                      distribution=[dict(value=json.loads(k),count=v) for k,v in distribution.items()], daily=daily))
    return result, selected


def gallery_csv(rows):
    out = io.StringIO()
    fields = ['issue_id','software_version','date','is_sample','is_low','state','model_label','model_confidence','assignee','review_submitted','te_status','te_value','first_seen','updated_at']
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore');writer.writeheader()
    for row in rows:
        flat = dict(row, **(row.get('prediction') or {}), assignee=(row.get('binding') or {}).get('assignee',''))
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in flat.items()})
    return '\ufeff'+out.getvalue()
