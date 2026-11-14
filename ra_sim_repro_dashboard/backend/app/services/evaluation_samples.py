"""Durable, verified sample snapshots. Page reads never acquire upstream data.

An offline import replaces one complete scope atomically and retains immutable
history. Subsets use warehouse create_date and literal columns, never Trail time
or a reconstructed merge label. Physical inputs are stored alongside the receipt
but remain subject to the simulation reuse audit in evaluation_pipeline.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from sqlalchemy import select
from app.models import ReleaseWorkflowState
from app.services import auto_triage_warehouse as warehouse, metric_profiles as profiles
from app.services import evaluation_labels
from app.services.release_cycle import digest

SNAPSHOT = 'evsample:'
INDEX = 'evsamplescope:'
COUNTS = tuple(prefix + '_' + name for prefix in ('auto', 'baseline')
               for name in ('precision_numerator', 'precision_denominator', 'recall_numerator', 'recall_denominator'))


def count_keys(dashboard):
    return tuple(prefix + '_' + name for prefix, _ in warehouse.label_pairs(dashboard)
                 for name in profiles.DEFAULT_CONFIG['memberships'])


def now():
    return datetime.now(timezone.utc).isoformat()


def records(db, prefix):
    return [r.payload for r in db.scalars(select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith(prefix)))]


def filters(value):
    config = deepcopy(profiles.REVIEW_CONFIG if value is not None and 'platform_gen' in value else profiles.DEFAULT_CONFIG)
    config['population']['filters'] = deepcopy(profiles.DEFAULT_FILTERS if value is None else value)
    selected = profiles.validate(config)['population']['filters']
    return {k: sorted(set(v), key=str) for k, v in selected.items()}


def compatible_filters(source, selected):
    # A snapshot with an extra filter cannot establish an unfiltered scope.
    return set(source) == set(selected) and all(set(v) <= set(source[k]) for k,v in selected.items())


def validate(dashboard, physical):
    from app.services import auto_triage_metrics as at
    try:
        scope = dashboard['scope']
        if set(scope) != {'release', 'date_start', 'date_end'} or not at.RELEASE.fullmatch(scope['release']):
            raise ValueError('sample_scope_invalid')
        start, end = date.fromisoformat(scope['date_start']), date.fromisoformat(scope['date_end'])
        if start.isoformat() != scope['date_start'] or end.isoformat() != scope['date_end'] or not 0 <= (end-start).days <= 366:
            raise ValueError('sample_scope_invalid')
        observed = datetime.fromisoformat(dashboard['observed_at'])
        if observed.tzinfo is None:
            raise ValueError('sample_observed_at_invalid')
        selected = filters(dashboard.get('population_filters'))
        keys = count_keys(dashboard)
        if any(type(dashboard['counts'][k]) is not int for k in ('population_count', *keys)):
            raise ValueError('sample_counts_incomplete')
        for row in dashboard['rows']:
            if not isinstance(row['issue_id'], str) or any(type(row[k]) is not int for k in keys):
                raise ValueError('sample_memberships_incomplete')
            for prefix, field in warehouse.label_pairs(dashboard):
                value = row[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError('sample_label_invalid')
                if prefix + '_is_null' in row and row[prefix + '_is_null'] != int(value is None):
                    raise ValueError('dashboard_null_projection_missing')
            if dashboard.get('schema_version') in (2, 3):
                if set(selected) != set(profiles.REVIEW_CONFIG['population']['filters']):
                    raise ValueError('sample_review_filters_incomplete')
                # Store all four observed sources, even when an earlier source wins.
                # A later priority edit must never manufacture a missing observation.
                for field in (evaluation_labels.SOURCE_FIELDS[k] for k in evaluation_labels.CURRENT_PRIORITY):
                    if field not in row:
                        raise ValueError('sample_label_sources_incomplete')
                    if row[field] is not None and not isinstance(row[field], str):
                        raise ValueError('sample_label_invalid')
                    if field+'_is_null' in row and row[field+'_is_null'] != int(row[field] is None):
                        raise ValueError('dashboard_null_projection_missing')
                resolved = profiles.resolution(profiles.REVIEW_CONFIG, row)
                if resolved['status'] not in evaluation_labels.READY or resolved['raw_label'] != row['merged_ra_rd_result']:
                    raise ValueError('sample_review_label_mismatch')
            if dashboard.get('schema_version') == 3 and 'merged_ra_result' in row:
                raise ValueError('trail_baseline_not_observed')
        warehouse.validate_receipt({**dashboard, 'population_filters': selected})
        if set(physical) != {r['issue_id'] for r in dashboard['rows']}:
            raise ValueError('label_population_mismatch')
        for row in dashboard['rows']:
            iid = row['issue_id']
            label = physical[iid]
            if str(label['issue_id']) != iid or not all(k in label for k in at.QUERY_FIELDS):
                raise ValueError('label_projection_incomplete')
            if at._physical(label)['ra_type'] != (2 if row['ra_trigger_type'] == '自触发' else 3):
                raise ValueError('dashboard_trigger_type_changed')
        if dashboard.get('schema_version') == 3:
            from app.services.evaluation_trail import validate_native
            validate_native(dashboard,physical)
    except (KeyError, TypeError, AttributeError):
        raise ValueError('sample_snapshot_invalid') from None
    return selected


def import_snapshot(db, dashboard, physical, *, provenance):
    """Trusted offline entry point. No network. Validate before changing any row."""
    from app.services.evaluation_pipeline import lock
    selected = validate(dashboard, physical)
    dashboard = {k: v for k, v in dashboard.items() if k not in ('sample_snapshot_id', 'sample_stored_at', 'sample_source_scope')}
    dashboard = {**deepcopy(dashboard), 'population_filters': selected,
                 'rows': sorted(deepcopy(dashboard['rows']), key=lambda r: r['issue_id'])}
    body = {'schema_version': dashboard.get('schema_version', 1), 'dashboard': dashboard, 'labels': deepcopy(physical)}
    identifier = digest(body)
    key = SNAPSHOT + identifier[:48]
    index_key = INDEX + digest({'scope': dashboard['scope'], 'filters': selected})[:48]
    with lock('sample-import'):
        db.expire_all()
        previous = db.get(ReleaseWorkflowState, index_key)
        prior = previous.payload if previous else {}
        if prior.get('snapshot_id') == identifier:
            return {**prior, 'changed': False}
        if prior and datetime.fromisoformat(prior['observed_at']) > datetime.fromisoformat(dashboard['observed_at']):
            raise ValueError('sample_import_older_than_current')
        old = db.get(ReleaseWorkflowState, prior.get('snapshot_key', 'evsample:none'))
        old_rows = {r['issue_id']: r for r in old.payload['dashboard']['rows']} if old else {}
        new_rows = {r['issue_id']: r for r in dashboard['rows']}
        stored_at = now()
        value = {**body, 'id': identifier, 'stored_at': stored_at, 'provenance': deepcopy(provenance)}
        record = db.get(ReleaseWorkflowState, key)
        if record and digest({k: record.payload[k] for k in body}) != identifier:
            raise ValueError('sample_snapshot_corrupt')
        if not record:
            db.add(ReleaseWorkflowState(key=key, payload=value))
        else:
            stored_at = record.payload['stored_at']
        pointer = {'snapshot_id': identifier, 'snapshot_key': key, 'scope': dashboard['scope'],
                   'population_filters': selected, 'observed_at': dashboard['observed_at'],
                   'stored_at': stored_at, 'row_count': len(new_rows),
                   'provider':dashboard.get('provider','shuyi'), 'pending_count':len(dashboard.get('pending', [])),
                   'previous_snapshot_id': prior.get('snapshot_id'),
                   'changes': {'added': len(new_rows.keys()-old_rows.keys()), 'removed': len(old_rows.keys()-new_rows.keys()),
                               'updated': sum(new_rows[i] != old_rows[i] or physical[i] != old.payload['labels'][i]
                                              for i in new_rows.keys() & old_rows.keys())}}
        record = previous or ReleaseWorkflowState(key=index_key)
        record.payload = pointer
        db.add(record)
        try:
            db.commit()  # Immutable content and the current pointer become visible together.
        except Exception:
            db.rollback()
            raise
        return {**pointer, 'changed': True}


def selection(db, scope, population_filters=None):
    selected = filters(population_filters)
    candidates = [p for p in records(db, INDEX)
                  if p['scope']['release'] == scope['release']
                  and p['scope']['date_start'] <= scope['date_start'] <= scope['date_end'] <= p['scope']['date_end']
                  and compatible_filters(p['population_filters'], selected)]
    if not candidates:
        raise ValueError('sample_snapshot_required')
    return max(candidates, key=lambda p: (datetime.fromisoformat(p['observed_at']), p['stored_at'], p['snapshot_id']))


def read(db, scope, population_filters=None):
    selected = filters(population_filters)
    pointer = selection(db, scope, selected)
    record = db.get(ReleaseWorkflowState, pointer['snapshot_key'])
    if not record or digest({k: record.payload[k] for k in ('schema_version', 'dashboard', 'labels')}) != pointer['snapshot_id']:
        raise ValueError('sample_snapshot_corrupt')
    saved = record.payload
    source = saved['dashboard']
    rows = [r for r in source['rows'] if scope['date_start'] <= r['create_date'] <= scope['date_end']
            and all(r[k] in allowed for k, allowed in selected.items())]
    counts = {k: sum(r[k] for r in rows) for k in count_keys(source)}
    counts.update(population_count=len(rows), big_version='1.' + scope['release'])
    dashboard = {**deepcopy(source), 'scope': deepcopy(scope), 'population_filters': selected,
                 'rows': deepcopy(rows), 'counts': counts, 'sample_snapshot_id': pointer['snapshot_id'],
                 'sample_stored_at': pointer['stored_at'], 'sample_source_scope': source['scope']}
    if source.get('provider') == 'trail':
        dashboard['pending'] = [deepcopy(item) for item in source.get('pending', [])
            if scope['date_start'] <= item['row']['create_date'] <= scope['date_end']
            and all(key == item['field'] or item['row'][key] in allowed for key, allowed in selected.items())]
    physical = {r['issue_id']: deepcopy(saved['labels'][r['issue_id']]) for r in rows}
    warehouse.validate_receipt(dashboard)
    return dashboard, physical


def status(db, scope, population_filters=None):
    try:
        pointer = selection(db, scope, population_filters)
    except ValueError as exc:
        return {'status': 'missing', 'mode': 'database', 'error': str(exc), 'requested_scope': scope}
    return {**pointer, 'status': 'ready', 'mode': 'database', 'requested_scope': scope}


def migrate(db):
    """One-shot promotion of previously reconciled receipts; never requery upstream."""
    sources = []
    for row in db.scalars(select(ReleaseWorkflowState).where(
            ReleaseWorkflowState.key.startswith('at_labels:') | ReleaseWorkflowState.key.startswith('evrevision:'))):
        source = row.payload.get('source', {}) if row.key.startswith('evrevision:') else row.payload
        if source.get('dashboard') is not None:
            sources.append((row.key, source['dashboard'], source.get('labels', source.get('rows'))))
    results = []
    for key, dashboard, physical in sorted(sources, key=lambda s: s[1]['observed_at']):
        # A derived subset cannot establish that a larger scope is complete.
        if dashboard.get('sample_snapshot_id'):
            continue
        try:
            results.append(import_snapshot(db, dashboard, physical, provenance={'kind': 'reconciled_database_receipt', 'state_key': key}))
        except ValueError as exc:
            if str(exc) != 'sample_import_older_than_current':
                raise
            # Repeating migration must not roll a newer offline update back.
            results.append({**selection(db, dashboard['scope'], dashboard.get('population_filters')),
                            'changed': False, 'skipped_older_receipt': True})
    return results
