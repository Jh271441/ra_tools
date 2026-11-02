"""Read-only native reconciliation before an existing video retry takes text ownership.

This never creates a job or a text worker. Unknown submissions, unknown uploads,
live attempts, source failures with a receipt, and ambiguous local owners stay held.
"""
import json
from pathlib import Path
import time

from ra_triage_dashboard.app.planning_text_artifact import identity, digest
from ra_triage_dashboard.app.planning_text_daily import capture_owner, transfer_owner


def reconcile(profile, member, owner, context):
    current = capture_owner(profile['data_dir'], member)
    if not current or current['state'] != 'pending' or current['owner'] == owner:
        return False
    root = Path(profile['data_dir'])/'planning_constraints'
    records = []
    for path in (root/'runs').glob('*.json'):
        record = json.loads(path.read_text())
        matching = [m for m in record['members'] if identity(m) == identity(member)
                    and m['owner'] == current['owner'] and m.get('extract')]
        if matching:
            records.append((record, matching[0]))
    if len(records) != 1:
        return False
    record, previous_member = records[0]
    launch = Path(record['run'])/'launch.receipt.json'
    if not launch.is_file():
        return False  # Local owner needs its explicit process/attempt reconciliation.
    native = json.loads(launch.read_text())
    if native.get('status') != 'submitted':
        return False
    from .import_results import list_files
    observed = list_files(native['job_id'], root, {identity(member): previous_member})
    missing = observed['missing']
    if (observed['job_state'] != 2 or observed['files'] or len(missing) != 1
            or not missing[0].get('missing_confirmed') or missing[0]['task_status'] not in {3, 4, 5}):
        return False
    evidence = dict(missing[0], kind='native_terminal_no_object', job_id=native['job_id'],
                    job_state=observed['job_state'], observed_at=time.time(),
                    observation_sha256=digest(root/'native-observations'/f"{native['job_id']}.json"))
    return transfer_owner(profile['data_dir'], member, current['owner'], owner, context, evidence)
