from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app.models import ReleaseWorkflowState
from app.services import evaluation_samples as samples, evaluation_pipeline as p, metric_profiles as profiles
from app.services import auto_triage_metrics as at, release_workflow as w
from test_auto_triage_metrics import db, prepared, RELEASE, dashboard_receipt
from test_evaluation_pipeline import seed


def offline_bundle(prepared):
    db, snapshot, _, labels = prepared
    scope = at.warehouse.scope_for(snapshot.payload['period'])
    return db, dashboard_receipt(labels, scope), deepcopy(labels)


def test_import_is_idempotent_and_invalid_update_keeps_current_snapshot(prepared):
    db, dashboard, labels = offline_bundle(prepared)
    original = deepcopy((dashboard, labels))
    first = samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'test'})
    assert first['changed'] and first['changes'] == {'added': 7, 'removed': 0, 'updated': 0}
    assert not samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'again'})['changed']
    invalid = deepcopy(dashboard)
    invalid['counts']['auto_precision_denominator'] += 1
    with pytest.raises(ValueError, match='dashboard_count_mismatch'):
        samples.import_snapshot(db, invalid, labels, provenance={'kind': 'invalid'})
    assert samples.selection(db, dashboard['scope'])['snapshot_id'] == first['snapshot_id']
    assert len(samples.records(db, samples.SNAPSHOT)) == 1
    assert (dashboard, labels) == original


def test_scope_update_retains_history_and_reports_row_diff(prepared):
    db, dashboard, labels = offline_bundle(prepared)
    first = samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'test'})
    updated = deepcopy(labels)
    updated.pop('a')
    updated['b']['ra_stuck_auto_result'] = ''
    receipt = dashboard_receipt(updated, dashboard['scope'])
    receipt['observed_at'] = '2026-11-05T03:50:00+00:00'
    second = samples.import_snapshot(db, receipt, updated, provenance={'kind': 'update'})
    assert second['previous_snapshot_id'] == first['snapshot_id']
    assert second['changes'] == {'added': 0, 'removed': 1, 'updated': 1}
    assert len(samples.records(db, samples.SNAPSHOT)) == 2
    with pytest.raises(ValueError, match='sample_import_older'):
        samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'old'})
    assert samples.selection(db, dashboard['scope'])['snapshot_id'] == second['snapshot_id']


def test_subset_filters_use_create_date_and_keep_null_empty_and_eight_memberships(prepared):
    db, dashboard, labels = offline_bundle(prepared)
    labels['a']['ra_stuck_auto_result'] = None
    labels['a']['ra_result'] = None
    labels['b']['ra_stuck_auto_result'] = ''
    dashboard = dashboard_receipt(labels, dashboard['scope'])
    dashboard['rows'][0]['create_date'] = '2026-10-17'
    dashboard['rows'][1]['trip_odd'] = 'ODD1'
    broader = deepcopy(profiles.DEFAULT_FILTERS)
    broader['trip_odd'] = ['ODD1', 'ODD2']
    dashboard['population_filters'] = broader
    samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'test'})
    scope = {**dashboard['scope'], 'date_start': '2026-10-17', 'date_end': '2026-10-17'}
    selected, physical = samples.read(db, scope)
    assert [r['issue_id'] for r in selected['rows']] == ['a']
    assert selected['rows'][0]['merged_ra_auto_result'] is None
    assert set(physical) == {'a'}
    assert all(selected['counts'][k] == selected['rows'][0][k] for k in samples.COUNTS)
    full, _ = samples.read(db, dashboard['scope'], broader)
    assert next(r for r in full['rows'] if r['issue_id'] == 'b')['merged_ra_auto_result'] == ''
    assert next(r for r in full['rows'] if r['issue_id'] == 'b')['auto_precision_denominator'] == 1
    for bad_scope, bad_filters in [({**scope, 'date_start': '2026-10-01'}, broader),
                                   (scope, {**broader, 'trip_odd': ['ODD3']})]:
        with pytest.raises(ValueError, match='sample_snapshot_required'):
            samples.read(db, bad_scope, bad_filters)


def test_snapshot_survives_normal_inventory_updates_but_plan_requires_recalculation(prepared, monkeypatch):
    db, snapshot, batch, labels, revision = seed(prepared, monkeypatch)
    original_batch = deepcopy(batch.payload)
    pointer = samples.selection(db, revision['source']['dashboard']['scope'])
    changed = deepcopy(snapshot.payload)
    changed['issues'][0]['ra_start_timestamp'] += 1
    changed['issues'][1]['evaluation_exclusion'] = {'approved_by': 'user', 'reason': 'review'}
    snapshot.payload = changed
    db.commit()
    assert p.board(db, RELEASE)['stale']
    monkeypatch.setattr(at.warehouse, 'fetch', lambda *a, **k: pytest.fail('No online warehouse'))
    monkeypatch.setattr(at, 'fetch_labels', lambda *a, **k: pytest.fail('No online Trail'))
    recalculated = p.recalculate(db, RELEASE)
    assert recalculated['source']['dashboard']['sample_snapshot_id'] == pointer['snapshot_id']
    assert recalculated['metrics']['counts'] == revision['metrics']['counts']
    assert next(r for r in recalculated['rows'] if r['issue_id'] == 'b')['result_status'] == 'user_exclusion'
    assert batch.payload == original_batch
    assert not p.rows(db, 'evstart:') and not p.rows(db, 'evexecution:')


def test_default_run_preview_publication_and_cron_have_no_upstream_calls(prepared, monkeypatch):
    db, snapshot, batch, labels, revision = seed(prepared, monkeypatch)
    monkeypatch.setattr(at.warehouse, 'fetch', lambda *a, **k: pytest.fail('No online warehouse'))
    monkeypatch.setattr(at, 'fetch_labels', lambda *a, **k: pytest.fail('No online Trail'))
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(p, 'SessionLocal', session)
    request = p.queue(db, RELEASE)
    p.process(request['id'])
    assert w.get_state(db, 'evrequest:' + request['id'])['status'] == 'complete'
    p.set_cron(db, True, release=RELEASE)
    p.tick()
    assert all(r['refresh_labels'] is False and r['source_mode'] == 'database' for r in p.rows(db, 'evrequest:'))
    config = deepcopy(profiles.DEFAULT_CONFIG)
    config['label']['mapping'] = {'正确触发': '成功'}
    draft = profiles.draft(db, config, 'mapped', 'reason')
    preview = p.preview(db, draft['id'], RELEASE)
    assert profiles.publish(db, draft['id'], preview['preview_hash'])['status'] == 'published'
    expanded = deepcopy(config)
    expanded['population']['filters']['trip_odd'].append('ODD3')
    draft = profiles.draft(db, expanded, 'expanded', 'reason')
    with pytest.raises(ValueError, match='sample_snapshot_required'):
        p.preview(db, draft['id'], RELEASE)
    assert p.board(db, RELEASE)['revision']
    assert not p.rows(db, 'evexecution:')


def test_import_invalidates_old_plan_and_profile_preview(prepared, monkeypatch):
    db, _, _, labels, revision = seed(prepared, monkeypatch)
    draft = profiles.draft(db, profiles.DEFAULT_CONFIG, 'draft', 'reason')
    preview = p.preview(db, draft['id'], RELEASE)
    newer = deepcopy(revision['source']['dashboard'])
    newer['observed_at'] = '2026-11-05T03:50:00+00:00'
    samples.import_snapshot(db, newer, revision['source']['labels'], provenance={'kind': 'update'})
    assert p.board(db, RELEASE)['stale']
    with pytest.raises(ValueError, match='plan_stale'):
        profiles.publish(db, draft['id'], preview['preview_hash'])
    with pytest.raises(ValueError, match='plan_stale'):
        p.start(db, p.board(db, RELEASE)['plan']['id'])
    assert not p.rows(db, 'evstart:')


def test_old_online_api_cannot_acquire_or_queue_a_sync(prepared, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.api.evaluation_routes import router
    db, _, _, _, revision = seed(prepared, monkeypatch)
    monkeypatch.setattr(at.warehouse, 'fetch', lambda *a, **k: pytest.fail('No online warehouse'))
    monkeypatch.setattr(at, 'fetch_labels', lambda *a, **k: pytest.fail('No online Trail'))
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    response = client.post('/api/dashboard/evaluation/runs', json={**revision['context'], 'refresh_labels': True})
    assert response.status_code == 409 and response.json()['detail'] == 'offline_sample_update_required'
    assert not p.rows(db, 'evrequest:')
    with pytest.raises(ValueError, match='offline_sample_update_required'):
        at.queue_refresh(db, RELEASE, True)


def test_import_commit_failure_is_atomic(prepared, monkeypatch):
    db, dashboard, labels = offline_bundle(prepared)
    samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'initial'})
    before = samples.records(db, samples.INDEX)
    dashboard['observed_at'] = '2026-11-05T03:50:00+00:00'
    def failed():
        raise RuntimeError('DB unavailable')
    monkeypatch.setattr(db, 'commit', failed)
    with pytest.raises(RuntimeError, match='DB unavailable'):
        samples.import_snapshot(db, dashboard, labels, provenance={'kind': 'failed'})
    assert samples.records(db, samples.INDEX) == before
    assert len(samples.records(db, samples.SNAPSHOT)) == 1
