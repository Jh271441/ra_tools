"""Dynamic version selectors retain original source/snapshot ownership."""
import threading
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.gt_sync import TrailGtSyncResult, gt_refresh_due
from ra_triage_dashboard.app.support import gt_sync as service


def test_version_gt_frontend_behavior():
    subprocess.run(['node', str(Path(__file__).with_name('version_gt_ui.cjs'))], check=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(tmp_path / 'db.sqlite3')
    db.init()
    old = 'old-source'
    incremental = 'manual_sidecar_version_20261009'
    db.replace_baseline_scope(scope=old, rows=[dict(issue_id='cn1', gt_label='误触发')], source='test')
    db.replace_baseline_scope(scope=incremental, rows=[dict(issue_id='cn2'), dict(issue_id='cn3')], source='test')
    registry = BaselineRegistry(entries=(BaselineEntry(id='old', label='Old', scope=old,
        loader='capture_workset', xlsx=Path('/unused'), gt_mode='sparse'),))
    settings = SimpleNamespace(gt_sync_baseline_ids=('*',), gt_sync_enabled=True,
        gt_sync_interval_seconds=1800, gt_sync_view_id=1000, gt_sync_chunk_size=100,
        ra_auto_triage_root=tmp_path, data_dir=tmp_path)
    monkeypatch.setattr(service, 'database', db)
    monkeypatch.setattr(service, 'baseline_registry', registry)
    monkeypatch.setattr(service, 'settings', settings)
    monkeypatch.setattr(service, 'runtime_state', {})
    monkeypatch.setattr(service, 'gt_sync_lock', threading.Lock())
    # Only catalog discovery is stubbed; snapshot writes and scope checks are real.
    monkeypatch.setattr(db, 'version_gt_sync_sources', lambda: {'20261009': [old, incremental]})
    calls = []
    def read(**kwargs):
        ids = kwargs['issue_ids']; calls.append(list(ids))
        rows = [dict(issue_id=i, gt_label='正确触发') for i in ids if i != 'cn3']
        return TrailGtSyncResult(rows, len(ids), len(ids), ('ra_merge_result',), 1000, True, 'ok')
    monkeypatch.setattr(service, 'read_trail_gt_labels', read)
    yield db, settings, calls, old, incremental
    db.close()


def test_version_alias_syncs_each_original_source_and_preserves_history(env):
    db, _, calls, old, incremental = env
    assert service.resolve_gt_sync_baseline_ids('version-20261009', strict=True) == ['old', 'version-20261009']
    result = service.sync_authoritative_gt(baseline_ids=['version-20261009'], trigger='test')
    assert result['status'] == 'ready'
    assert calls == [['cn1'], ['cn2', 'cn3']]
    assert result['baseline_sources']['version-20261009'] == ['old', 'version-20261009']
    first = db.get_active_gt_snapshot(incremental)
    assert first['member_count'] == 2 and first['valid_label_count'] == 1
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute('SELECT issue_id,gt_label,baseline_scope FROM issues ORDER BY issue_id')]
    assert [(r['issue_id'], r['gt_label'] or '', r['baseline_scope']) for r in rows] == [
        ('cn1', '正确触发', old), ('cn2', '正确触发', incremental), ('cn3', '', incremental)]
    service.sync_authoritative_gt(trigger='test')  # wildcard scheduled path
    assert db.get_active_gt_snapshot(incremental)['id'] == first['id']
    assert db.gt_sync_status(incremental)['last_check_change_count'] == 0


def test_new_members_require_refresh_even_inside_freshness_interval(env):
    db, _, _, _, scope = env
    service.sync_authoritative_gt(trigger='test')
    assert not gt_refresh_due(service.gt_sync_status(), interval_seconds=1800)
    db.upsert_issues([dict(issue_id='cn4')], baseline_scope=scope, source='test', replace_gt=False)
    status = service.gt_sync_status()
    assert status['status'] == 'not_started'
    assert gt_refresh_due(status, interval_seconds=1800)
    service.sync_authoritative_gt(trigger='test')
    assert db.get_active_gt_snapshot(scope)['member_count'] == 3


def test_partial_trail_response_never_clears_previous_snapshot(env, monkeypatch):
    db, _, _, _, scope = env
    service.sync_authoritative_gt(trigger='test')
    previous = db.get_active_gt_snapshot(scope)['id']
    monkeypatch.setattr(service, 'read_trail_gt_labels', lambda **_: TrailGtSyncResult(
        [], 2, 1, ('ra_merge_result',), 1000, False, 'incomplete'))
    assert service.sync_authoritative_gt(trigger='test')['status'] == 'failed'
    assert db.get_active_gt_snapshot(scope)['id'] == previous
    assert db.gt_sync_overlay(scope)['cn2']['gt_label'] == '正确触发'


def test_explicit_allowlist_and_unknown_sources_fail_closed(env, monkeypatch):
    db, settings, _, old, scope = env
    settings.gt_sync_baseline_ids = ('old',)
    with pytest.raises(ValueError):
        service.resolve_gt_sync_baseline_ids('version-20261009', strict=True)
    settings.gt_sync_baseline_ids = ('*',)
    monkeypatch.setattr(db, 'version_gt_sync_sources', lambda: {'20261009': [old, scope, 'unknown-scope']})
    with pytest.raises(ValueError):
        service.resolve_gt_sync_baseline_ids('version-20261009', strict=True)
    with pytest.raises(ValueError):
        service.resolve_gt_sync_baseline_ids('version-20990101', strict=True)


def test_original_only_version_needs_no_empty_incremental_snapshot(env, monkeypatch):
    db, _, _, old, _ = env
    monkeypatch.setattr(db, 'version_gt_sync_sources', lambda: {'20261009': [old]})
    assert service.resolve_gt_sync_baseline_ids('version-20261009', strict=True) == ['old']
    assert service.sync_authoritative_gt(baseline_ids='version-20261009')['status'] == 'ready'


def test_reserved_lock_released_if_catalog_read_fails(env, monkeypatch):
    service.gt_sync_lock.acquire()
    def fail():
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(service, '_gt_sync_catalog', fail)
    with pytest.raises(RuntimeError):
        service.sync_authoritative_gt(_lock_acquired=True)
    assert not service.gt_sync_lock.locked()


def test_membership_changes_during_read_fail_without_overwrite(env, monkeypatch):
    db, _, _, _, scope = env
    service.sync_authoritative_gt(trigger='test')
    previous = db.get_active_gt_snapshot(scope)['id']
    reader = service.read_trail_gt_labels
    def read(**kwargs):
        result = reader(**kwargs)
        if 'cn2' in kwargs['issue_ids']:
            db.upsert_issues([dict(issue_id='cn4')], baseline_scope=scope, source='test', replace_gt=False)
        return result
    monkeypatch.setattr(service, 'read_trail_gt_labels', read)
    assert service.sync_authoritative_gt(trigger='test')['status'] == 'failed'
    assert db.get_active_gt_snapshot(scope)['id'] == previous
    assert 'cn4' in db.baseline_issue_ids(scope=scope)


def test_source_discovery_is_local_and_retains_original_scopes(tmp_path):
    db = Database(tmp_path / 'db.sqlite3')
    db.init()
    try:
        db.replace_baseline_scope(scope='old', rows=[dict(issue_id='cn1')], source='test')
        db.replace_baseline_scope(scope='manual_sidecar_version_20261009', rows=[dict(issue_id='cn2')], source='test')
        for family, ids in [('20261009', ['cn1', 'cn2', 'cn3']), ('20261016', ['cn4'])]:
            db.ingest_version_dataset(family=family,
                policy=dict(sampling_policy='version_probability_v3', seed='a'*64),
                items=[dict(issue_id=i, software_version='1.gen4-release-'+family+'.1', state='ready') for i in ids],
                batch_key='test', actor='test')
        assert db.version_gt_sync_sources() == {'20261009': ['manual_sidecar_version_20261009', 'old'], '20261016': []}
    finally:
        db.close()
