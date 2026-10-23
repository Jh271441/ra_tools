"""Bounded, read-only projections of atomic TE snapshots. Never calls Trail."""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timezone
import csv
import io
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

MAX_BYTES = 8 * 1024 * 1024

class SnapshotChanged(ValueError):
    pass

def _read(root, relative):
    path = root / relative
    if not path.exists():return None
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():raise ValueError('snapshot_path')
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('snapshot_size')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('snapshot_format')
    return value

def _valid_row(row,dataset,day):
    stamp={'1009':'20261009','0821':'20260821'}.get(dataset,dataset)
    if not isinstance(row,dict) or not re.fullmatch(r'cn\d+',str(row.get('issue_id',''))):return False
    if not re.match(r'^1\.gen4-release-'+stamp+r'(?:[.\-]|$)',str(row.get('version',''))):return False
    if row.get('dataset')!=dataset or row.get('reason') not in {'low','sample'}:return False
    if dataset!='0821' and day and row.get('date')!=day:return False
    if dataset!='0821' and not day:
        try:date.fromisoformat(row.get('date',''))
        except (ValueError,TypeError):return False
    status=row.get('te_status');v=row.get('te_value')
    if status not in {'filled','unfilled','unknown'}:return False
    if status=='filled' and not (type(v) is int or isinstance(v,str) and 0<len(v)<=256):return False
    if status in {'unfilled','unknown'} and v not in (None,''):return False
    return True

def project(root:Path,dataset='1009',day='',reason='all',te_status='all',page=1,size=24,revision=''):
    if (dataset not in {'1009','0821'} and not re.fullmatch(r'20\d{6}',dataset)) or reason not in {'all','low','sample'} or te_status not in {'all','filled','unfilled','unknown'}:raise ValueError('invalid_scope')
    if not 1<=page<=10000 or not 1<=size<=100:raise ValueError('invalid_page')
    allowed=Path(root).resolve()
    root=allowed/'reports/te_review_monitor'
    if not root.resolve().is_relative_to(allowed):raise ValueError('snapshot_root')
    options=[]
    folder=root/'snapshots'
    if folder.exists():
        for p in folder.glob(dataset+'-????-??-??.json'):
            d=p.stem[len(dataset)+1:]
            try:date.fromisoformat(d)
            except ValueError:continue
            options.append(d)
            if len(options)>4000:raise ValueError('too_many_dates')
    options.sort(reverse=True)
    version_membership=_read(root,'version-membership-'+dataset+'.json') if dataset!='0821' else None
    day=(day or ('' if version_membership else options[0] if options else '')) if dataset!='0821' else ''
    if day:date.fromisoformat(day)
    key=dataset+('-'+day if day else '')
    snap=_read(root,'snapshots/'+key+'.json') if day or dataset=='0821' or version_membership else None
    status=_read(root,'status/'+key+'.json') or {}
    if snap:
        if snap.get('schema_version')!=1 or snap.get('source_field')!='ra_review_result_new' or snap.get('dataset')!=dataset or (snap.get('date') or '')!=day:raise ValueError('snapshot_scope')
        rows=snap.get('rows');rev=snap.get('snapshot_revision','')
        if not isinstance(rows,list) or len(rows)>20000 or not re.fullmatch('[a-f0-9]{64}',rev):raise ValueError('snapshot_format')
        if any(not _valid_row(r,dataset,day) for r in rows) or len({r['issue_id'] for r in rows})!=len(rows):raise ValueError('invalid_snapshot_member')
        if revision and rev!=revision:raise SnapshotChanged('snapshot_changed')
        rows=[{k:r.get(k) for k in ('issue_id','dataset','date','version','reason','te_status','te_value')} for r in rows if reason=='all' or r['reason']==reason]
        at=snap.get('last_success_at')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(at)).total_seconds()
        stale=age> (900 if not day or (datetime.now(ZoneInfo("Asia/Shanghai")).date()-date.fromisoformat(day)).days<=15 else 4200)
        source_status='error' if status.get('status')=='error' else 'stale' if stale else 'ready'
    else:
        rows=[];rev='';at=None;source_status='error' if status.get('status')=='error' else 'unavailable'
    counts=Counter(r['te_status'] for r in rows);total=len(rows)
    dist=Counter(json.dumps(r['te_value'],ensure_ascii=False) for r in rows if r['te_status']=='filled')
    summary=dict(total=total,filled=counts['filled'],unfilled=counts['unfilled'],unknown=counts['unknown'],rate=counts['filled']/total if total else None,coverage=(counts['filled']+counts['unfilled'])/total if total else None,reasons=dict(Counter(r['reason'] for r in rows))) if snap else None
    selected=[r for r in rows if te_status=='all' or r['te_status']==te_status]
    result=dict(version_membership=bool(version_membership),scope=dict(dataset=dataset,date=day or None,reason=reason),summary=summary,date_options=options,source_status=source_status,last_success_at=at,snapshot_revision=rev,
                result_distribution=[dict(value=json.loads(k),count=v) for k,v in sorted(dist.items())],
                total=len(selected),page=page,size=size,items=selected[(page-1)*size:page*size],source_field='ra_review_result_new')
    return result,selected

def export_csv(rows):
    out=io.StringIO();fields=['issue_id','dataset','date','version','reason','te_status','te_value']
    writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader()
    for row in rows:
        safe={k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return '\ufeff'+out.getvalue()


def daily_overview(root, current, reason='all'):
    """Latest 14 data dates, independently validated; never sum daily denominators."""
    if current['scope']['dataset'] == '0821':
        return []
    result = []
    for day in reversed(current['date_options'][:14]):
        try:
            data = current if day == current['scope']['date'] else project(root, current['scope']['dataset'], day, reason, size=1)[0]
            result.append({k: data[k] for k in ('summary', 'source_status', 'last_success_at')} | {'date': day})
        except (ValueError, OSError, TypeError, KeyError):
            result.append({'date': day, 'summary': None, 'source_status': 'error', 'last_success_at': None})
    return result
