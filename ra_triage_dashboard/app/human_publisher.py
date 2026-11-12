"""Durable, serialized publication of current formal human conclusions."""
from contextlib import contextmanager
import fcntl
import json
import logging
from pathlib import Path
import re
import stat
from threading import Lock
import time
from uuid import uuid4

from .human_label_policy import FIELDS, VALUES, PRIORITY
from .db_parts.shared import _json, utc_now

logger = logging.getLogger(__name__)
ENDPOINT = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/'
QUERY_ENDPOINT = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/query/'


def qualified_capabilities(path):
    """A deployment receipt, not an API/browser flag, qualifies field semantics."""
    if not path:
        raise ValueError('publication_capabilities_unqualified')
    path = Path(path)
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('publication_capabilities_unqualified')
    data = json.loads(path.read_text())
    if data.get('endpoint') != ENDPOINT or not data.get('evidence') or data.get('qualified') is not True:
        raise ValueError('publication_capabilities_unqualified')
    for field in FIELDS.values():
        contract = data.get('fields', {}).get(field, {})
        if contract.get('null_clear') is not True or contract.get('metric_null_fallback') is not True or set(contract.get('values', [])) != set(VALUES.values()):
            raise ValueError('publication_capabilities_unqualified')
    return data


class _PacedQueryTransport:
    """Pace every actual query page, including pagination inside the SDK."""
    def __init__(self, delegate, pace):
        self.delegate = delegate
        self.pace = pace

    def send_request(self, url, data, timeout=None):
        if url != QUERY_ENDPOINT:
            raise ValueError('Unexpected human publication query endpoint')
        self.pace()
        return self.delegate.send_request(url, data, timeout)


class HumanTrailClient:
    """Use existing application credentials; enforce fixed fields and a shared rate."""
    def __init__(self, root, capabilities, *, interval=1.0):
        from .rd_results import adapter
        self.delegate = adapter(root)
        self.capabilities = capabilities
        self.interval = max(1.0, interval)
        self.last_request = 0.0
        self.pace_lock = Lock()
        self.sdk = self.delegate.client.client
        self.delegate.client = _PacedQueryTransport(self.delegate.client, self._pace)

    def _pace(self):
        with self.pace_lock:
            time.sleep(max(0, self.interval-(time.monotonic()-self.last_request)))
            self.last_request=time.monotonic()

    @staticmethod
    def _validate_ids(ids):
        if (not 1 <= len(ids) <= 20 or any(not isinstance(i, str) or not re.fullmatch(r'cn[0-9]{1,30}', i) for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Invalid publication batch')

    def fetch(self, ids):
        self._validate_ids(ids)
        rows=self.delegate.fetch(ids)
        if len(rows)!=len(ids) or {r.get('issue_id') for r in rows}!=set(ids):
            raise ValueError('Incomplete Trail readback')
        output={}
        for row in rows:
            values={}
            for field in FIELDS.values():
                if field not in row and not self.capabilities['fields'][field].get('absent_means_null'):
                    raise ValueError('Unobserved Trail field')
                value=row.get(field)
                if value is not None and not isinstance(value,str):
                    raise ValueError('Invalid Trail field')
                values[field]=value
            values.update({field:row[field] for field in PRIORITY if field not in values and field in row})
            output[row['issue_id']]=values
        return output

    def update(self, lane, values):
        import requests
        if lane not in FIELDS or not 1 <= len(values) <= 20 or any(v is not None and v not in VALUES.values() for v in values.values()):
            raise ValueError('Invalid publication payload')
        self._validate_ids(list(values))
        self._pace()
        # Bypass RD-only payload adapter, retain its authenticated underlying SDK.
        with requests.Session() as session:
            session.trust_env=False
            response=session.post(ENDPOINT,json=dict(user_location='cn',source_id=1,
                issue_info={iid:{FIELDS[lane]:value} for iid,value in values.items()}),
                headers=self.sdk._post_headers(ENDPOINT),timeout=(10,60),allow_redirects=False)
            response.raise_for_status()


class HumanPublisher:
    def __init__(self, database, directory, client=None, *, enabled=False, batch_size=20):
        self.db=database;self.directory=Path(directory);self.client=client;self.enabled=enabled
        self.batch_size=max(1,min(batch_size,20))

    @contextmanager
    def lock(self):
        # Share the legacy manual writer's lock as well as a cross-host PG lock.
        root=self.directory/'rd_publications';root.mkdir(parents=True,exist_ok=True)
        with (root/'.lock').open('a') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                yield False;return
            try:
                if self.db.backend=='postgresql':
                    with self.db.connect() as conn:
                        acquired=conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('human-label-publisher')) AS acquired").fetchone()['acquired']
                        yield bool(acquired)
                else:yield True
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _row(self,iid,lane):
        with self.db.connect() as conn:
            row=conn.execute('SELECT * FROM human_publications WHERE issue_id=? AND lane=?',(iid,lane)).fetchone()
            return dict(row) if row else None

    def _status(self,row,state,error='',observed=None):
        with self.db._write_lock,self.db.connect() as conn:
            conn.execute('''UPDATE human_publications SET sync_state=?,error_code=?,checked_at=?,
                observed_json=?,attempts=attempts+1,next_attempt=? WHERE issue_id=? AND lane=? AND generation=?''',
                (state,error,utc_now(),_json(observed or {}),time.time()+min(3600,30*2**min(7,int(row['attempts']))),
                 row['issue_id'],row['lane'],row['generation']))

    def _complete_attempt(self,attempt,actual):
        iid=attempt['issue_id'];lane=attempt['lane'];desired=attempt['desired'];field=FIELDS[lane]
        with self.db._write_lock,self.db.connect() as conn:
            row=conn.execute('SELECT * FROM human_publications WHERE issue_id=? AND lane=?',(iid,lane)).fetchone()
            matched=actual[field]==desired
            if matched:
                # Intent establishes the predecessor; a same-value pre-read never does.
                conn.execute('''UPDATE human_publications SET owned=?,owned_value=?,observed_json=?,checked_at=?,
                    published_generation=?,sync_state=CASE WHEN generation=? THEN 'synced' ELSE 'pending' END,
                    error_code='',next_attempt=? WHERE issue_id=? AND lane=?''',
                    (int(desired is not None),desired,_json(actual),utc_now(),attempt['generation'],attempt['generation'],time.time(),iid,lane))
                state='verified'
            else:
                before=json.loads(attempt['before_json'])
                unchanged=actual[field]==before[field]
                state='not_applied' if unchanged else 'external_conflict'
                if row:
                    conn.execute('''UPDATE human_publications SET sync_state=?,error_code=?,observed_json=?,checked_at=?,
                        attempts=attempts+1,next_attempt=? WHERE issue_id=? AND lane=?''',
                        ('retry_wait' if unchanged and row['attempts']<3 else 'needs_recheck',state,_json(actual),utc_now(),
                         time.time()+30*2**min(7,row['attempts']),iid,lane))
            conn.execute('UPDATE human_publication_attempts SET state=?,finished_at=? WHERE id=?',(state,utc_now(),attempt['id']))

    def _recover(self):
        with self.db.connect() as conn:
            pending=[dict(r) for r in conn.execute("SELECT * FROM human_publication_attempts WHERE state IN ('intent','unverified') AND recovery_attempts<5 AND next_attempt<=? ORDER BY created_at LIMIT 20",(time.time(),)).fetchall()]
        if not pending:return True
        try:actual=self.client.fetch(list(dict.fromkeys(r['issue_id'] for r in pending)))
        except Exception:
            with self.db._write_lock,self.db.connect() as conn:
                for row in pending:
                    conn.execute("UPDATE human_publication_attempts SET recovery_attempts=recovery_attempts+1,next_attempt=? WHERE id=?",
                                 (time.time()+min(3600,30*2**row['recovery_attempts']),row['id']))
            for row in pending:
                current=self._row(row['issue_id'],row['lane'])
                if current:self._status(current,'unverified' if row['recovery_attempts']<4 else 'needs_recheck','readback_failed')
            return False
        self.db.refresh_human_publications(issue_ids=list(dict.fromkeys(r['issue_id'] for r in pending)),delay=0)
        for row in pending:self._complete_attempt(row,actual[row['issue_id']])
        return True

    def tick(self, *, force_ids=None):
        self.db.refresh_human_publications(issue_ids=force_ids,delay=0 if force_ids else 10)
        if not self.enabled or self.client is None:return {'state':'disabled'}
        with self.lock() as acquired:
            if not acquired:return {'state':'busy'}
            if not self._recover():return {'state':'unverified'}
            for lane in FIELDS:
                with self.db.connect() as conn:
                    rows=[dict(r) for r in conn.execute('''SELECT * FROM human_publications
                        WHERE lane=? AND sync_state IN ('pending','retry_wait') AND next_attempt<=?
                        AND EXISTS(SELECT 1 FROM human_label_scopes h WHERE h.issue_id=human_publications.issue_id AND h.publication_armed=1)
                        AND NOT EXISTS(SELECT 1 FROM human_publication_attempts a WHERE a.issue_id=human_publications.issue_id
                          AND a.lane=human_publications.lane AND a.state IN ('intent','unverified'))
                        ORDER BY next_attempt,issue_id LIMIT ?''',(lane,time.time(),self.batch_size)).fetchall()]
                if rows:self._batch(lane,rows)
            return {'state':'checked'}

    def _batch(self,lane,rows):
        ids=[r['issue_id'] for r in rows];field=FIELDS[lane]
        try:before=self.client.fetch(ids)
        except Exception:
            for row in rows:self._status(row,'retry_wait' if row['attempts']<3 else 'needs_recheck','pre_read_failed')
            return
        self.db.refresh_human_publications(issue_ids=ids,delay=0)
        intents=[]
        for original in rows:
            row=self._row(original['issue_id'],lane)
            if not row or row['generation']!=original['generation']:continue
            actual=before[row['issue_id']];current=actual[field];desired=row['desired']
            if current==desired:
                self._status(row,'synced' if row['owned'] and row['owned_value']==current else 'same',observed=actual)
                continue
            can_write=(bool(row['owned']) and current==row['owned_value']) or (not row['owned'] and current is None and desired is not None)
            if not can_write:
                self._status(row,'needs_recheck','external_conflict',actual);continue
            attempt=dict(id=uuid4().hex,issue_id=row['issue_id'],lane=lane,generation=row['generation'],
                         desired=desired,before_json=_json(actual))
            with self.db._write_lock,self.db.connect() as conn:
                fresh=conn.execute('SELECT generation FROM human_publications WHERE issue_id=? AND lane=?',(row['issue_id'],lane)).fetchone()
                if not fresh or fresh['generation']!=row['generation']:continue
                conn.execute('''INSERT INTO human_publication_attempts(id,issue_id,lane,generation,action,before_json,desired,state,created_at)
                    VALUES(?,?,?,?,?,?,?,'intent',?)''',(attempt['id'],row['issue_id'],lane,row['generation'],
                    'clear' if desired is None else 'set',attempt['before_json'],desired,utc_now()))
            intents.append(attempt)
        if not intents:return
        try:self.client.update(lane,{r['issue_id']:r['desired'] for r in intents})
        except Exception:pass  # A timeout may have committed; always read back first.
        try:after=self.client.fetch([r['issue_id'] for r in intents])
        except Exception:
            with self.db._write_lock,self.db.connect() as conn:
                for r in intents:
                    conn.execute("UPDATE human_publication_attempts SET state='unverified',error_code='readback_failed' WHERE id=?",(r['id'],))
            for r in intents:
                row=self._row(r['issue_id'],lane);self._status(row,'unverified','readback_failed')
            return
        # Reconcile new submissions made while remote I/O was in flight before marking success.
        self.db.refresh_human_publications(issue_ids=[r['issue_id'] for r in intents],delay=0)
        for r in intents:self._complete_attempt(r,after[r['issue_id']])


async def run_human_publisher(database,settings):
    import asyncio
    client=None
    if settings.human_label_write_enabled:
        try:client=HumanTrailClient(settings.ra_auto_triage_root,qualified_capabilities(settings.human_label_capabilities_file))
        except Exception:logger.error('Human publication disabled: field capabilities are unqualified')
    publisher=HumanPublisher(database,settings.data_dir,client,enabled=client is not None)
    while True:
        task=asyncio.create_task(asyncio.to_thread(publisher.tick))
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            await task;raise
        except Exception:logger.exception('Human publication processing failed')
        await asyncio.sleep(10)
