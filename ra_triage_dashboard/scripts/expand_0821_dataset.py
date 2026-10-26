"""Audited additive 0821 membership expansion. Never rewrites existing tasks/labels.

Prepare queries Trail read-only and freezes two identical complete ID passes.
apply_database is called only by the backup-bound cutover/rehearsal orchestrator.
Production data and receipts stay on the cloud host, outside the source checkout.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

OLD_SCOPES = ['release0821_1242_20260908', 'manual_sidecar_0821-review-extra']
NEW_ID = '0821-trail-extra'
NEW_SCOPE = 'manual_sidecar_0821-trail-extra'
ATTRS = [
    {'attr_id': 'version', 'operator': 'in', 'val': ['1.gen4-release-20260821.534']},
    {'attr_id': 'trip_category', 'operator': 'in', 'val': [0]},
    {'attr_id': 'ra_trigger', 'operator': 'not_in', 'val': ['CZ_TL']},
    {'attr_id': 'ra_type', 'operator': 'in', 'val': [2, 3]},
]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save_new(path, value):
    with path.open('x') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write('\n')


def live_environment():
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = (proc/'cmdline').read_bytes().split(b'\0')
            if proc.stat().st_uid == os.getuid() and b'uvicorn' in args and b'8785' in args:
                found.append((proc, dict(x.split('=', 1) for x in
                    (proc/'environ').read_text().split('\0') if '=' in x)))
        except OSError:
            pass
    assert len(found) == 1, 'Expected exactly one owned production instance'
    return found[0]


def prepare(folder):
    import psycopg
    os.umask(0o077)
    assert folder.is_dir() and not (folder/'prepared.json').exists()
    proc, env = live_environment()
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):
            os.environ.pop(key)
    os.environ['NO_PROXY'] = '*'
    sys.path.insert(0, '/volume/home/workspace/ra_auto_triage')
    from utils.trail_api import TrailInterface
    from utils.config import config
    client = TrailInterface()

    def query():
        rows = []
        for page in range(1, 20):
            response = client.send_request(config.trail_api['query_url'], {
                'view_id': 2410, 'user_location': 'cn', 'page': page, 'size': 300,
                'query_attrs': ATTRS, 'filter_operator': 'AND'}, timeout=45)
            response.raise_for_status()
            payload = response.json()
            assert payload.get('code') == 0
            body = payload['data']
            assert body.get('total', body.get('count')) == 2005, 'Trail cohort changed'
            chunk = body.get('res') or body.get('data') or []
            assert chunk
            rows.extend(chunk)
            if len(rows) >= 2005:
                break
        assert len(rows) == len({row['issue_id'] for row in rows}) == 2005
        return rows

    rows = query()
    all_ids = sorted(row['issue_id'] for row in rows)
    assert all_ids == sorted(row['issue_id'] for row in query()), 'Trail membership moved'
    url = Path(env['DASHBOARD_DATABASE_URL_FILE']).read_text().strip()
    with psycopg.connect(url, options='-c default_transaction_read_only=on') as conn:
        old = conn.execute('SELECT issue_id, baseline_scope FROM issues WHERE baseline_scope=ANY(%s)', (OLD_SCOPES,)).fetchall()
        assert Counter(scope for _, scope in old) == dict(zip(OLD_SCOPES, [1242, 250]))
        old_ids = {issue for issue, _ in old}
        assert old_ids <= set(all_ids)
        new_ids = sorted(set(all_ids) - old_ids)
        assert len(new_ids) == 513
        assert not conn.execute('SELECT issue_id FROM issues WHERE issue_id=ANY(%s)', (new_ids,)).fetchall()
    registry_path = Path(env['DASHBOARD_BASELINES_FILE'])
    registry = json.loads(registry_path.read_text())
    assert isinstance(registry, list) and not any(x['id'] == NEW_ID for x in registry)
    members_path = Path(env['DASHBOARD_DATA_DIR'])/'manual_sidecar_members'/f'{NEW_ID}.json'
    assert not members_path.exists()
    layout_root = Path(env.get('DASHBOARD_MEDIA_LAYOUT_ROOT') or Path(env['DASHBOARD_DATA_DIR'])/'media_layouts')/NEW_SCOPE
    assert not layout_root.exists()
    new_set = set(new_ids)
    members = {'schema_version': 'capture-workset-v1', 'expected_count': 513,
        'rows': [{'issue_id': row['issue_id'], 'trip_id': row.get('trip_id') or '',
                  'gt_label': '', 'gt_source': '0821 membership expansion; GT not imported',
                  'summary': '', 'source': {key: row.get(key) for key in
                    ('version', 'trip_category', 'ra_trigger', 'ra_type')}}
                 for row in sorted(rows, key=lambda row: row['issue_id']) if row['issue_id'] in new_set]}
    save_new(folder/'members.json', members)
    entry = {'id': NEW_ID, 'label': '0821', 'scope': NEW_SCOPE, 'loader': 'capture_workset',
             'xlsx': str(members_path), 'expected_count': 513,
             'members_sha256': digest((folder/'members.json').read_bytes()), 'gt_mode': 'sparse',
             'default_selected': False, 'media': {'provider': 'product_layout', 'layout_id': NEW_SCOPE,
                 'lifecycle': True, 'strict_isolation': True}}
    save_new(folder/'registry-after.json', registry + [entry])
    save_new(folder/'registry-before.json', registry)
    save_new(folder/'prepared.json', {'prepared_at': datetime.now(timezone.utc).isoformat(),
        'query': ATTRS, 'all_ids': all_ids, 'old_ids': sorted(old_ids), 'new_ids': new_ids,
        'all_ids_sha256': digest('\n'.join(all_ids).encode()),
        'members_sha256': entry['members_sha256'],
        'registry_path': str(registry_path), 'registry_before_sha256': digest(registry_path.read_bytes()),
        'registry_after_sha256': digest((folder/'registry-after.json').read_bytes()),
        'members_path': str(members_path), 'layout_root': str(layout_root),
        'production_app': str((proc/'cwd').resolve()),
        'note': 'No task/assignment/history rewrite. 513 newly registered members remain unassigned.'})
    print(json.dumps({'prepared': str(folder), 'total': 2005, 'existing': 1492, 'new': 513}), flush=True)


def inventories(conn):
    from psycopg import sql
    result = {}
    for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall():
        table = row['tablename']
        result[table] = Counter(item['hash'] for item in conn.execute(sql.SQL(
            'SELECT md5(row_to_json(t)::text) AS hash FROM {} t').format(sql.Identifier(table))).fetchall())
    return result


def fingerprints(inventory):
    return {table: {'count': sum(rows.values()), 'sha256': digest(json.dumps(sorted(rows.items())).encode())}
            for table, rows in inventory.items()}


def apply_database(url, folder, *, backup_sha256):
    """One transaction; all old rows must survive byte-identically or roll back."""
    import psycopg
    from psycopg.rows import dict_row
    from app.db import Database
    from app.db_parts.shared import _PostgresConnection
    from app.baseline import load_capture_workset
    assert len(backup_sha256) == 64
    plan = json.loads((folder/'prepared.json').read_text())
    assert digest((folder/'members.json').read_bytes()) == plan['members_sha256']
    rows = load_capture_workset(folder/'members.json').rows
    assert sorted(row['issue_id'] for row in rows) == plan['new_ids']
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        conn.execute("SET LOCAL lock_timeout='10s'")
        conn.execute('SELECT pg_advisory_xact_lock(8212005)')
        old = conn.execute('SELECT issue_id FROM issues WHERE baseline_scope=ANY(%s)', (OLD_SCOPES,)).fetchall()
        assert sorted(row['issue_id'] for row in old) == plan['old_ids']
        assert not conn.execute('SELECT issue_id FROM issues WHERE issue_id=ANY(%s)', (plan['new_ids'],)).fetchall()
        assert not conn.execute('SELECT issue_id FROM issues WHERE baseline_scope=%s', (NEW_SCOPE,)).fetchall()
        before = inventories(conn)
        db = Database(url)

        @contextmanager
        def connect():
            yield _PostgresConnection(conn)

        db.connect = connect
        added = db.upsert_issues(rows, source='capture_workset', replace_gt=False, baseline_scope=NEW_SCOPE)
        assert added == {'inserted': 513, 'updated': 0, 'skipped': 0}
        db.apply_gt_sync_snapshot(scope=NEW_SCOPE, rows=[], source_name='membership-only-unobserved',
            source_view_id=2410, source_field='unobserved', trigger='0821-full-membership',
            requested_by='jasperchen', requested_by_source='authorized_dataset_migration',
            requested_by_verified=False, expected_issue_ids=plan['new_ids'], allow_sparse=True)
        db.set_labeling_scope_state(baseline_scope=NEW_SCOPE, status='active',
            policy_version='0821-full-membership-v1', source_inventory_sha256=plan['members_sha256'],
            updated_by='jasperchen', expected_epoch=0)
        all_rows = conn.execute('SELECT issue_id FROM issues WHERE baseline_scope=ANY(%s)', (OLD_SCOPES + [NEW_SCOPE],)).fetchall()
        assert sorted(row['issue_id'] for row in all_rows) == plan['all_ids']
        after = inventories(conn)
        append_only = {'issues', 'gt_sync_state', 'gt_sync_labels', 'gt_snapshots',
                       'gt_snapshot_items', 'gt_snapshot_active', 'labeling_scope_state'}
        revisions = {'dashboard_change_revision', 'dashboard_change_topics'}
        changed = []
        for table in before:
            if before[table] == after[table]:
                continue
            changed.append(table)
            if table in revisions:
                continue
            assert table in append_only, f'Unexpected changed table: {table}'
            assert not (before[table] - after[table]), f'Historical rows changed: {table}'
        receipt = {'backup_sha256': backup_sha256, 'total': 2005, 'added': added,
                   'before': fingerprints(before), 'after': fingerprints(after),
                   'changed_tables': changed, 'historical_rows_preserved': True,
                   'assignment_tables_unchanged': True, 'new_assignments': 0}
    return receipt


def rehearse(folder, dump):
    import getpass
    import subprocess
    import uuid
    import psycopg
    from backup_instance import fingerprints as backup_fingerprints
    from app.db import Database
    receipt = json.loads(dump.with_suffix('.receipt.json').read_text())
    assert receipt['restore_verified'] and digest(dump.read_bytes()) == receipt['sha256']
    name = 'manual_0821_rehearsal_' + uuid.uuid4().hex[:12]
    subprocess.run(['sudo', '-u', 'postgres', 'createdb', '--template=template0', '--owner', getpass.getuser(), name], check=True)
    try:
        subprocess.run(['pg_restore', '--dbname', name, '--no-owner', '--no-privileges', '--exit-on-error', str(dump)], check=True)
        with psycopg.connect(dbname=name) as conn:
            assert backup_fingerprints(conn) == receipt['table_fingerprints']
        result = apply_database('postgresql:///' + name, folder, backup_sha256=receipt['sha256'])
        db = Database('postgresql:///' + name)
        plan = json.loads((folder/'prepared.json').read_text())
        with db.connect() as conn:
            members = [conn.execute('SELECT issue_id FROM issues WHERE baseline_scope=? ORDER BY issue_id LIMIT 1', (scope,)).fetchone()['issue_id']
                       for scope in OLD_SCOPES + [NEW_SCOPE]]
        workset = db.create_review_workset(baseline_scopes=OLD_SCOPES + [NEW_SCOPE], issue_ids=members)
        task = db.create_labeling_task(workset_id=workset['id'], assignments=[{'name':'migration_test', 'issue_ids':members}],
            created_by='migration_test', seed=1, reviewers_per_issue=1, overlap_ratio=0)
        label = db.create_label_revision(issue_id=members[-1], task_id=task['id'], expected_output='误触发',
            tags=[], evidence_gaps=[], is_excluded=False, rationale='DISPOSABLE DATABASE TEST ONLY',
            author='migration_test', author_source='test', author_verified=False, expected_previous_revision_id=None)
        assert label['rationale'] == 'DISPOSABLE DATABASE TEST ONLY'
        for scope in OLD_SCOPES + [NEW_SCOPE]:
            assert task['id'] in {item['id'] for item in db.list_labeling_tasks([scope])}
        result['restored_postgres_union_submission_passed'] = True
        result['restore_tables_verified'] = len(receipt['table_fingerprints'])
        save_new(folder/('rehearsal-' + name + '.json'), result)
        print(json.dumps({'rehearsal': 'passed', 'tables': len(receipt['table_fingerprints']),
            'changed_tables': result['changed_tables'], 'total': 2005}), flush=True)
        if db._pool:
            db._pool.close()
        return result
    finally:
        subprocess.run(['sudo', '-u', 'postgres', 'dropdb', '--if-exists', name], check=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--rehearse', type=Path)
    parser.add_argument('--dump', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
    else:
        assert args.rehearse and args.dump
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        rehearse(args.rehearse, args.dump)
