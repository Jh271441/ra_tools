"""Explicit read-only TE refreshes; local observations never authorize writes."""
from datetime import datetime, timezone
from pathlib import Path

from .trail_import_discovery import TrailImportDiscovery


class TEObservationStore(TrailImportDiscovery):
    """Share durable workers/locks with discovery, retaining every TE observation."""
    def __init__(self, directory, source):
        super().__init__(directory, ['te-correction-v1', source])
        self.root = Path(directory) / 'te_correction_observations'

    @staticmethod
    def _retain_fact(fact):
        return True

    def read(self, baselines, ids, *, refresh=False, read_remote=None):
        members = [{'issue_id': iid} for iid in sorted(set(ids))]
        state = self.read_or_start(scopes=[baselines], members=members,
                                   read_remote=read_remote, refresh=refresh, start_if_missing=False)
        snapshot = state.get('snapshot') or {}
        status = dict(status=state['status'], scanned=state.get('scanned', 0), total=state.get('total', len(ids)),
                      started_at=state.get('started_at'), checked_at=snapshot.get('checked_at'),
                      membership_changed=self.membership_changed(state, members))
        return state, status


def _stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def merge_observations(snapshot, observations, saved, refresh_status):
    """Prefer the newer complete source; never publish partial refresh results."""
    current = {row['issue_id']: dict(row) for row in observations}
    metadata = dict(source_status=snapshot.get('source_status', 'unavailable'),
                    last_success_at=snapshot.get('last_success_at'), refresh=refresh_status)
    complete = saved.get('snapshot') or {}
    if complete and _stamp(complete.get('checked_at')) >= _stamp(snapshot.get('last_success_at')):
        for row in complete['items']:
            current[row['issue_id']] = dict(issue_id=row['issue_id'], **row['remote'])
        metadata.update(source_status='ready', last_success_at=complete['checked_at'])
    return metadata, current
