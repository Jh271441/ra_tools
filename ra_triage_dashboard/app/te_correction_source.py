"""Explicit read-only TE refreshes; local observations never authorize writes."""
from datetime import datetime, timezone
from pathlib import Path
import json

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

    def record_readback(self, record, refresh):
        folder = self.root / 'writebacks'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._save(folder / (record['id'] + '.json'), dict(baselines=record['baselines'], **refresh))

    def apply_readbacks(self, baselines, metadata, observations):
        """Fresh per-Issue observations overlay only older complete snapshots."""
        base_stamp = _stamp(metadata.get('last_success_at'))
        latest = {}
        for path in (self.root / 'writebacks').glob('*.json'):
            saved = json.loads(path.read_text())
            if saved['baselines'] != baselines or saved['status'] != 'ready':
                continue
            stamp = saved['checked_at']
            if stamp < base_stamp:
                continue
            for row in saved['items']:
                if stamp >= latest.get(row['issue_id'], (0, None))[0]:
                    value = row['current']
                    latest[row['issue_id']] = (stamp, dict(issue_id=row['issue_id'], te_value=value,
                        te_status='unfilled' if value in (None, '') else 'filled'))
        observations.update({iid:value for iid, (_, value) in latest.items()})
        if latest:
            metadata['last_writeback_at'] = max(stamp for stamp, _ in latest.values())
        return metadata, observations


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
