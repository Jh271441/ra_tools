"""Field-scoped model publication audit and conflict-checked inverse patches.

The original exclusion audit is intentionally unchanged. This adapter owns only
ra_stuck_auto_result, retaining the actual model output in its separate info.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy

from .db_parts.trail_history import encoded
from .trail_audit import info_object

FIELD = 'ra_stuck_auto_result'
INFO = 'ra_stuck_auto_result_info'
SOURCES = {'model_label_normalization', 'model_publication', 'model_label_restore'}
VALUES = {'正确触发', '成功', '误触发', '无需协助'}


def model_context(row):
    info = info_object(row.get(INFO))
    return hashlib.sha256(encoded({k: info.get(k) for k in
        ('daily_auto_triage', 'model_result')}).encode()).hexdigest()


def snapshot(row):
    value = row.get(FIELD)
    if value is not None and not isinstance(value, str):
        raise ValueError('Invalid model field scalar')
    return {'present': FIELD in row, 'value': value,
            'model_context_sha256': model_context(row)}


def matches(row, expected):
    return encoded(snapshot(row)) == encoded(expected)


def operation_items(rows, changes):
    before = {r['issue_id']: r for r in rows}
    if not changes or len(changes) > 200 or len({c['issue_id'] for c in changes}) != len(changes):
        raise ValueError('Invalid model audit cohort')
    items = []
    for change in changes:
        iid = change['issue_id']
        if set(change) != {'issue_id', FIELD} or iid not in before:
            raise ValueError('Only the model scalar belongs to this audit')
        value = change[FIELD]
        if value is not None and value not in VALUES:
            raise ValueError('Invalid model publication enum')
        old = snapshot(before[iid])
        items.append({'issue_id': iid, 'field': FIELD, 'before': old,
            'after': {**old, 'present': True, 'value': value}})
    return items


def begin(db, *, operation_id, rows, changes, source, actor, actor_source,
          actor_verified=False, reason='', parent_id=None, after_rows=None):
    if source not in SOURCES:
        raise ValueError('Invalid model audit source')
    existing = db.trail_operation(operation_id)
    if existing and any(db.trail_operation(c['id'])['status'] in {'succeeded', 'partial'}
                        for c in existing['children']):
        raise ValueError('Restored publication is terminal; do not replay')
    items = operation_items(rows, changes)
    if after_rows is not None:
        after = {r['issue_id']: r for r in after_rows}
        for item in items:
            item['after'] = snapshot(after[item['issue_id']])
    db.begin_trail_operation(operation_id=operation_id, source=source,
        actor=actor, actor_source=actor_source, actor_verified=actor_verified,
        reason=reason, parent_id=parent_id, items=items)
    return items


def reconcile(db, operation_id, rows, *, actor=None, actor_source=None):
    operation = db.trail_operation(operation_id)
    if operation is None or operation['source'] not in SOURCES:
        raise ValueError('Missing model publication intent')
    current = {r['issue_id']: r for r in rows}
    observed = {i['issue_id']: ('succeeded' if i['issue_id'] in current and
        matches(current[i['issue_id']], i['after']) else 'conflict' if
        i['issue_id'] in current else 'unknown') for i in operation['items']}
    # Historical verified success remains a historical fact after later edits.
    changed = {iid: value for iid, value in observed.items()
        if operation['outcomes'].get(iid) != 'succeeded'}
    if changed:
        state = 'succeeded' if all(v == 'succeeded' for v in changed.values()) else 'partial' if 'succeeded' in changed.values() else 'unknown' if 'unknown' in changed.values() else 'conflict'
        db.append_trail_event(operation_id, state, changed, actor=actor, actor_source=actor_source)
    return observed


def restore(operation, rows, *, null_qualified=False):
    if operation['source'] not in SOURCES or any(i['field'] != FIELD for i in operation['items']):
        raise ValueError('Not a model scalar operation')
    current = {r['issue_id']: r for r in rows}
    changes, conflicts = [], []
    for item in operation['items']:
        iid, old = item['issue_id'], item['before']
        if iid not in current or not matches(current[iid], item['after']):
            conflicts.append(iid)
            continue
        if not old.get('present') or (old.get('value') is None and not null_qualified):
            conflicts.append(iid)
            continue
        changes.append({'issue_id': iid, FIELD: deepcopy(old['value'])})
    return changes, conflicts
