"""Revision-aware cache for page reads only; operational decisions stay uncached."""
from collections import OrderedDict
from copy import deepcopy
from contextvars import ContextVar
from datetime import datetime
import os
from pathlib import Path
from threading import RLock
from time import monotonic

from sqlalchemy import select
from app.config import CONFIG_DIR, settings
from app.models import (
    DashboardSnapshot, ReleaseIssueSnapshot, ReleaseSimulationBatch,
    ReleaseWorkflowState,
)
from app.services.release_cycle import TZ

_lock = RLock()
_values = OrderedDict()
_fills = {}
_read_db = ContextVar('read_view_session', default=None)
_MAX_ENTRIES = 96


def _file_revision(path):
    path = Path(path)
    try:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
    except FileNotFoundError:
        return str(path), None


def revision(db):
    # Only identifiers/timestamps cross the DB boundary, never the MB-sized JSON.
    # Read on every request so writes by the worker or another process invalidate
    # immediately. Keep the engine itself in the key to isolate test/other DBs.
    statements = [
        select(ReleaseWorkflowState.key, ReleaseWorkflowState.updated_at).order_by(ReleaseWorkflowState.key),
        select(ReleaseSimulationBatch.fingerprint, ReleaseSimulationBatch.status, ReleaseSimulationBatch.updated_at).order_by(ReleaseSimulationBatch.fingerprint),
        select(ReleaseIssueSnapshot.id, ReleaseIssueSnapshot.period_hash).order_by(ReleaseIssueSnapshot.id),
        select(DashboardSnapshot.id, DashboardSnapshot.config_hash).order_by(DashboardSnapshot.id),
    ]
    return (
        db.get_bind(),
        tuple(tuple(tuple(row) for row in db.execute(stmt)) for stmt in statements),
        tuple(_file_revision(path) for path in [
            settings.versions_config, CONFIG_DIR / 'versions.example.yaml',
            os.getenv('RELEASE_CYCLES_CONFIG', str(CONFIG_DIR / 'release-cycles.default')),
        ]),
        os.getenv('RELEASE_DRIVER_COMMAND_JSON'), os.getenv('RELEASE_WORKFLOW_ENABLED'),
        datetime.now(TZ).date(),
    )


def read_view(db, name, load, *, max_age=300):
    # Never cache uncommitted state or a failed computation. Callers of this
    # helper are GET handlers, not the scheduler, publication, or submit paths.
    if db.new or db.dirty or db.deleted:
        return load()
    token = revision(db)
    key = (token, name)
    # Only requests for the same revision and view share a fill lock. A slow
    # board must not block unrelated pages or cache hits while holding the DB.
    with _lock:
        existing = _values.get(key)
        if existing and monotonic() - existing[0] < max_age:
            _values.move_to_end(key)
            return deepcopy(existing[1])
        fill = _fills.setdefault(key, [RLock(), 0])
        fill[1] += 1
    try:
        with fill[0]:
            with _lock:
                existing = _values.get(key)
                if existing and monotonic() - existing[0] < max_age:
                    _values.move_to_end(key)
                    return deepcopy(existing[1])
            scope = _read_db.set(db)
            try:
                value = load()
            finally:
                _read_db.reset(scope)
            cached = deepcopy(value)
            with _lock:
                _values[key] = (monotonic(), cached)
                _values.move_to_end(key)
                while len(_values) > _MAX_ENTRIES:
                    _values.popitem(last=False)
            return value
    finally:
        with _lock:
            fill[1] -= 1
            if not fill[1]:
                del _fills[key]


def read_projection(db, name, load, *, max_age=300):
    """Reuse public subviews only inside a cached GET, never in worker decisions."""
    active = _read_db.get()
    if active is None or active is not db:
        return load()
    return read_view(db, name, load, max_age=max_age)


def workflow_status(db):
    from app.services.release_workflow import status
    return read_view(db, 'workflow-status', lambda: status(db))


def business_context(db):
    from app.services.release_presentation import context
    return read_view(db, 'business-context', lambda: context(db, workflow_status(db)))


def history_kpis(db):
    from app.services.release_presentation import history_kpis as build
    return read_view(db, 'history-kpis', lambda: build(db))
