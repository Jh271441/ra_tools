"""Audited GT cohort label repair for scenes with no submitted simulation."""
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ra_api.release_labels import cohort_label_update, full_scene_label, scene_labels


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reconcile(payload, query, update, directory):
    """Validate the complete batch before writing, then verify live metadata."""
    period = payload['period']
    release = payload['release']
    label = payload['label']
    if not period.get('verified') or period.get('release') != release or full_scene_label(period) != label:
        raise ValueError('Verified canonical release required for label synchronization')
    changes = payload['changes']
    expected = {str(c['scenario_id']): c for c in changes}
    if not changes or len(expected) != len(changes) or not payload.get('source_hash'):
        raise ValueError('Invalid label synchronization scope')

    def fetch():
        rows = query(list(expected))
        found = {str(row['id']): row for row in rows}
        if len(rows) != len(expected) or len(found) != len(rows) or set(found) != set(expected):
            raise ValueError('Live Scenario identity coverage mismatch')
        return found

    def identity(row, change):
        if row.get('is_deleted') or any(row.get(k) != change.get(k) for k in ('start_timestamp', 'end_timestamp')):
            raise ValueError('Scenario input changed before label synchronization')
        ids = {v for v in scene_labels(row) if v.startswith('#') and v[1:].isdigit()}
        if ids != {'#' + str(change['issue_id']).removeprefix('cn')}:
            raise ValueError('Scenario source Issue changed before label synchronization')

    # Labels may advance the metadata revision; execution inputs must stay identical.
    def inputs(row):
        return {k:row.get(k) for k in ('name', 'scenario', 'start_timestamp', 'end_timestamp', 'scenario_tags')}

    directory = Path(directory) / 'label-sync'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'reconcile.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = fetch()
        for sid, change in expected.items():
            row = before[sid]
            identity(row, change)
            if row.get('version') != change.get('scenario_revision') or scene_labels(row) != set(change['before_labels']):
                raise ValueError('Scenario metadata changed before label synchronization')
            target = cohort_label_update(row, label, release, change['cohort'])
            if target is None or target != change['after_labels']:
                raise ValueError('Label update differs from canonical GT cohort')
        request_hash = digest(payload)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path = directory / f'{release}-{stamp}-{request_hash[:12]}.json'
        audit = {'request_hash':request_hash, 'request':payload, 'status':'planned',
                 'before':before, 'updated_ids':[], 'checked_at':datetime.now(timezone.utc).isoformat()}

        def save():
            temp = path.with_suffix('.next')
            with temp.open('w') as stream:
                json.dump(audit, stream, ensure_ascii=False, indent=2)
            temp.chmod(0o600)
            os.replace(temp, path)

        save()
        try:
            for sid, change in expected.items():
                response = update(sid, change['after_labels'])
                if not response or response.get('msg') != 'success':
                    raise ValueError('Scenario cohort label update failed')
                audit['updated_ids'].append(sid)
                save()
            after = fetch()
            for sid, row in after.items():
                identity(row, expected[sid])
                if scene_labels(row) != set(expected[sid]['after_labels']) or inputs(row) != inputs(before[sid]):
                    raise ValueError('Scenario input or labels differ after synchronization')
            audit.update(status='complete', after=after)
            save()
        except Exception as exc:
            audit.update(status='failed', error=type(exc).__name__)
            save()
            raise
        return {'ready':True, 'verified_count':len(expected), 'request_hash':request_hash, 'audit_path':str(path)}


def reconcile_labels(payload):
    from ra_api.scenario_api import trail_api, ScenarioURL
    from ra_api.sim_result_api import SimResultClient
    trail_api.token = SimResultClient()._app_token

    def query(ids):
        rows = []
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            response = trail_api.send_request(ScenarioURL.query.value, {'id':','.join(batch), 'page':1, 'size':500})
            if not response or response.get('msg') != 'success':
                raise ValueError('Cannot verify live Scenario metadata')
            data = response['data']
            found = data.get('res', data.get('data', []))
            if int(data.get('total', data.get('count', -1))) != len(batch) or len(found) != len(batch):
                raise ValueError('Scenario metadata query is incomplete')
            rows.extend(found)
        return rows

    def update(sid, labels):
        return trail_api.send_request(ScenarioURL.update.value, {'id':int(sid), 'labels':','.join(labels),
            'updater':'jasperchen', 'user_location':'cn', 'keep_review_status':True})

    return reconcile(payload, query, update, os.environ['RELEASE_DRIVER_STATE_DIR'])
