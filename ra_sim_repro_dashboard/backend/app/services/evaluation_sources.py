"""Small, read-only source attribution derived from one saved evaluation revision.

No acquisition, simulation or ledger writes. Literal labels and the selected
profile's independent membership counts remain unchanged.
"""
from collections import Counter
from .auto_triage_metrics import business_label
from .metric_profiles import membership, resolve, resolution

ROUTES = ('model', 'ra_result', 'unverified')
MEMBERSHIPS = ('precision_numerator', 'precision_denominator', 'recall_numerator', 'recall_denominator')


def _class(label):
    if label in ('正确触发', '成功', '失败'):
        return 'correct'
    return {'误触发': 'false', '无需协助': 'no_assist'}.get(label, 'other')


def _labels(counter):
    return [{'label': label, 'count': count} for label, count in sorted(counter.items(), key=lambda item: (item[0] is not None, str(item[0])))]


def distribution(revision):
    missing = {'available': False, 'error': 'source_unavailable'}
    try:
        dashboard = revision['source']['dashboard']
        physical = revision['source']['labels']
        config = revision['profile']['config']
        review = config['label']['source'] == 'coalesce'
        source = {row['issue_id']: row for row in dashboard['rows']}
        rows = {row['issue_id']: row for row in revision['rows']}
        if (len(source) != len(dashboard['rows']) or len(rows) != len(revision['rows']) or
                set(source) != set(rows) or len(rows) != revision['source_count']):
            return {**missing, 'error': 'source_inconsistent'}
        groups = {key: {'id': key, 'count': 0, 'classes': {name: 0 for name in ('correct','false','no_assist','other')},
                        'classified_count': 0, 'memberships': {name: 0 for name in MEMBERSHIPS},
                        'triggers': {'auto': 0, 'manual': 0}, 'raw_labels': Counter(), 'labels': Counter()}
                  for key in ([*config['label']['priority'], 'no_result', 'unverified'] if review else ROUTES)}
        correct_not_precision = 0
        memberships = {}
        for iid, row in rows.items():
            raw = source[iid]['merged_ra_auto_result']
            observed = physical.get(iid, {})
            route = 'unverified'
            if review:
                receipt = resolution(config, source[iid])
                if receipt['status'] not in ('resolved', 'all_null') or row.get('label_resolution') != receipt:
                    return {**missing, 'error': 'source_inconsistent'}
                route = receipt['source'] or 'no_result'
                raw = receipt['raw_label']
                label = receipt['label']
            elif all(key in observed for key in ('ra_stuck_auto_result', 'ra_result')):
                model = observed['ra_stuck_auto_result']
                expected = str(model) if model is not None else business_label(observed['ra_result'])
                if expected == raw:
                    route = 'model' if model is not None else 'ra_result'
            if not review:
                label = resolve(config, source[iid])
            identity = (row['ra_type'], label)
            if identity not in memberships:
                memberships[identity] = membership(config, *identity)
            flags = memberships[identity]
            if label != row['auto_label'] or flags != row['auto_memberships'] or row['ra_type'] not in (2,3):
                return {**missing, 'error': 'source_inconsistent'}
            group = groups[route]
            group['count'] += 1
            group['raw_labels'][raw] += 1
            group['labels'][label] += 1
            group['classes'][_class(label)] += 1
            group['classified_count'] += _class(label) != 'other'
            group['triggers']['auto' if row['ra_type'] == 2 else 'manual'] += 1
            for key in MEMBERSHIPS:
                group['memberships'][key] += flags[key]
            correct_not_precision += bool(row['ra_type']==2 and label=='正确触发' and
                flags['precision_denominator'] and not flags['precision_numerator'] and flags['recall_numerator'])
        counts = {key: sum(g['memberships'][key] for g in groups.values()) for key in MEMBERSHIPS}
        if counts != revision['metrics']['counts']:
            return {**missing, 'error': 'source_inconsistent'}
        for group in groups.values():
            for field in ('raw_labels', 'labels'):
                group[field] = _labels(group[field])
        return {'available': True, 'schema_version': 2 if review else 1, 'revision_key': revision['revision_key'],
                'context': dict(revision['context']), 'total': len(rows),
                'sample_snapshot_id': dashboard.get('sample_snapshot_id'), 'observed_at': dashboard['observed_at'],
                'label_source': config['label']['source'], 'label_mapping': dict(config['label']['mapping']),
                **({'label_priority': list(config['label']['priority'])} if review else {}),
                'rules': config['memberships'], 'groups': list(groups.values()), 'counts': counts,
                'correct_not_precision': correct_not_precision}
    except (KeyError, TypeError, AttributeError, ValueError):
        return missing
