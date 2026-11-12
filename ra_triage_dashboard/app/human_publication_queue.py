"""Manual controls enqueue the same durable worker; no remote I/O in HTTP paths."""
import json
import re
import time
from uuid import uuid4

from .db_parts.shared import _json, utc_now
from .human_label_policy import FIELDS
from .human_publisher import qualified_capabilities


def publication_enabled(settings):
    if not getattr(settings,'human_label_write_enabled',False):return False
    try:qualified_capabilities(settings.human_label_capabilities_file)
    except (OSError,ValueError,TypeError,KeyError):return False
    return True


def preview(db, *, lane, issue_ids, datasets, actor):
    if lane not in FIELDS or not 1<=len(issue_ids)<=100 or len(set(issue_ids))!=len(issue_ids) or any(not re.fullmatch(r'cn[0-9]+',i) for i in issue_ids):
        raise ValueError('请选择1到100条不同的Issue / Select 1 to 100 unique Issues')
    db.refresh_human_publications(issue_ids=issue_ids,delay=10)
    with db._write_lock,db.connect() as conn:
        items=[]
        for iid in issue_ids:
            scope=conn.execute('SELECT dataset_id,publication_armed FROM human_label_scopes WHERE issue_id=?',(iid,)).fetchone()
            row=conn.execute('SELECT * FROM human_publications WHERE issue_id=? AND lane=?',(iid,lane)).fetchone()
            if not scope or scope['dataset_id'] not in datasets or not row:
                raise ValueError('Issue不在所选正式任务中 / Issue is outside the selected formal tasks')
            pending=bool(conn.execute("SELECT 1 FROM human_publication_attempts WHERE issue_id=? AND lane=? AND state IN ('intent','unverified')",(iid,lane)).fetchone())
            eligible=bool(scope['publication_armed']) and (row['desired'] is not None or bool(row['owned']) or pending)
            action='blocked' if not scope['publication_armed'] else 'recheck' if pending else 'set' if row['desired'] is not None else 'clear' if row['owned'] else 'blocked'
            items.append(dict(issue_id=iid,lane=lane,generation=row['generation'],fingerprint=row['fingerprint'],
                desired=row['desired'],conclusion=row['conclusion'],action=action,eligible=eligible))
        request=dict(id=uuid4().hex,actor=actor,lane=lane,items=items,state='preview',created_at=utc_now(),expires_at=time.time()+900)
        conn.execute('INSERT INTO human_publication_requests(id,actor,lane,items_json,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
            (request['id'],actor,lane,_json(items),'preview',request['created_at'],request['expires_at']))
        return request


def enqueue(db, *, request_id, actor):
    with db._write_lock,db.connect() as conn:
        row=conn.execute('SELECT * FROM human_publication_requests WHERE id=?',(request_id,)).fetchone()
        if not row or row['actor']!=actor:raise ValueError('预览不存在或不属于当前用户 / Preview unavailable for this user')
        if row['state']=='queued':return dict(id=request_id,state='queued',replayed=True)
        if row['expires_at']<time.time():raise ValueError('预览已过期，请重新预览 / Preview expired; preview again')
        items=json.loads(row['items_json'])
        for item in items:
            current=conn.execute('SELECT generation,fingerprint FROM human_publications WHERE issue_id=? AND lane=?',(item['issue_id'],row['lane'])).fetchone()
            # Recompute from committed votes too: the worker may not yet have consumed dirty work.
            context=db.human_label_context(item['issue_id'],connection=conn)
            from .human_label_policy import digest,VALUES
            result=context['lanes'][row['lane']] if context else {}
            desired=VALUES.get(result.get('label')) if result.get('state')=='resolved' else None
            if not current or current['generation']!=item['generation'] or digest([result.get('fingerprint'),result.get('state'),desired])!=item['fingerprint']:
                raise ValueError('正式结论已变化，请重新预览 / Formal conclusion changed; preview again')
        for item in items:
            if not item['eligible']:continue
            conn.execute("UPDATE human_publications SET sync_state='pending',next_attempt=0,attempts=0,error_code='' WHERE issue_id=? AND lane=?",
                         (item['issue_id'],row['lane']))
            # An ambiguous write must be read back before any subsequent write.
            conn.execute("UPDATE human_publication_attempts SET recovery_attempts=0,next_attempt=0 WHERE issue_id=? AND lane=? AND state IN ('intent','unverified')",
                         (item['issue_id'],row['lane']))
        conn.execute("UPDATE human_publication_requests SET state='queued',committed_at=? WHERE id=?",(utc_now(),request_id))
        return dict(id=request_id,state='queued',queued=sum(i['eligible'] for i in items))
