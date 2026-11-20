"""Immutable, declarative evaluation rules. No executable SQL or Python in configs."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import ReleaseWorkflowState
from app.services.release_cycle import digest
from app.services import release_workflow as w
from app.services import evaluation_labels as labels

GOOD = ['成功', '失败', '无需协助', '限制使用']
EXCLUDED = ['out_of_scope', '未接起', '未填写']
DEFAULT_FILTERS = {'trip_odd': ['ODD2'], 'trip_category_name': ['Daily Cruise/稳定版本测试'],
                   'version_category': ['release版本'], 'is_deleted': [0]}
DEFAULT_CONFIG = {
    'schema_version': 1, 'population': {'date_field': 'create_date', 'filters': DEFAULT_FILTERS},
    'label': {'source': 'merged_ra_auto_result', 'mapping': {}},
    'memberships': {
        'precision_numerator': {'triggers': [2], 'include': GOOD},
        'precision_denominator': {'triggers': [2], 'exclude': EXCLUDED},
        'recall_numerator': {'triggers': [2], 'exclude': ['误触发', *EXCLUDED]},
        'recall_denominator': {'triggers': [2, 3], 'exclude': ['误触发', *EXCLUDED]},
    },
}
BUILTIN = {'id': 'auto_triage_sql_v2', 'name': 'SQL v2', 'status': 'published',
           'config': DEFAULT_CONFIG, 'config_hash': digest(DEFAULT_CONFIG), 'created_at': None,
           'parent': None, 'description': 'Verified literal-label SQL, 2026-11-04'}

# Keep the legacy configuration and its digest immutable. Activation is explicit.
REVIEW_CONFIG = deepcopy(DEFAULT_CONFIG)
REVIEW_CONFIG.update(schema_version=2)
REVIEW_CONFIG['population']['filters']['platform_gen'] = ['GEN4_PT', 'GEN4_SOP']
REVIEW_CONFIG['label'] = {'source': 'coalesce', 'priority': list(labels.CURRENT_PRIORITY), 'mapping': {}}
REVIEW = {'id': 'auto_triage_review_v1', 'name': '人工复核', 'status': 'published',
          'config': REVIEW_CONFIG, 'config_hash': digest(REVIEW_CONFIG), 'created_at': None,
          'parent': BUILTIN['id'], 'description': 'Shuyi verified review basis, PT + SOP, 2026-11-09'}
BUILTINS = {p['id']: p for p in (BUILTIN, REVIEW)}


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_CONFIG) or config['schema_version'] not in (1, 2):
        raise ValueError('profile_schema_invalid')
    population = config['population']
    if set(population) != {'date_field', 'filters'} or population['date_field'] != 'create_date':
        raise ValueError('profile_date_field_invalid')
    filters = population['filters']
    expected_filters = set(DEFAULT_FILTERS) | ({'platform_gen'} if config['schema_version'] == 2 else set())
    if set(filters) != expected_filters:
        raise ValueError('profile_filters_invalid')
    for name, values in filters.items():
        if not isinstance(values, list) or not 1 <= len(values) <= 30 or any(type(v) not in (str, int) for v in values):
            raise ValueError('profile_filters_invalid')
        if name == 'is_deleted' and values != [0]:
            raise ValueError('profile_deleted_population_invalid')
    label = config['label']
    if config['schema_version'] == 1:
        if set(label) != {'source', 'mapping'} or label['source'] not in ('merged_ra_auto_result', 'merged_ra_result'):
            raise ValueError('profile_label_invalid')
    else:
        if set(label) != {'source', 'priority', 'mapping'} or label['source'] != 'coalesce':
            raise ValueError('profile_label_invalid')
        labels.validate_policy(label)
    if not isinstance(label['mapping'], dict) or len(label['mapping']) > 100 or any(
            not isinstance(k, str) or len(k) > 100 or v is not None and (not isinstance(v, str) or len(v) > 100)
            for k, v in label['mapping'].items()):
        raise ValueError('profile_mapping_invalid')
    rules = config['memberships']
    if set(rules) != set(DEFAULT_CONFIG['memberships']):
        raise ValueError('profile_memberships_invalid')
    for rule in rules.values():
        if not isinstance(rule, dict) or set(rule) not in ({'triggers', 'include'}, {'triggers', 'exclude'}):
            raise ValueError('profile_condition_invalid')
        if not isinstance(rule['triggers'], list) or not rule['triggers'] or any(type(v) is not int or v not in (2, 3) for v in rule['triggers']):
            raise ValueError('profile_trigger_invalid')
        values = rule.get('include', rule.get('exclude'))
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 100 for v in values):
            raise ValueError('profile_condition_invalid')
    # A numerator outside its denominator cannot be presented as a rate.
    label_domain = {None, '', '__unlisted__', *[v for rule in rules.values() for v in rule.get('include', rule.get('exclude'))]}
    for trigger in (2, 3):
        for value in label_domain:
            flags = membership(config, trigger, value)
            if any(flags[m + '_numerator'] > flags[m + '_denominator'] for m in ('precision', 'recall')):
                raise ValueError('profile_numerator_outside_denominator')
    return deepcopy(config)


def membership(config, trigger, label):
    # SQL UNKNOWN is not a member: NULL never matches IN or NOT IN.
    return {name: int(label is not None and trigger in rule['triggers'] and
                     (label in rule['include'] if 'include' in rule else label not in rule['exclude']))
            for name, rule in config['memberships'].items()}


def resolve(config, row):
    if config['label']['source'] == 'coalesce':
        result = resolution(config, row)
        if result['status'] not in labels.READY:
            raise ValueError('label_source_' + result['status'])
        return result['label']
    value = row[config['label']['source']]
    return config['label']['mapping'].get(value, value) if value is not None else None


def resolution(config, row):
    if config['label']['source'] == 'coalesce':
        return labels.resolve_label(row, config['label'])
    value = row[config['label']['source']]
    return {'label': config['label']['mapping'].get(value, value) if value is not None else None,
            'raw_label': value, 'source': 'warehouse', 'status': 'resolved' if value is not None else 'all_null',
            'policy_version': digest(config['label']), 'source_revision': None, 'trace': []}


def get(db, version=None):
    version = version or w.get_state(db, 'evprofile:active').get('id') or BUILTIN['id']
    if version in BUILTINS:
        return deepcopy(BUILTINS[version])
    value = w.get_state(db, 'evprofile:' + str(version))
    if not value:
        raise ValueError('profile_not_found')
    return value


def catalogue(db):
    records = [*[deepcopy(p) for p in BUILTINS.values()], *[r.payload for r in db.scalars(select(ReleaseWorkflowState).where(
        ReleaseWorkflowState.key.startswith('evprofile:'))) if r.key != 'evprofile:active']]
    return {'active': get(db)['id'], 'versions': sorted(records, key=lambda r: r.get('created_at') or '', reverse=True),
            'label_sources': [{'id': name, 'field': field, 'requires_adapter': field is None}
                              for name, field in labels.SOURCE_FIELDS.items()]}


def draft(db, config, name, description, parent=None):
    from app.services.evaluation_pipeline import lock
    with lock('profiles'):
        return _draft(db, config, name, description, parent)


def _draft(db, config, name, description, parent=None):
    config = validate(config)
    if not name.strip() or len(name) > 80 or len(description) > 2000:
        raise ValueError('profile_name_invalid')
    parent = get(db, parent)['id']
    value = {'name': name.strip(), 'description': description, 'config': config,
             'config_hash': digest(config), 'parent': parent, 'created_at': now(), 'status': 'draft'}
    value['id'] = 'draft_' + digest(value)[:24]
    w.put_state(db, 'evprofile:' + value['id'], value)
    return value


def publish(db, version, preview_hash, *, activate=None):
    from app.services.evaluation_pipeline import lock
    with lock('profiles'):
        db.expire_all()
        preview = w.get_state(db, 'evpreview:' + preview_hash[:48])
        with lock('context:' + digest(preview.get('context', {}))):
            return _publish(db, version, preview_hash, activate=activate)


def _publish(db, version, preview_hash, *, activate=None):
    value = get(db, version)
    if value['status'] == 'published':
        return value
    preview = w.get_state(db, 'evpreview:' + preview_hash[:48])
    if not preview or preview.get('profile_id') != version or preview.get('config_hash') != value['config_hash']:
        raise ValueError('profile_preview_required')
    from app.services import evaluation_pipeline as pipeline
    view = pipeline.board(db, **preview['context'])
    if view['stale'] or not view['revision'] or view['revision']['revision_key'] != preview['base_revision']:
        raise ValueError('plan_stale')
    result = {**value, 'id': 'at_' + value['config_hash'][:24], 'status': 'published',
              'published_at': now(), 'preview_hash': preview_hash}
    key = 'evprofile:' + result['id']
    if not w.get_state(db, key):
        w.put_state(db, key, result)
    # Publication uses the verified preview receipt immediately. A later source
    # refresh may fail without discarding the newly reviewed metrics and plan.
    published = get(db, result['id'])
    from contextlib import nullcontext
    ctx = {**preview['context'], 'profile_id': published['id']}
    with pipeline.lock('context:' + digest(ctx)) if ctx != preview['context'] else nullcontext():
        pipeline.publish_profile_revision(db, published, preview)
    # Preserve the legacy API contract. Review policies are staged until an
    # explicit activation validates every requested release/context together.
    if activate is True or activate is None and value['config']['schema_version'] == 1:
        _activate(db, result['id'], [ctx], get(db)['id'], locked_contexts=[preview['context']])
    return get(db, result['id'])


def activate(db, version, contexts, expected_active):
    from app.services.evaluation_pipeline import lock
    with lock('profiles'):
        return _activate(db, version, contexts, expected_active)


def _activate(db, version, contexts, expected_active, *, locked_contexts=()):
    from contextlib import ExitStack
    from app.services import evaluation_pipeline as pipeline
    if not isinstance(contexts, list) or not 1 <= len(contexts) <= 100:
        raise ValueError('profile_activation_context_invalid')
    db.expire_all()
    profile = get(db, version)
    if profile['status'] != 'published':
        raise ValueError('profile_not_published')
    if get(db)['id'] != expected_active:
        raise ValueError('profile_active_changed')
    canonical = []
    for ctx in contexts:
        if not isinstance(ctx, dict) or set(ctx) - {'release','profile_id','date_start','date_end'} or ctx.get('profile_id') not in (None,version):
            raise ValueError('profile_activation_context_invalid')
        resolved, *_ = pipeline.context(db, **{**ctx,'profile_id':version})
        canonical.append(resolved)
    if len({digest(c) for c in canonical}) != len(canonical):
        raise ValueError('profile_activation_context_invalid')
    with ExitStack() as stack:
        stack.enter_context(pipeline.lock('sample-import'))
        for ctx in sorted(canonical, key=digest):
            if digest(ctx) not in {digest(c) for c in locked_contexts}:
                stack.enter_context(pipeline.lock('context:' + digest(ctx)))
        db.expire_all()
        receipts = []
        for ctx in canonical:
            view = pipeline.board(db, **ctx)
            revision = view['revision']
            if view['stale'] or not revision or view['sample_source']['status'] != 'ready' or revision['reconciliation']['status'] != 'matched':
                raise ValueError('profile_activation_revision_required')
            receipts.append({'context':ctx,'revision_key':revision['revision_key'],
                             'sample_snapshot_id':view['sample_source']['snapshot_id']})
        prior = w.get_state(db, 'evprofile:active')
        value = {'id':version,'previous_id':expected_active,'activated_at':now(),
                 'contexts':receipts,'previous_pointer':deepcopy(prior)}
        # One commit makes the activation pointer and audit visible atomically.
        audit_key = 'evactivation:' + digest(value)[:48]
        pointer = db.get(ReleaseWorkflowState,'evprofile:active') or ReleaseWorkflowState(key='evprofile:active')
        pointer.payload = {k:v for k,v in value.items() if k!='previous_pointer'}
        db.add(pointer)
        db.add(ReleaseWorkflowState(key=audit_key,payload=value))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {'active':version,'audit_key':audit_key,'contexts':receipts}
