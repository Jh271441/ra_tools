"""Immutable timing sidecar. Reads never contact Scenario, Orion, Trail or Shuyi."""
from collections import defaultdict
from copy import deepcopy
from sqlalchemy import select
from app.models import ReleaseSimulationBatch, ReleaseWorkflowState, ReleaseIssueSnapshot
from app.services import reproduction_timing as timing
from app.services.release_cycle import digest

SCHEMA = 'reproduction_evidence_v1'


def active(db, release):
    row = db.get(ReleaseWorkflowState, 'rtime_policy:' + release)
    return bool(row and row.payload == {'policy': timing.POLICY, 'enabled': True})


def evaluation_policy_key(release, profile_id):
    return 'evtiming:' + digest([release, profile_id])[:48]


def evaluation_active(db, release, profile):
    """A metric profile may opt in without changing ordinary simulation history."""
    from app.services import metric_profiles
    current, seen = profile or {}, set()
    while current.get('id'):
        identifier = current['id']
        if identifier in seen or len(seen) >= 32:
            raise ValueError('reproduction_policy_parent_invalid')
        seen.add(identifier)
        row = db.get(ReleaseWorkflowState, evaluation_policy_key(release, identifier))
        if row:
            value = row.payload
            if (set(value) != {'release','profile_id','policy','boundary_band_ms','enabled'}
                    or value['release'] != release or value['profile_id'] != identifier
                    or value['policy'] != timing.POLICY or value['boundary_band_ms'] != timing.DEFAULT_BAND_MS
                    or type(value['enabled']) is not bool):
                raise ValueError('reproduction_policy_invalid')
            return value['enabled']
        parent = current.get('parent')
        current = metric_profiles.get(db, parent) if parent else {}
    return active(db, release)


def binding(release, issue, scene, signal, lineage):
    from app.services.auto_triage_metrics import _physical
    from app.services.label_recovery import SCENE_FIELDS
    execution = {k: lineage.get(k) for k in ('fingerprint', 'execution_id', 'audit_hash', 'job_id') if lineage.get(k) is not None}
    if (not execution.get('audit_hash') or not execution.get('job_id')
            or bool(execution.get('fingerprint')) == bool(execution.get('execution_id'))):
        raise ValueError('timing_execution_unverified')
    if type(signal.get('sim_triggered')) is not bool:
        raise ValueError('timing_signal_unverified')
    return {'release': release, 'issue_id': str(issue['issue_id']), 'physical': _physical(issue),
            'scene': {'scenario_id': str(scene['scenario_id']), **{k: scene.get(k) for k in SCENE_FIELDS}},
            'sim_triggered': signal['sim_triggered'], 'execution': execution}


def validate_record(db, record, source_cache=None):
    """Validate the stored execution, physical input and task before any DB write."""
    from app.services import auto_triage_metrics as at
    from app.services.result_publication import audit_hash
    value = record['binding']
    source = value['execution']
    sid, iid = str(value['scene']['scenario_id']), str(value['issue_id'])
    cache = source_cache if source_cache is not None else {}
    identity = (source.get('fingerprint'), source.get('execution_id'), source.get('audit_hash'))
    if identity in cache:
        p, inputs, tasks, scenes = cache[identity]
    elif source.get('fingerprint'):
        batch = db.get(ReleaseSimulationBatch, source['fingerprint'])
        if not batch or audit_hash(batch.payload) != source['audit_hash']:
            raise ValueError('timing_execution_changed')
        p = batch.payload
        inputs, _ = at.execution_inputs(db, batch)
        tasks = p.get('scenario_results', {})
    else:
        from app.services.evaluation_pipeline import execution_audit_hash
        state = db.get(ReleaseWorkflowState, 'evexecution:' + source['execution_id'])
        e = state.payload if state else {}
        if not e.get('audit_hash') or e['audit_hash'] != source['audit_hash'] or execution_audit_hash(e) != source['audit_hash']:
            raise ValueError('timing_execution_changed')
        p = {**e['plan'], 'job_id': e['job_id'], 'results': e['results']}
        inputs = {str(i['issue_id']): i for i in p['issues']}
        tasks = {str(r['scenario_id']): r for r in e['export']['rows']}
    if identity not in cache:
        scenes = {str(s['scenario_id']): s for s in p['scenarios']}
        cache[identity] = (p, inputs, tasks, scenes)
    scene, task = scenes.get(sid), tasks.get(sid, {})
    if (not scene or iid not in inputs or p['release'] != value['release']
            or str(p['job_id']) != str(source['job_id'])
            or binding(value['release'], inputs[iid], scene, p['results'][sid], source) != value):
        raise ValueError('timing_input_changed')
    if str(task.get('task_id')) != str(record.get('task_id')) or type(record.get('task_version')) is not int or record['task_version'] < 0:
        raise ValueError('timing_task_unverified')
    if not isinstance(record.get('artifact_sha256'), str) or len(record['artifact_sha256']) != 64:
        raise ValueError('timing_artifact_unverified')
    events = record.get('trigger_events')
    # Validate the signal even when this Issue lacks a usable manual anchor.
    test = timing.classify(3, scene.get('start_timestamp'), [{**scene,
        'sim_triggered': value['sim_triggered'], 'trigger_events': events}])
    if test['status'] in ('signal_unverified', 'signal_conflict'):
        raise ValueError('timing_events_unverified')


def save(db, release, records):
    """Caller commits with the execution receipt; existing rows are never edited."""
    if not records:
        return None
    cache = {}
    for record in records:
        if record['binding']['release'] != release:
            raise ValueError('timing_release_mixed')
        validate_record(db, record, cache)
    core = {'schema': SCHEMA, 'release': release,
            'records': sorted(records, key=lambda r: digest(r['binding']))}
    key = 'rtime:' + digest(core)[:48]
    existing = db.get(ReleaseWorkflowState, key)
    if existing and existing.payload != core:
        raise ValueError('timing_ledger_conflict')
    if not existing:
        db.add(ReleaseWorkflowState(key=key, payload=core))
    return key


def index(db, release):
    values = defaultdict(list)
    # Filter before transferring large immutable ledgers. Still validate each
    # returned payload and its content-addressed key below.
    statement = select(ReleaseWorkflowState).where(
        ReleaseWorkflowState.key.like('rtime:%'),
        ReleaseWorkflowState.payload['release'].as_string() == release)
    for row in db.scalars(statement):
        p = row.payload
        if p.get('release') != release or p.get('schema') != SCHEMA or row.key != 'rtime:' + digest(p)[:48]:
            continue
        for record in p['records']:
            values[digest(record['binding'])].append(record)
    return values


def evaluate(db, release, issues, scenes, results, lineage):
    evidence = index(db, release)
    groups = defaultdict(list)
    for scene in scenes:
        groups[str(scene['issue_id'])].append(scene)
    values = {}
    for issue in issues:
        iid = str(issue['issue_id'])
        inputs = []
        for scene in groups[iid]:
            sid = str(scene['scenario_id'])
            signal = results.get(sid, {})
            events = None
            try:
                expected = binding(release, issue, scene, signal, lineage.get(sid, {}))
                records = evidence.get(digest(expected), [])
                if records and len({digest(r['trigger_events']) for r in records}) == 1:
                    events = records[0]['trigger_events']
            except ValueError:
                pass
            inputs.append({**scene, 'sim_triggered': signal.get('sim_triggered'), 'trigger_events': events})
        ra_type = issue.get('ra_type')
        ra_type = int(ra_type) if isinstance(ra_type, str) and ra_type.isdecimal() else ra_type
        values[iid] = timing.classify(ra_type, issue.get('ra_start_timestamp'), inputs)
    return values


def overlay_metrics(metrics, evaluations):
    summary = timing.summarize(evaluations)
    return {**metrics, 'whole_window_road_matches': metrics['road_matches'],
            'whole_window_repro_rate': metrics.get('sim_repro_rate'),
            'whole_window_covered_repro_rate': metrics.get('covered_repro_rate', metrics.get('sim_repro_rate')),
            'road_matches': summary['matched'], 'sim_repro_rate': None if metrics.get('source_pending_count') else summary['rate'],
            'covered_repro_rate': summary['covered_rate'], 'reproduction': summary}


def evaluation_view(db, revision):
    release = (revision or {}).get('context', {}).get('release')
    if not release or not evaluation_active(db, release, (revision or {}).get('profile')):
        return revision
    p = revision['payload']
    # Resolve each execution once, retaining each scene's raw signal for multi-scene Issues.
    from app.services import evaluation_pipeline as pipeline
    actual, origins = {}, {}
    for sid, origin in revision['lineage'].items():
        key = origin.get('fingerprint') or origin.get('execution_id')
        if key not in origins:
            if origin.get('fingerprint'):
                batch = db.get(ReleaseSimulationBatch, key)
                if not batch or pipeline.at.audit_hash(batch.payload) != origin['audit_hash']:
                    return revision
                origins[key] = batch.payload.get('results', {})
            else:
                state = db.get(ReleaseWorkflowState, 'evexecution:' + key)
                e = state.payload if state else {}
                if not e.get('audit_hash') or pipeline.execution_audit_hash(e) != origin['audit_hash']:
                    return revision
                origins[key] = e.get('results', {})
        if sid in origins[key]:
            actual[sid] = origins[key][sid]
    values = evaluate(db, revision['context']['release'], p['issues'], p['scenarios'], actual, revision['lineage'])
    view = {**revision, 'rows': deepcopy(revision['rows']),
            'metrics': deepcopy(revision['metrics']), 'baseline': deepcopy(revision['baseline'])}
    for row in view['rows']:
        row['reproduction'] = values[str(row['issue_id'])]
    view['metrics'] = overlay_metrics(view['metrics'], (r['reproduction'] for r in view['rows'] if r['eligible']))
    config = pipeline.profiles.DEFAULT_CONFIG
    if view['baseline'].get('source_available',True):
        view['baseline'] = overlay_metrics(view['baseline'], (r['reproduction'] for r in view['rows']
            if any(pipeline.profiles.membership(config, r['ra_type'], r['baseline_label'])[k]
                   for k in ('precision_denominator', 'recall_denominator'))))
    # The cohorts describe behavioral reproduction too; do not leave old matches beside the new rate.
    for name, label_key in (('metrics', 'auto_label'), ('baseline', 'baseline_label')):
        if view[name].get('source_available') is False:
            continue
        for group in view[name]['cohorts'].values():
            group.update(matches=0, evaluated=0)
        for row in view['rows']:
            label = row[label_key]
            membership = pipeline.profiles.membership(view['profile']['config'] if name == 'metrics' else config, row['ra_type'], label)
            if not (membership['precision_denominator'] or membership['recall_denominator']):
                continue
            group_key = ('positive_manual' if row['ra_type'] == 3 else 'positive_auto') if label in pipeline.profiles.GOOD else 'negative_auto' if label == '误触发' and row['ra_type'] == 2 else 'other_manual' if row['ra_type'] == 3 else 'other_auto'
            matched = row['reproduction']['matched']
            if type(matched) is bool:
                view[name]['cohorts'][group_key]['matches'] += matched
                view[name]['cohorts'][group_key]['evaluated'] += 1
    return view


def standard_inputs(db, batch, metrics):
    """Resolve only the already validated effective publication, including retries."""
    from app.services import auto_triage_metrics as at
    p = batch.payload
    issues = p['issues']
    base_hash = at.audit_hash(p)
    lineage = {str(s['scenario_id']): {'fingerprint': batch.fingerprint,
        'job_id': p['job_id'], 'audit_hash': base_hash} for s in p['scenarios'] if str(s['scenario_id']) in p.get('results', {})}
    pub = metrics.get('publication', {})
    for key in ('backfill_revision_key', 'label_revision_key'):
        state = db.get(ReleaseWorkflowState, pub.get(key, 'rtime:none'))
        revision = state.payload if state else {}
        if revision.get('issues') is not None:
            issues = revision['issues']
        elif revision.get('population_hash'):
            for snapshot in db.scalars(select(ReleaseIssueSnapshot).where(ReleaseIssueSnapshot.release == batch.release)
                                       .order_by(ReleaseIssueSnapshot.id.desc())):
                if at.workflow.population_identity(snapshot.payload) == revision['population_hash']:
                    issues = snapshot.payload['issues']
                    break
        if revision.get('lineage'):
            lineage = revision['lineage']
    scenes, results, physical = {}, {}, {}
    origins = {}
    for sid, origin in lineage.items():
        key = origin.get('fingerprint') or origin.get('execution_id')
        if key not in origins:
            if origin.get('fingerprint'):
                b = db.get(ReleaseSimulationBatch, key)
                inputs, _ = at.execution_inputs(db, b)
                origins[key] = (b.payload, {str(s['scenario_id']): s for s in b.payload['scenarios']}, inputs)
            else:
                e = db.get(ReleaseWorkflowState, 'evexecution:' + key).payload
                origins[key] = ({**e['plan'], 'results': e['results']},
                    {str(s['scenario_id']): s for s in e['plan']['scenarios']}, {str(i['issue_id']): i for i in e['plan']['issues']})
            physical.update(origins[key][2])
        execution, scene_index, inputs = origins[key]
        scene = scene_index[sid]
        scenes[sid], results[sid] = scene, execution['results'][sid]
    excluded = set(pub.get('excluded_issue_ids', []))
    rows = [{**physical.get(str(i['issue_id']), {}), **i} for i in issues if str(i['issue_id']) not in excluded]
    # Compact legacy plans omit physical fields; use the pre-registration input.
    from app.services.label_recovery import INPUT_FIELDS
    for row in rows:
        for field in INPUT_FIELDS:
            if field not in row:
                row[field] = physical.get(str(row['issue_id']), {}).get(field)
    return rows, list(scenes.values()), results, lineage


def standard_view(db, batch, metrics):
    if not metrics or not active(db, batch.release):
        return metrics
    from app.services.release_metrics import cohort_for_issue
    issues, scenes, results, lineage = standard_inputs(db, batch, metrics)
    eligible = [i for i in issues if cohort_for_issue(i)]
    # Never replace an audited denominator using an unresolved source revision.
    if len(eligible) != metrics['eligible']:
        return metrics
    values = evaluate(db, batch.release, eligible, scenes, results, lineage)
    view = overlay_metrics(metrics, values.values())
    for cohort in ('positive_auto', 'negative_auto', 'positive_manual'):
        summary = timing.summarize(values[str(i['issue_id'])] for i in eligible if cohort_for_issue(i) == cohort)
        view[cohort + '_repro_rate'] = summary['rate']
    return view


def annotate_standard_rows(db, release, rows):
    if not active(db, release):
        return rows
    from app.services.result_publication import published_batch, effective_publication
    batch = published_batch(db, release)
    metrics = effective_publication(db, batch) if batch else None
    if not metrics or not metrics.get('reproduction'):
        return rows
    issues, scenes, results, lineage = standard_inputs(db, batch, metrics)
    from app.services.release_metrics import cohort_for_issue
    issues = [i for i in issues if cohort_for_issue(i)]
    values = evaluate(db, release, issues, scenes, results, lineage)
    return [{**row, 'whole_window_reproduced': row.get('reproduced'),
             'reproduced': values[str(row['issue_id'])]['matched'],
             'reproduction': values[str(row['issue_id'])]} if str(row['issue_id']) in values else row for row in rows]


def capture_batch(db, batch, export):
    """Store completion evidence separately from historical publication hashes."""
    from app.services.auto_triage_metrics import execution_inputs
    from app.services.result_publication import audit_hash
    p = batch.payload
    inputs, _ = execution_inputs(db, batch)
    scenes = {str(s['scenario_id']): s for s in p['scenarios']}
    origin = {'fingerprint': batch.fingerprint, 'job_id': p['job_id'], 'audit_hash': audit_hash(p)}
    records = []
    for row in export.get('rows', []):
        sid = str(row['scenario_id'])
        evidence = row.get('reproduction_timing') or {}
        if evidence.get('status') != 'verified' or sid not in p.get('results', {}):
            continue
        scene = scenes[sid]
        iid = str(scene['issue_id'])
        if iid not in inputs or evidence.get('sim_triggered') != p['results'][sid]['sim_triggered']:
            continue
        records.append({k: evidence[k] for k in ('task_id', 'task_version', 'artifact_sha256', 'trigger_events')})
        records[-1]['binding'] = binding(batch.release, inputs[iid], scene, p['results'][sid], origin)
    return save(db, batch.release, records)


def capture_execution(db, execution):
    p = execution['plan']
    scenes = {str(s['scenario_id']): s for s in p['scenarios']}
    issues = {str(i['issue_id']): i for i in p['issues']}
    origin = {'execution_id': execution['id'], 'job_id': execution['job_id'], 'audit_hash': execution['audit_hash']}
    records = []
    for row in execution['export'].get('rows', []):
        sid = str(row['scenario_id'])
        evidence = row.get('reproduction_timing') or {}
        signal = execution.get('results', {}).get(sid)
        if evidence.get('status') != 'verified' or not signal or evidence.get('sim_triggered') != signal['sim_triggered']:
            continue
        scene = scenes[sid]
        records.append({k: evidence[k] for k in ('task_id', 'task_version', 'artifact_sha256', 'trigger_events')})
        records[-1]['binding'] = binding(p['release'], issues[str(scene['issue_id'])], scene, signal, origin)
    return save(db, p['release'], records)


def capture_completion(db, *, batch=None, export=None, execution=None):
    """An unavailable timing artifact cannot turn a valid scalar task into a failure."""
    try:
        key = capture_batch(db, batch, export) if batch is not None else capture_execution(db, execution)
        db.commit()
        return key
    except (KeyError, ValueError, TypeError):
        db.rollback()
        return None
