"""Reconcile the version registry after a scheduler heartbeat, including external GT edits."""
from __future__ import annotations

import asyncio
import logging

from .version_metric_source import read_only_client, source
from .version_metric_store import VersionMetricStore, now

logger = logging.getLogger(__name__)


def scheduled_families(store, datasets, checked):
    """Refresh changed releases and audit one unchanged release on each tick."""
    changed, stable = [], []
    for dataset in datasets:
        family = dataset["release_family"]
        history = store.history(family)
        if not history or history[0].get("registry_revision") != dataset["revision"]:
            changed.append(family)
        else:
            stable.append(family)

    def order(family):
        return (checked.get(family, {}).get("attempted_at", ""), -int(family))
    return sorted(changed, key=order) + sorted(stable, key=order)[:1]


def reconcile(store, db, root):
    tick_file = store.root / "cron.tick"
    try:
        tick = tick_file.stat().st_mtime_ns
    except FileNotFoundError:
        return
    state_file = store.root / "cron-state.json"
    state = store._read(state_file) or {}
    if state.get("tick") == tick:
        return
    checked = state.setdefault("releases", {})
    families = scheduled_families(store, db.list_version_datasets(), checked)
    client = None

    def collect(family):
        nonlocal client
        if client is None:
            client = read_only_client(root)
        return source(db, family, client)

    for family in families:
        try:
            job = store.refresh([family], collect, synchronous=True)
        except ValueError:
            # A manual or other worker owns the lock. Reconsider on the next tick.
            break
        entry = checked.setdefault(family, {})
        entry.update(attempted_at=job["started_at"], status=job["status"])
        if job["status"] == "ready":
            entry["checked_at"] = job["finished_at"]
        store._save(state_file, state)
    state.update(tick=tick, finished_at=now())
    store._save(state_file, state)


async def run_metric_cron(db, settings):
    store = VersionMetricStore(settings.data_dir)
    while True:
        task = asyncio.create_task(asyncio.to_thread(reconcile, store, db, settings.ra_auto_triage_root))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        except Exception:
            logger.exception("Version metric reconciliation failed")
        await asyncio.sleep(15)
