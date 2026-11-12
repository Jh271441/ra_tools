"""Formal role projections, source-bound decisions and durable publication state."""
from contextlib import nullcontext
import json
import time

from .shared import _json, utc_now
from ..human_label_policy import FIELDS, VALUES, digest, resolve_role, effective_metric_label


class DatabaseHumanLabelsMixin:
    def human_label_context(self, issue_id, *, connection=None):
        return self.human_label_contexts([issue_id],connection=connection).get(issue_id)

    def human_label_contexts(self, issue_ids, *, connection=None):
        """Bounded batch projection; no per-case query loop in Gallery/summary paths."""
        output={}
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            for offset in range(0,len(issue_ids),400):
                ids=issue_ids[offset:offset+400]
                if not ids:continue
                marks=','.join('?' for _ in ids)
                scopes=[dict(r) for r in conn.execute(f"""SELECT h.*,c.lifecycle,
                    t.is_target,l.status AS labeling_status FROM human_label_scopes h
                    LEFT JOIN issue_work_splits c ON c.id=h.campaign_id
                    LEFT JOIN version_dataset_items t ON t.dataset_id=h.dataset_id AND t.issue_id=h.issue_id
                    LEFT JOIN labeling_scope_state l ON l.baseline_scope=h.baseline_scope
                    WHERE h.issue_id IN ({marks})""",ids).fetchall()]
                if not scopes:continue
                members={r['issue_id']:[] for r in scopes};heads={i:{} for i in members};decisions={};sync={i:{} for i in members}
                for row in conn.execute(f"""SELECT a.issue_id,lower(a.assignee) AS username,r.role
                    FROM review_work_assignments a JOIN human_label_scopes h ON h.issue_id=a.issue_id AND h.campaign_id=a.split_id
                    LEFT JOIN human_assignment_roles r ON r.campaign_id=a.split_id AND r.issue_id=a.issue_id AND r.username=lower(a.assignee)
                    WHERE h.issue_id IN ({marks}) ORDER BY lower(a.assignee)""",ids).fetchall():
                    members[row['issue_id']].append(dict(username=row['username'],role=row['role'] or 'unknown',required=True))
                for row in conn.execute(f"""SELECT c.issue_id,r.id,lower(r.author) AS author,r.expected_output,r.author_verified,
                    r.label_case_id,v.role,r.created_at,r.rationale FROM label_revisions r
                    JOIN label_cases c ON c.id=r.label_case_id JOIN human_label_scopes h ON h.issue_id=c.issue_id AND h.baseline_scope=c.baseline_scope
                    LEFT JOIN human_vote_roles v ON v.revision_id=r.id WHERE h.issue_id IN ({marks})
                    AND r.revision_kind IN ('submission','legacy')
                    AND NOT EXISTS(SELECT 1 FROM label_import_suppressed_revisions s WHERE s.revision_id=r.id)
                    ORDER BY r.id""",ids).fetchall():
                    heads[row['issue_id']][row['author']]=dict(id=int(row['id']),author=row['author'],label=row['expected_output'],
                        label_case_id=row['label_case_id'],role=row['role'],verified=bool(row['author_verified']),created_at=row['created_at'],rationale=row['rationale'])
                for row in conn.execute(f"""SELECT d.* FROM issue_label_decisions d JOIN human_label_scopes h
                    ON h.issue_id=d.issue_id AND h.baseline_scope=d.baseline_scope WHERE h.issue_id IN ({marks})
                    AND d.id=(SELECT MAX(n.id) FROM issue_label_decisions n WHERE n.issue_id=d.issue_id AND n.baseline_scope=d.baseline_scope)""",ids).fetchall():
                    decisions[row['issue_id']]=dict(row)
                for row in conn.execute(f'SELECT * FROM human_publications WHERE issue_id IN ({marks})',ids).fetchall():
                    if row['issue_id'] in sync:sync[row['issue_id']][row['lane']]=dict(row)
                for scope in scopes:
                    iid=scope['issue_id'];formal=members[iid]
                    lanes={role:resolve_role(formal,list(heads[iid].values()),role) for role in ('rd','te')}
                    lifecycle=scope.pop('lifecycle');target=scope.pop('is_target');labeling=scope.pop('labeling_status')
                    active=bool(scope['active']) and (target is None or bool(target)) and labeling=='active' and lifecycle not in {None,'cancelled','superseded'}
                    if not active:
                        for result in lanes.values():result.update(state='inactive',label=None)
                    if any(m['role']=='unknown' for m in formal):
                        for result in lanes.values():result.update(state='unclassified',label=None)
                    source=dict(campaign_id=scope['campaign_id'],active=active,roles={r:lanes[r]['source'] for r in ('rd','te')})
                    fingerprint=digest(source);decision=decisions.get(iid)
                    arb=dict(state='none',label=None,source={},fingerprint=digest(['no-decision']))
                    if decision:
                        stale=decision['source_fingerprint']!=fingerprint or not active or not decision['created_by_verified']
                        arb=dict(state='stale' if stale else 'resolved',label=None if stale else decision['expected_output'],
                            source=dict(decision_id=decision['id'],actor=decision['created_by'],rationale=decision['rationale'],source_fingerprint=decision['source_fingerprint']),
                            fingerprint=digest([decision['id'],fingerprint]))
                    lanes['arbitrated']=arb
                    output[iid]=dict(issue_id=iid,scope=scope,members=formal,lanes=lanes,source=source,source_fingerprint=fingerprint,sync=sync[iid])
        return output

    @staticmethod
    def _human_dirty(conn, issue_id):
        conn.execute('''INSERT INTO human_label_dirty(issue_id,generation) VALUES(?,1)
            ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1''', (issue_id,))

    def register_human_label_scope(self, *, issue_id, campaign_id, dataset_id, actor, connection=None):
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            member = conn.execute('''SELECT m.baseline_scope FROM campaign_issue_members m
                JOIN issue_work_splits c ON c.id=m.campaign_id
                JOIN version_datasets d ON d.id=? AND d.run_id=c.evaluation_run_id
                WHERE m.campaign_id=? AND m.issue_id=? AND c.workflow_mode='model_review_and_case_label'
                  AND c.lifecycle='active' AND d.release_family>='20261106' ''',
                (dataset_id, campaign_id, issue_id)).fetchone()
            if member is None:
                raise ValueError('正式发布范围无效 / Invalid formal publication scope')
            old = conn.execute('SELECT * FROM human_label_scopes WHERE issue_id=?', (issue_id,)).fetchone()
            if old and (old['campaign_id'] != campaign_id or old['dataset_id'] != dataset_id):
                raise ValueError('已有正式发布任务 / A formal publication task already exists')
            conn.execute('''INSERT INTO human_label_scopes(issue_id,baseline_scope,dataset_id,campaign_id,created_by,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(issue_id) DO NOTHING''',
                (issue_id, member['baseline_scope'], dataset_id, campaign_id, actor, utc_now()))
            self._human_dirty(conn, issue_id)

    def refresh_human_publications(self, *, limit=100, issue_ids=None, delay=10):
        """Consume committed dirty markers. An interrupted refresh remains recoverable."""
        with self._write_lock, self.connect() as conn:
            if issue_ids is None:
                rows = conn.execute('SELECT issue_id,generation FROM human_label_dirty ORDER BY issue_id LIMIT ?', (min(500,limit),)).fetchall()
            else:
                if len(issue_ids)>500:
                    raise ValueError('最多500条 / At most 500 issues')
                rows = [dict(issue_id=iid, generation=None) for iid in dict.fromkeys(issue_ids)]
            if self.backend=='postgresql':
                for iid in sorted({r['issue_id'] for r in rows}):conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))',('human:'+iid,))
            contexts=self.human_label_contexts([r['issue_id'] for r in rows],connection=conn)
            changed=0
            for dirty in rows:
                iid=dirty['issue_id']
                context=contexts.get(iid)
                if context:
                    for lane, result in context['lanes'].items():
                        desired=VALUES.get(result['label']) if result['state']=='resolved' else None
                        fingerprint=digest([result['fingerprint'],result['state'],desired])
                        old=context['sync'].get(lane)
                        if old and old['fingerprint']==fingerprint:
                            # Advisory votes affect the display only, never the publication revision.
                            if old['source_json'] != _json(result):
                                conn.execute('UPDATE human_publications SET source_json=?,objection_count=? WHERE issue_id=? AND lane=?',
                                             (_json(result),len(result.get('objections',[])),iid,lane))
                            continue
                        generation=int(old['generation'])+1 if old else 1
                        state='pending' if desired is not None or (old and old['owned']) else 'not_ready'
                        if old and old['sync_state']=='same' and old['desired'] is not None and desired is None:
                            state='needs_recheck'
                        if old and desired==old['desired'] and old['sync_state'] in {'synced','same','not_ready'}:
                            state=old['sync_state']
                        conn.execute('''INSERT INTO human_publications(issue_id,lane,generation,fingerprint,desired,conclusion,source_json,
                            sync_state,next_attempt,updated_at,objection_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(issue_id,lane) DO UPDATE SET generation=excluded.generation,fingerprint=excluded.fingerprint,
                              desired=excluded.desired,conclusion=excluded.conclusion,source_json=excluded.source_json,
                              sync_state=excluded.sync_state,next_attempt=excluded.next_attempt,attempts=0,error_code='',
                              updated_at=excluded.updated_at,objection_count=excluded.objection_count''',
                            (iid,lane,generation,fingerprint,desired,result['state'],_json(result),state,time.time()+delay,utc_now(),len(result.get('objections',[]))))
                        changed+=1
                if dirty['generation'] is not None:
                    conn.execute('DELETE FROM human_label_dirty WHERE issue_id=? AND generation=?', (iid,dirty['generation']))
            return changed

    def human_publication_rows(self, *, lane='rd', datasets=(), query='', state='all', page=1, page_size=20):
        if lane not in FIELDS or page_size not in {10,20,50,100} or isinstance(page,bool) or int(page)!=page or page<1:
            raise ValueError('分页或发布类型无效 / Invalid pagination or publication lane')
        allowed={'all','resolved','pending','conflict','stale','none','unassigned','inactive','unclassified','objection'}
        if state not in allowed or len(query)>128 or len(datasets)>50:
            raise ValueError('筛选无效 / Invalid filter')
        with self.connect() as conn:
            where=['p.lane=?'];args=[lane]
            if datasets:
                where.append('s.dataset_id IN ('+','.join('?' for _ in datasets)+')');args.extend(datasets)
            if query:
                where.append('s.issue_id LIKE ?');args.append('%'+query.replace('%','').replace('_','')+'%')
            base=' FROM human_label_scopes s JOIN human_publications p ON p.issue_id=s.issue_id WHERE '+' AND '.join(where)
            counts={key:0 for key in allowed if key!='all'}
            for row in conn.execute('SELECT p.conclusion,COUNT(*) AS n'+base+' GROUP BY p.conclusion',args).fetchall():counts[row['conclusion']]=row['n']
            counts['objection']=conn.execute('SELECT COUNT(*) AS n'+base+' AND p.objection_count>0',args).fetchone()['n']
            if state=='objection':base+=' AND p.objection_count>0'
            elif state!='all':base+=' AND p.conclusion=?';args.append(state)
            total=conn.execute('SELECT COUNT(*) AS n'+base,args).fetchone()['n']
            pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
            source_rows=conn.execute('SELECT p.*,s.dataset_id,s.publication_armed'+base+' ORDER BY p.issue_id LIMIT ? OFFSET ?',(*args,page_size,(page-1)*page_size)).fetchall()
            items=[]
            for raw in source_rows:
                row=dict(raw);result=json.loads(row.pop('source_json'));row.pop('owned',None);row.pop('owned_value',None)
                row.update(label=result.get('label'),required=result.get('required',0),submitted=result.get('submitted',0),
                    authors=[v['author'] for v in result.get('source',{}).get('votes',[])],objections=result.get('objections',[]),
                    observed=json.loads(row.pop('observed_json')))
                row['effective_metric']=effective_metric_label(row['observed'])
                items.append(row)
            return dict(items=items,total=total,page=page,page_size=page_size,pages=pages,counts=counts,field=FIELDS[lane])
