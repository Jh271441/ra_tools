from datetime import datetime, timedelta, timezone
from copy import deepcopy

from test_release_workflow import config, db, seed
from app.services import release_workflow as w, release_watch as watch
from app.services.release_inventory import inventory
from app.models import ReleaseSimulationBatch, ReleaseIssueSnapshot
from sqlalchemy import select

NEW = 'gen4-release-20261009'
NOW = datetime.now(timezone.utc)


def observe(db, config, now=NOW):
    rows = [dict(issue_id='cn1', issue_topic='new case', issue_time=int((now-timedelta(hours=1)).timestamp()*1000),
                 version='1.'+NEW+'.600', ra_type=2, ra_merge_result='成功'),
            dict(issue_id='cn2', issue_topic='manual', issue_time=int((now-timedelta(hours=2)).timestamp()*1000),
                 version='1.'+NEW+'.600', ra_type=3, ra_merge_result='成功')]
    watch.monitor_tick(db, config, now=now, activity_fetcher=lambda _: (NEW, rows))
    return rows


def test_stable_default_and_collecting_details_no_simulation(db, config, monkeypatch):
    seed(db, config)
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    rows = observe(db, config)
    value = inventory(db, config, NOW)
    assert value['default_release'] == config['periods'][0]['release']
    new = value['versions'][0]
    assert (new['release'], new['collection_status'], new['issue_count'], new['auto_count'], new['manual_count']) == (NEW, 'collecting', 2, 1, 1)
    assert w.list_issues(db, '@stable')['items'][0]['issue_id'] == 'i1'
    current = w.list_issues(db, NEW)
    assert current['total'] == 2
    assert all(i['sim_triggered'] is None and i['simulation_status'] == 'collecting' for i in current['items'])
    assert w.list_issues(db, NEW, query='manual')['total'] == 1
    assert w.list_issues(db, NEW, page_size=1, page=2)['items'][0]['issue_id'] == 'cn2'
    assert w.list_issues(db, NEW, label='fabricated')['total'] == 0
    assert db.scalars(select(ReleaseSimulationBatch)).all() == []
    assert len(db.scalars(select(ReleaseIssueSnapshot)).all()) == 1


def test_failed_observation_retains_rows_but_not_eligible(db, config, monkeypatch):
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    observe(db, config)
    def fail(_):
        raise RuntimeError('source unavailable')
    watch.monitor_tick(db, config, now=NOW+timedelta(minutes=15), activity_fetcher=fail)
    item = inventory(db, config, NOW+timedelta(minutes=15))['versions'][0]
    assert item['stale'] and item['eligible_at'] is None
    assert w.list_issues(db, NEW)['total'] == 2
    assert inventory(db, config, NOW)['default_release'] is None


def test_stable_only_after_full_day_and_not_after_gap(db, config):
    rows = observe(db, config)
    for step in range(1, 97):
        watch.monitor_tick(db, config, now=NOW+timedelta(minutes=15*step), activity_fetcher=lambda _: (NEW, rows))
    value = inventory(db, config, NOW+timedelta(days=1))
    assert value['default_release'] == NEW
    assert value['versions'][0]['collection_status'] == 'stable'
    value = inventory(db, config, NOW+timedelta(days=1, hours=4))
    assert value['default_release'] is None
    assert value['versions'][0]['stale']


def test_missing_or_partial_snapshots_not_default(db, config, monkeypatch):
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    assert inventory(db, config)['default_release'] is None
    assert w.list_issues(db, '@stable')['items'] == []
    seed(db, config)
    snap = db.scalars(select(ReleaseIssueSnapshot)).one()
    snap.payload = {**snap.payload, 'population_complete': False}
    db.commit()
    assert inventory(db, config)['default_release'] is None


def test_same_count_replacement_visible_keeps_last_issue_age(db, config, monkeypatch):
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    rows = observe(db, config)
    changed = deepcopy(rows)
    changed[0]['issue_id'] = 'cn3'
    watch.monitor_tick(db, config, now=NOW+timedelta(minutes=15), activity_fetcher=lambda _: (NEW, changed))
    assert {i['issue_id'] for i in w.list_issues(db, NEW)['items']} == {'cn2', 'cn3'}
    assert w.get_state(db, 'release_monitor')['quiet_seconds'] == 4500


def test_previous_observer_remains_in_inventory_and_issue_browser(db, config, monkeypatch):
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    rows = observe(db, config)
    newer = 'gen4-release-20261016'
    watch.monitor_tick(db, config, now=NOW+timedelta(minutes=15),
                       activity_fetcher=lambda _: (newer, [{**rows[0], 'version': '1.'+newer+'.610'}]))
    versions = {v['release']: v for v in inventory(db, config, NOW+timedelta(minutes=15))['versions']}
    assert NEW in versions and newer in versions
    assert versions[NEW]['issue_count'] == 2
    assert w.list_issues(db, NEW)['total'] == 2
