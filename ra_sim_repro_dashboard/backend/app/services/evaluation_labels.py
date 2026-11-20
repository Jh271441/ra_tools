"""Pure, versioned label resolution shared by evaluation and source attribution.

Adapters project unavailable fields separately from observed SQL NULL. Priorities
are data; no executable expressions or arbitrary field names come from configs.
"""
from collections.abc import Mapping
from functools import lru_cache
import hashlib
import json

SOURCE_FIELDS = {
    'review': None,
    'te_prime': None,
    'te': 'ra_review_result_new',
    'rd': 'ra_rd_review_result',
    'auto': 'ra_stuck_auto_result',
    'to': 'ra_original_result',
}
CURRENT_PRIORITY = ['te', 'rd', 'auto', 'to']
FUTURE_PRIORITY = ['review', 'te_prime', *CURRENT_PRIORITY]
READY = ('resolved', 'all_null')


def validate_policy(policy):
    if not isinstance(policy, Mapping):
        raise ValueError('profile_priority_invalid')
    priority = policy.get('priority')
    if (not isinstance(priority, list) or not 1 <= len(priority) <= len(SOURCE_FIELDS)
            or any(not isinstance(name, str) or name not in SOURCE_FIELDS for name in priority)
            or len(set(priority)) != len(priority)):
        raise ValueError('profile_priority_invalid')
    return policy


@lru_cache(maxsize=128)
def _version(serialized):
    return hashlib.sha256(serialized.encode()).hexdigest()


def source_value(sample, name):
    """Read a registered flat projection or a future adapter's explicit receipt."""
    projected = sample.get('label_sources', {})
    if isinstance(projected, Mapping) and name in projected:
        item = projected[name]
        if not isinstance(item, Mapping):
            return {'state': 'unavailable'}
        if item.get('state') in ('unavailable', 'conflict'):
            return {'state': item['state'], 'revision': item.get('revision')}
        if item.get('state') != 'observed' or 'value' not in item:
            return {'state': 'unavailable'}
        value = item['value']
        revision = item.get('revision')
    else:
        field = SOURCE_FIELDS[name]
        if field is None or field not in sample:
            return {'state': 'unavailable'}
        value, revision = sample[field], None
    if value is not None and not isinstance(value, str):
        return {'state': 'unavailable', 'revision': revision}
    return {'state': 'null' if value is None else 'value', 'value': value, 'revision': revision}


def resolve_label(sample, policy, *, policy_version=None):
    """Resolve the first known non-NULL source, preserving every literal value."""
    validate_policy(policy)
    version = policy_version or _version(json.dumps(policy, sort_keys=True, ensure_ascii=True))
    trace = []
    for name in policy['priority']:
        item = source_value(sample, name)
        trace.append({'source': name, 'state': item['state']})
        if item['state'] in ('unavailable', 'conflict'):
            return {'label': None, 'raw_label': None, 'source': None,
                    'policy_version': version, 'source_revision': item.get('revision'),
                    'status': item['state'], 'trace': trace}
        if item['state'] == 'value':
            raw = item['value']
            return {'label': policy.get('mapping', {}).get(raw, raw), 'raw_label': raw,
                    'source': name, 'policy_version': version,
                    'source_revision': item.get('revision'), 'status': 'resolved', 'trace': trace}
    return {'label': None, 'raw_label': None, 'source': None, 'policy_version': version,
            'source_revision': None, 'status': 'all_null', 'trace': trace}
