from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import sleep

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ReleaseWorkflowState, ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import read_views as views


@pytest.fixture
def engine(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'read-cache.db'))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_reads_are_shared_and_do_not_share_mutable_responses(engine):
    calls = []
    def load():
        calls.append(1)
        return {'nested': {'value': 1}, 'refresh_job_ids': [123]}
    with Session(engine) as db:
        first = views.read_view(db, 'test', load)
        first['nested']['value'] = 99
        first.pop('refresh_job_ids')
    with Session(engine) as db:
        assert views.read_view(db, 'test', load) == {'nested': {'value': 1}, 'refresh_job_ids': [123]}
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['settings', 'batch', 'snapshot'])
def test_background_writes_invalidate_immediately(engine, kind):
    calls = []
    def load():
        calls.append(1)
        return len(calls)
    with Session(engine) as db:
        db.add(ReleaseWorkflowState(key='settings', payload={'mode': 'manual'}))
        db.add(ReleaseSimulationBatch(fingerprint='abc', release='release', status='running', payload={}))
        db.commit()
        assert views.read_view(db, kind, load) == 1
    with Session(engine) as writer:
        if kind == 'settings':
            writer.get(ReleaseWorkflowState, 'settings').payload = {'mode': 'auto'}
        elif kind == 'batch':
            batch = writer.get(ReleaseSimulationBatch, 'abc')
            batch.payload = {'summary': {'available': True}}
            batch.status = 'complete'
        else:
            writer.add(ReleaseIssueSnapshot(period_hash='new', release='release', payload={}))
        writer.commit()
    with Session(engine) as db:
        assert views.read_view(db, kind, load) == 2


def test_configuration_change_invalidates_without_waiting(engine, tmp_path, monkeypatch):
    from types import SimpleNamespace
    config = tmp_path / 'versions.yaml'
    config.write_text('versions: {}')
    monkeypatch.setattr(views, 'settings', SimpleNamespace(versions_config=config))
    with Session(engine) as db:
        assert views.read_view(db, 'config', lambda: 'old') == 'old'
        config.write_text('versions: {new: {}}')
        assert views.read_view(db, 'config', lambda: 'new') == 'new'


def test_simultaneous_requests_fill_once(engine):
    calls = []
    lock = Lock()
    def request(_):
        def load():
            with lock:
                calls.append(1)
            sleep(0.02)
            return {'result': 'ready'}
        with Session(engine) as db:
            return views.read_view(db, 'parallel', load)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(request, range(6))) == [{'result': 'ready'}] * 6
    assert len(calls) == 1


def test_slow_view_does_not_block_other_views_or_cached_responses(engine):
    started, release = Event(), Event()
    def read(name, load):
        with Session(engine) as db:
            return views.read_view(db, name, load)
    def slow():
        started.set()
        assert release.wait(5)
        return 'slow-ready'
    assert read('cached', lambda: 'cached-ready') == 'cached-ready'
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = pool.submit(read, 'slow', slow)
        try:
            assert started.wait(2)
            assert pool.submit(read, 'cached', lambda: pytest.fail('cache miss')).result(timeout=2) == 'cached-ready'
            assert pool.submit(read, 'independent', lambda: 'ready').result(timeout=2) == 'ready'
        finally:
            release.set()
        assert pending.result(timeout=2) == 'slow-ready'
    assert not views._fills


def test_expiration_failures_and_database_isolation(engine, monkeypatch):
    monkeypatch.setattr(views, 'monotonic', lambda: 1)
    with Session(engine) as db:
        assert views.read_view(db, 'expiry', lambda: 1, max_age=2) == 1
        monkeypatch.setattr(views, 'monotonic', lambda: 4)
        assert views.read_view(db, 'expiry', lambda: 2, max_age=2) == 2
        with pytest.raises(ValueError):
            views.read_view(db, 'failure', lambda: (_ for _ in ()).throw(ValueError()))
        assert views.read_view(db, 'failure', lambda: 'recovered') == 'recovered'
    other = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(other)
    with Session(other) as db:
        assert views.read_view(db, 'expiry', lambda: 3, max_age=2) == 3
    other.dispose()
