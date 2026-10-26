"""One read-only gallery for version processing and authoritative TE observations."""
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
import hashlib
import io
import json
import re
from urllib.parse import quote, urlencode

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


def composition(rows, *, historical=False, date=''):
    """Mutually exclusive final reason groups; pending/excluded are not 'other'."""
    scoped=[r for r in rows if not date or r['date']==date]
    completed=[r for r in scoped if historical or r['state'] in {'inferred','published'}]
    counts=Counter('sample' if r.get('is_sample') else 'low' if r.get('is_low') else 'other' for r in completed)
    total=len(completed)
    return dict(basis='frozen_targets' if historical else 'inferred_admitted',date=date,total=total,
                groups=[dict(key=k,count=counts[k],ratio=counts[k]/total if total else 0) for k in ('low','sample','other')],
                excluded=sum(r['state']=='excluded' for r in scoped),
                pending=sum(r['state'] not in {'inferred','published','excluded','historical'} for r in scoped))


def trail_filter_url(filters):
    """Encode native Trail descriptors without escaping its .$0 array marker."""
    params = {'__fmt': '1', 'view_id~d': '2410', 'page~d': '1', 'size~d': '20',
              'is_us_engineer~b': '0'}
    for i, (field, operator, value, kind) in enumerate(filters):
        params['query_attrs.$' + str(i)] = '|'.join((field, operator, quote(value, safe=''), kind))
    params['filter_operator'] = 'AND'
    # Trail uses decodeURI for the outer query and preserves encoded '$'.
    return 'https://voyager.intra.xiaojukeji.com/static/management/#/issue/pool?' + urlencode(params, safe='$')


def trail_case_filter(rows):
    """Native Trail filter URL for this exact recorded cohort (no live query)."""
    ids = sorted({r['issue_id'] for r in rows})
    if not ids:
        return None  # An empty IN filter must never accidentally open all cases.
    if any(not re.fullmatch(r'cn\d+', iid) for iid in ids):
        raise ValueError('Invalid Issue ID in metric scope')
    return trail_filter_url([('issue_id', 'in', ','.join(ids), 'a_s')])


def trail_reason_filter(family, mode):
    """Compact live reason query; the historical EOL exception is 1009-only."""
    if not isinstance(family, str) or not re.fullmatch(r'20\d{6}', family):
        raise ValueError('Invalid release family')
    datetime.strptime(family, '%Y%m%d')
    filters = [('version', 'like', '1.gen4-release-' + family, 'a_s'),
               ('trip_category', 'in', '0', 'a_d'), ('ra_type', 'in', '2,3', 'a_d'),
               ('trip_odd', 'in', 'ODD2', 'a_s')]
    if family == '20261009':
        filters.append(('ra_trigger', 'not_in', 'kEndOfLaneSequence', 'a_s'))
    if mode == 'published':
        filters.append(('ra_review_reason', 'not_empty', '', 's'))
    elif mode in {'targets', 'sampled_targets'}:
        reason = '目标集-抽样' if mode == 'sampled_targets' else '目标集-低置信,目标集-抽样'
        filters.append(('ra_review_reason', 'in', reason, 'a_s'))
    else:
        raise ValueError('Invalid reason metric')
    return trail_filter_url(filters)


def count_scope(rows, *, historical=False, family=None):
    """Whole-version metric definitions, independent of gallery/date filters."""
    states = Counter(r['state'] for r in rows)
    completed = [r for r in rows if historical or r['state'] in {'inferred', 'published'}]
    groups = Counter('sample' if r.get('is_sample') else 'low' if r.get('is_low') else 'other' for r in completed)
    excluded = Counter()
    allowed = {'CZ_TL', 'kEndOfLaneSequence', 'FN_EOL', 'AbnormalTrafficLight'}
    for row in rows:
        if row['state'] == 'excluded':
            trigger = row.get('trigger')
            # The platform packet retains top-level trigger, not raw start events.
            # Keep unmatched/start-only or business exclusions explicit.
            typed = row.get('error') == 'trigger_source_excluded' and isinstance(trigger, str) and trigger in allowed
            excluded[trigger if typed else 'other_exclusion'] += 1
    cohorts = {
        'all': rows,
        'published': [r for r in rows if r['state']=='published'],
        'targets': [r for r in rows if r.get('is_target')],
        'source_waiting': [r for r in rows if r['state']=='waiting_metadata'],
        'excluded': [r for r in rows if r['state']=='excluded'],
        'sampled_targets': [r for r in rows if r.get('is_target') and r.get('is_sample')],
    }
    reason_modes = {'published', 'targets', 'sampled_targets'}
    kinds, links = {}, {}
    for mode, cohort in cohorts.items():
        by_reason = bool(family) and not historical and mode in reason_modes
        kinds[mode] = 'reason_fields' if by_reason else 'case_ids'
        if not cohort:
            links[mode] = None
        else:
            links[mode] = trail_reason_filter(family, mode) if by_reason else trail_case_filter(cohort)
    return dict(basis='frozen_targets' if historical else 'version_all_dates', total=len(rows), states=dict(states),
                completed=len(completed), low_only=groups['low'], sampled=groups['sample'],
                targets=sum(bool(r.get('is_target')) for r in rows),
                exclusions=[dict(type=k, count=v) for k,v in sorted(excluded.items())],
                sampling_policy=None if historical else 'version_probability_v3',
                sampling_probability=None if historical else 0.1,
                trail_links=links, trail_link_types=kinds,
                trail_reason_exclusions=['kEndOfLaneSequence'] if family=='20261009' and not historical else [])


def workbench(db, root, dataset_id, *, page=1, page_size=24, mode='targets', q='', sort='added',
              date='', te_status='all', revision='',assignee='',review_status='all'):
    if mode not in {'targets', 'samples', 'low', 'waiting', 'all', 'published', 'excluded', 'source_waiting', 'sampled_targets'} or sort not in {'added', 'updated', 'occurred', 'issue'} or te_status not in {'all', 'filled', 'unfilled', 'unknown'}:
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
        if mode == 'published':return row['state']=='published'
        if mode == 'excluded':return row['state']=='excluded'
        if mode == 'source_waiting':return row['state']=='waiting_metadata'
        if mode == 'sampled_targets':return bool(row.get('is_target') and row.get('is_sample'))
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
    days=sorted(grouped)[-14:]
    if date in grouped and date not in days:days=sorted([date,*days[-13:]])
    daily = [dict(date=day, summary=summarize(grouped[day])) for day in days]
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
                  snapshot_revision=snapshot_revision,count_scope=count_scope(rows,historical=historical,family=family),composition=composition(rows,historical=historical,date=date), te=dict(source_field='ra_review_result_new',
                      source_status=te['source_status'], last_success_at=te.get('last_success_at'),observed_changes=te.get('observed_changes'), summary=summarize(targets),
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
