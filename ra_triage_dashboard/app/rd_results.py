"""Manual RD publication: canonical labels, frozen previews, durable receipts.

This writer owns exactly ra_rd_review_result. It does not use the exclusion
writer, whose operation marker would modify another field.
"""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import BoundedSemaphore, Event, Lock
import time
import uuid

FIELD = "ra_rd_review_result"
VALUES = {"正确触发": "成功", "误触发": "误触发", "无需协助": "无需协助"}
PROTECTED = ("ra_stuck_auto_result", "ra_stuck_auto_result_info", "ra_review_reason", "ra_merge_result")
_preview_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='rd-preview')
_preview_slots = BoundedSemaphore(2)
# Shared across preview jobs so two previews cannot multiply Trail concurrency.
_trail_read_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix='rd-trail-read')
UPLOAD_BATCH_SIZE = 20
UPLOAD_CONCURRENCY = 4
_commit_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rd-commit')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def adapter(root):
    root = str(Path(root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    result = importlib.import_module("tools.daily_auto_triage.rd_review_sync").TrailHTTP()
    result.client = RDTransport(result.client)
    return result


class RDTransport:
    """Reuse application auth, but isolate proxy policy and avoid write retries."""
    def __init__(self, client):
        self.client = client

    def send_request(self, url, data, timeout=None):
        import requests
        from urllib.parse import urlsplit
        target = urlsplit(url)
        if target.hostname != 'voyager.intra.xiaojukeji.com' or target.path not in {
            '/paladin/issue/pool/query/', '/paladin/issue/pool/multi_update/',
        }:
            raise RuntimeError('Unexpected Trail endpoint')
        if target.path.endswith('/multi_update/'):
            url = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/'
            issues = data.get('issue_info') if isinstance(data, dict) else None
            if (not isinstance(issues, dict) or not 1 <= len(issues) <= 100
                    or set(data) != {'user_location', 'source_id', 'issue_info'}
                    or data['user_location'] != 'cn' or data['source_id'] != 1
                    or any(not re.fullmatch(r'cn[0-9]+', iid) or not isinstance(attrs, dict)
                           or set(attrs) != {FIELD} or attrs[FIELD] not in VALUES.values()
                           for iid, attrs in issues.items())):
                raise ValueError('RD 上传字段无效 / Invalid RD upload fields')
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(url, json=data, headers=self.client._post_headers(url),
                                    timeout=(10, 60), allow_redirects=False)
            response.raise_for_status()
            return response

    def _send_request(self, url, json_data, timeout=None):
        return self.send_request(url, json_data, timeout).json()


def read_remote(client, ids, *, progress=None, parallel=False):
    result = {}
    if parallel and len(ids) > 40:
        # TrailHTTP.fetch splits at 40; align to avoid nested serial requests.
        futures = [_trail_read_workers.submit(_read_remote_chunk, client, ids[offset:offset + 40])
                   for offset in range(0, len(ids), 40)]
        try:
            for future in as_completed(futures):
                result.update(future.result())
                if progress:
                    progress(len(result), len(ids))
        finally:
            for future in futures:
                future.cancel()
        # Completion order must not reorder the user's frozen preview.
        return {iid: result[iid] for iid in ids}
    for offset in range(0, len(ids), 100):
        result.update(_read_remote_chunk(client, ids[offset:offset + 100]))
        if progress:
            progress(len(result), len(ids))
    return result


def _read_remote_chunk(client, ids):
    rows = client.fetch(ids)
    if len(rows) != len(ids) or {r.get("issue_id") for r in rows} != set(ids):
        raise ValueError("Trail 返回不完整或重复 / Incomplete or duplicate Trail response")
    # The query contract exposes unset attributes as absent or null. Never
    # coerce unknown/non-string values into an empty, writable field.
    for row in rows:
        if row.get(FIELD) is not None and not isinstance(row[FIELD], str):
            raise ValueError("Trail 字段格式异常 / Invalid Trail field")
    return {r["issue_id"]: {k: r.get(k) for k in (FIELD, *PROTECTED)} for r in rows}


def local_rows(db, ids):
    result = {}
    active = set(db.active_labeling_scopes())
    with db.connect() as conn:
        for offset in range(0, len(ids), 400):
            batch = ids[offset:offset + 400]
            if not batch:
                continue
            rows = conn.execute(f"SELECT issue_id,baseline_scope FROM issues WHERE issue_id IN ({','.join('?' for _ in batch)})", batch).fetchall()
            scopes = {}
            for row in rows:
                if row['baseline_scope'] in active:
                    scopes.setdefault(row['baseline_scope'], []).append(row['issue_id'])
            for scope, members in scopes.items():
                projections = db.project_issue_label_states(scope, members, connection=conn)
                for iid, item in projections.items():
                    revisions = [r for s in item.get('sources', []) for r in s.get('revision_summaries', [])]
                    decision = item.get('decision') or {}
                    result[iid] = dict(issue_id=iid, baseline_scope=scope,
                        state=item['state'], label=item.get('expected_output', ''),
                        fingerprint=digest(item),
                        authors=sorted({r['author'] for r in revisions if r.get('author')} | ({decision['created_by']} if decision.get('created_by') else set())),
                        updated_at=max([str(r.get('created_at') or '') for r in revisions] + [str(decision.get('created_at') or '')]),
                        source_revision_ids=item.get('source_revision_ids', []),
                        decision_id=decision.get('id'))
    return result


def classify(row, remote):
    if row['state'] != 'resolved' or row['label'] not in VALUES:
        return 'blocked'
    current = remote.get(FIELD)
    if current == VALUES[row['label']]:
        return 'same'
    return 'pending' if current in (None, '') else 'conflict'


class PublicationStore:
    def __init__(self, directory):
        self.root = Path(directory) / 'rd_publications'

    @contextmanager
    def lock(self, *, blocking=True):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / '.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def path(self, operation):
        if not re.fullmatch(r'[0-9a-f]{32}', operation):
            raise ValueError('操作编号无效 / Invalid operation ID')
        return self.root / (operation + '.json')

    def save(self, record):
        path = self.path(record['id'])
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix='.receipt-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, operation):
        return json.loads(self.path(operation).read_text())

    def receipt(self, operation):
        """A running receipt without a live lock owner is an interrupted write.

        Never wait for the network writer here: the UI must be able to inspect
        its durable progress while a commit is still running.
        """
        record = self.get(operation)
        if record['state'] == 'preparing':
            with (self.root / (operation + '.preview-lock')).open('a') as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return self.public(record)
                try:
                    record = self.get(operation)
                    if record['state'] == 'preparing':
                        record.update(state='preview_failed', reason='preview_interrupted')
                        self.save(record)
                finally:
                    fcntl.flock(stream, fcntl.LOCK_UN)
            return self.public(record)
        if record['state'] != 'running':
            return self.public(record)
        with (self.root / '.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self.public(record)
            try:
                record = self.get(operation)
                if record['state'] == 'running':
                    record['state'] = 'needs_recheck'
                    record['reason'] = 'interrupted'
                    record['finished_at'] = time.time()
                    record.get('progress', {}).update(stage='stopped')
                    for result in record['results']:
                        if result['state'] == 'intent':
                            result.update(state='unverified', reason='interrupted')
                    for result in record['results']:
                        result.pop('phase', None)
                        if result['state'] == 'not_attempted':
                            result['reason'] = 'batch_stopped'
                    self.save(record)
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
        return self.public(record)

    def start_preview(self, actor, baselines, overwrite, load):
        """Return a durable operation before doing any local/Trail projection.

        Bounded workers never perform writes. The lock also lets another process
        detect an interrupted preview without mistaking it for an empty result.
        """
        if not _preview_slots.acquire(blocking=False):
            raise ValueError('核对任务繁忙，请稍后重试 / Preview workers busy; retry shortly')
        lock = None
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            operation = uuid.uuid4().hex
            lock = (self.root / (operation + '.preview-lock')).open('a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record = dict(id=operation, actor=actor, created_at=time.time(), expires_at=time.time()+600,
                          state='preparing', overwrite=overwrite, baselines=baselines, items=[], results=[],
                          background_preview=True, progress=dict(stage='labels', checked=0, total=0))
            self.save(record)
            def work():
                try:
                    def progress(checked, total):
                        record['progress'] = dict(stage='trail', checked=checked, total=total)
                        self.save(record)
                    rows, remote, scope = load(progress)
                    self.preview(actor, rows, remote, overwrite, baselines, scope=scope, operation=operation)
                except Exception:
                    record.update(state='preview_failed', reason='preview_check_failed')
                    self.save(record)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    lock.close()
                    _preview_slots.release()
            _preview_workers.submit(work)
            return self.public(record)
        except BaseException:
            if lock:
                lock.close()
            _preview_slots.release()
            raise

    def preview(self, actor, rows, remote, overwrite, baselines, *, scope=None, operation=None):
        items = []
        for iid, row in rows.items():
            status = classify(row, remote[iid])
            items.append(dict(**row, status=status, before=remote[iid], desired=VALUES.get(row['label']),
                              eligible=status == 'pending' or (status == 'conflict' and overwrite)))
        record = dict(id=operation or uuid.uuid4().hex, actor=actor, created_at=time.time(),
                      expires_at=time.time() + 600, overwrite=overwrite, baselines=baselines,
                      state='preview', items=items, results=[])
        if scope is not None:
            record['scope'] = scope
        if operation is not None:
            record['background_preview'] = True
        with self.lock():
            self.save(record)
        return self.public(record)

    @staticmethod
    def public(record):
        return {**{k: record[k] for k in ('id', 'actor', 'created_at', 'expires_at', 'state', 'overwrite')},
                'reason': record.get('reason', ''),
                'scope': record.get('scope'),
                'progress': PublicationStore.progress(record),
                'background_preview': record.get('background_preview', False),
                'results': [{k: v for k, v in r.items() if k != 'after'} |
                            ({'observed': r['after'][FIELD]} if 'after' in r else {}) for r in record['results']],
                'items': [{k: v for k, v in row.items() if k not in {'before', 'fingerprint'}} | {'current': row['before'].get(FIELD)} for row in record['items']]}

    @staticmethod
    def progress(record):
        progress = record.get('progress')
        if not progress or 'started_at' not in record:
            return progress
        results = record['results']
        return {**progress,
                'total': len(results),
                'verified': sum(r['state'] == 'verified' for r in results),
                'unverified': sum(r['state'] == 'unverified' for r in results),
                'active': sum(r['state'] == 'intent' or r.get('phase') == 'checking' for r in results),
                'waiting': sum(r['state'] == 'not_attempted' and not r.get('phase') for r in results),
                'elapsed_seconds': round(max(0, record.get('finished_at', time.time()) - record['started_at']), 1)}

    def _claim_commit(self, operation, actor):
        record = self.get(operation)
        if record['actor'] != actor:
            raise ValueError('预览属于另一操作者 / Preview belongs to another actor')
        if record['state'] == 'complete':
            return record
        if record['state'] != 'preview' or time.time() > record['expires_at']:
            raise ValueError('请重新预览并核对结果 / Preview again and check current results')
        record.update(state='running', reason='', started_at=time.time(),
                      progress=dict(stage='preflight', checked=0, check_total=len(record['items']),
                                    batch_size=UPLOAD_BATCH_SIZE, concurrency=UPLOAD_CONCURRENCY))
        record['results'] = [dict(issue_id=r['issue_id'], state='not_attempted', reason='')
                             for r in record['items'] if r['eligible']]
        self.save(record)  # Claim before any network I/O, so GET can report preflight.
        return record

    def start_commit(self, operation, actor, db, client, scope_ids):
        # Acquire before returning 202. No unowned queued writes, and concurrent
        # retries of the same operation can only observe its existing receipt.
        claim = self.lock(blocking=False)
        try:
            claim.__enter__()
        except BlockingIOError:
            record = self.get(operation)
            if record['actor'] != actor:
                raise ValueError('预览属于另一操作者 / Preview belongs to another actor')
            if record['state'] in {'running', 'complete'}:
                return self.public(record)
            raise ValueError('已有上传任务执行中，请稍后再试 / Another upload is running; retry later') from None
        try:
            record = self._claim_commit(operation, actor)
            if record['state'] == 'complete':
                claim.__exit__(None, None, None)
                return self.public(record)
            initial = self.public(record)
            def work():
                try:
                    self._execute_commit(record, db, client, scope_ids)
                except Exception:
                    # Includes unexpected worker/storage failures; leave no
                    # ambiguous intent eligible for replay. GET also recovers
                    # a stale running receipt after a hard process interruption.
                    record.update(state='needs_recheck', reason=record.get('reason') or 'interrupted', finished_at=time.time())
                    record['progress']['stage'] = 'stopped'
                    for result in record['results']:
                        result.pop('phase', None)
                        if result['state'] == 'intent':
                            result.update(state='unverified', reason='interrupted')
                        elif result['state'] == 'not_attempted' and not result['reason']:
                            result['reason'] = 'batch_stopped'
                    self.save(record)
                finally:
                    claim.__exit__(None, None, None)
            _commit_workers.submit(work)
            return initial
        except BaseException:
            claim.__exit__(None, None, None)
            raise

    def commit(self, operation, actor, db, client, scope_ids):
        with self.lock():
            record = self._claim_commit(operation, actor)
            if record['state'] != 'complete':
                self._execute_commit(record, db, client, scope_ids)
            return self.public(record)

    def _execute_commit(self, record, db, client, scope_ids):
        def current_scope():
            return scope_ids() if callable(scope_ids) else scope_ids

        ids = [r['issue_id'] for r in record['items']]
        try:
            if not set(ids).issubset(current_scope()):
                raise ValueError('数据范围已变化 / Dataset membership changed')
            local = local_rows(db, ids)
            def progress(checked, total):
                record['progress'].update(checked=checked, check_total=total)
                self.save(record)
            remote = read_remote(client, ids, parallel=True, progress=progress)
            for row in record['items']:
                iid = row['issue_id']
                if local.get(iid, {}).get('fingerprint') != row['fingerprint'] or remote[iid] != row['before']:
                    raise ValueError('标注或 Trail 已变化，请重新预览 / Labels or Trail changed; preview again')
        except Exception:
            record.update(state='needs_recheck', reason='preflight_failed', finished_at=time.time())
            record['progress']['stage'] = 'stopped'
            for result in record['results']:
                result['reason'] = 'preflight_failed'
            self.save(record)
            raise

        guard, stopped = Lock(), Event()
        results_by_id = {r['issue_id']: r for r in record['results']}
        record['progress']['stage'] = 'uploading'
        self.save(record)
        eligible = [row for row in record['items'] if row['eligible']]
        batches = iter(eligible[offset:offset + UPLOAD_BATCH_SIZE] for offset in range(0, len(eligible), UPLOAD_BATCH_SIZE))

        def batch(rows):
            batch_ids = [row['issue_id'] for row in rows]
            with guard:
                if stopped.is_set():
                    return
                for iid in batch_ids:
                    results_by_id[iid]['phase'] = 'checking'
                self.save(record)
            try:
                live = read_remote(client, batch_ids)
                latest = local_rows(db, batch_ids)
                members = current_scope()
                changed = any(row['issue_id'] not in members or live[row['issue_id']] != row['before']
                              or latest.get(row['issue_id'], {}).get('fingerprint') != row['fingerprint'] for row in rows)
                reason = 'source_changed' if changed else ''
            except Exception:
                reason = 'check_failed'
            with guard:
                if reason or stopped.is_set():
                    if reason:
                        stopped.set()
                    for iid in batch_ids:
                        results_by_id[iid].pop('phase', None)
                        results_by_id[iid]['reason'] = reason or 'batch_stopped'
                    self.save(record)
                    return
                for iid in batch_ids:
                    results_by_id[iid].update(state='intent', phase='uploading')
                # All intents must reach durable storage before this batch POST.
                self.save(record)
            acknowledged = False
            try:
                response = client.update({row['issue_id']: row['desired'] for row in rows})
                acknowledged = isinstance(response, dict) and response.get('code') == 0 and response.get('msg') == 'success'
            except Exception:
                pass  # Never retry writes; lost responses still require readback.
            with guard:
                for iid in batch_ids:
                    results_by_id[iid].update(acknowledged=acknowledged, phase='readback')
                self.save(record)
            try:
                after = read_remote(client, batch_ids)
                outcomes = {}
                for row in rows:
                    iid = row['issue_id']
                    reason = ('protected_changed' if any(after[iid][k] != live[iid][k] for k in PROTECTED)
                              else 'value_mismatch' if after[iid][FIELD] != row['desired'] else '')
                    outcomes[iid] = dict(after=after[iid], state='unverified' if reason else 'verified', reason=reason)
            except Exception:
                outcomes = {iid: dict(state='unverified', reason='readback_failed') for iid in batch_ids}
            with guard:
                if any(result['state'] != 'verified' for result in outcomes.values()):
                    stopped.set()
                for iid, outcome in outcomes.items():
                    results_by_id[iid].update(outcome)
                    results_by_id[iid].pop('phase', None)
                self.save(record)

        # Only keep a bounded window, never enqueue the entire dataset. After
        # failure, drain in-flight writes/readbacks before finalizing receipts.
        with ThreadPoolExecutor(max_workers=UPLOAD_CONCURRENCY, thread_name_prefix='rd-upload') as workers:
            pending = set()
            while True:
                while not stopped.is_set() and len(pending) < UPLOAD_CONCURRENCY:
                    rows = next(batches, None)
                    if rows is None:
                        break
                    pending.add(workers.submit(batch, rows))
                if not pending:
                    break
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        future.result()
                    except Exception:
                        stopped.set()
            # Executor exit waits for any worker that failed outside its I/O guard.
        for result in record['results']:
            result.pop('phase', None)
            if result['state'] == 'intent':
                result.update(state='unverified', reason='interrupted')
            elif result['state'] == 'not_attempted' and not result['reason']:
                result['reason'] = 'batch_stopped'
        record['state'] = 'complete' if all(r['state'] == 'verified' for r in record['results']) else 'needs_recheck'
        record.update(finished_at=time.time())
        record['progress']['stage'] = 'complete' if record['state'] == 'complete' else 'stopped'
        self.save(record)
