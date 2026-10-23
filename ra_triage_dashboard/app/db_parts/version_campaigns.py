"""Authorized physical consolidation and direct append for version review tasks.

Ordinary Campaigns/worksets remain frozen. The explicit version_live exception
archives original task records, pins each original reference value, and changes
only ownership bindings. All ordinary label/review identities remain intact.
"""
from collections import Counter, defaultdict
import hashlib
import json
import re
import uuid
from .shared import utc_now, _json, _json_load


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def insert(conn, table, row):
    assert re.fullmatch('[a-z_]+',table) and all(re.fullmatch('[a-z_][a-z0-9_]*',k) for k in row)
    keys=list(row)
    values=[_json(v) if isinstance(v,(dict,list)) else v for v in row.values()]
    conn.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', values)


class VersionCampaignsMixin:
    def _version_event(self,conn,did,key,action,detail,actor):
        eid=str(uuid.uuid5(uuid.NAMESPACE_URL,'version-task:'+did+':'+action+':'+key))
        conn.execute('INSERT INTO dataset_audit_events(id,dataset_id,batch_key,issue_id,action,detail_json,actor,created_at) VALUES(?,?,?,\'\',?,?,?,?) ON CONFLICT(id) DO NOTHING',
                     (eid,did,key,action,json.dumps(detail,ensure_ascii=False,default=str),actor,utc_now()))

    def _version_registration(self,conn,did):
        row=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND action='version_task_registered' ORDER BY created_at LIMIT 1",(did,)).fetchone()
        return _json_load(row['detail_json'],{}) if row else {}

    def version_campaign_dataset(self,campaign_id):
        with self.connect() as conn:
            cid=self._resolve_version_campaign(conn,campaign_id)
            row=conn.execute('SELECT filter_json FROM issue_work_splits WHERE id=?',(cid,)).fetchone()
            return _json_load(row['filter_json'],{}).get('version_dataset_id','') if row else ''

    def version_campaign_id(self,dataset_id):
        with self.connect() as conn:return self._version_registration(conn,dataset_id).get('campaign_id','')

    def _resolve_version_campaign(self,conn,campaign_id):
        value=str(campaign_id or '')
        if value.startswith('version:'):
            return self._version_registration(conn,value[8:]).get('campaign_id') or value
        if not value or conn.execute('SELECT 1 FROM issue_work_splits WHERE id=?',(value,)).fetchone():return value
        row=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE batch_key=? AND action='version_task_archived' LIMIT 1",('campaign:'+value,)).fetchone()
        return _json_load(row['detail_json'],{}).get('canonical_id',value) if row else value

    def resolve_version_campaign(self,campaign_id):
        with self.connect() as conn:return self._resolve_version_campaign(conn,campaign_id)

    def _version_reference_id(self,conn,campaign_id,issue_id,reference_id):
        campaign=conn.execute('SELECT filter_json,reference_id FROM issue_work_splits WHERE id=?',(campaign_id,)).fetchone()
        if not campaign or not _json_load(campaign['filter_json'],{}).get('version_live'):return reference_id
        if not reference_id or reference_id==campaign['reference_id']:return campaign['reference_id']
        did=_json_load(campaign['filter_json'],{}).get('version_dataset_id')
        for row in conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND action='version_task_archived'",(did,)).fetchall():
            original=_json_load(row['detail_json'],{})
            if original.get('campaign',{}).get('reference_id')==reference_id and issue_id in original.get('issue_ids',[]):return campaign['reference_id']
        return reference_id

    def _version_workset(self,conn,dataset,campaign_id,members,actor):
        ordered=[m['issue_id'] for m in members];scopes=sorted({m['baseline_scope'] for m in members})
        sha=hashlib.sha256('\n'.join(ordered).encode()).hexdigest()
        wid='workset-version-'+dataset['release_family']+'-'+sha[:24]
        if conn.execute('SELECT 1 FROM review_worksets WHERE id=?',(wid,)).fetchone():return wid
        insert(conn,'review_worksets',dict(id=wid,baseline_scope=scopes[0] if len(scopes)==1 else '',name=dataset['release_family'][4:]+' version review',selection_source_run_id=dataset['run_id'],source_filter_json=_json({'version_dataset_id':dataset['id']}),member_count=len(ordered),members_sha256=sha,created_by=actor,created_by_source='version_task_service',created_by_verified=False,created_at=utc_now(),scope_mode='single' if len(scopes)==1 else 'multi',scope_count=len(scopes),scopes_sha256=digest(scopes),selection_metadata_json=_json({'kind':'version_live_revision','dataset_id':dataset['id']})))
        for n,m in enumerate(members,1):insert(conn,'review_workset_items',dict(workset_id=wid,issue_id=m['issue_id'],ordinal=n))
        for n,scope in enumerate(scopes,1):
            ids=[m['issue_id'] for m in members if m['baseline_scope']==scope]
            insert(conn,'review_workset_scopes',dict(workset_id=wid,baseline_scope=scope,ordinal=n,member_count=len(ids),members_sha256=hashlib.sha256('\n'.join(ids).encode()).hexdigest()))
        return wid

    def _version_archive_guards(self,conn,restore=None):
        # Only the explicit, backup-bound physical migration calls this helper.
        # PostgreSQL DDL is transactional and takes table locks. Any exception
        # rolls back ownership changes AND guard state; ordinary append never disables guards.
        tables=['campaign_config_revisions','campaign_config_members','campaign_assignment_audit','campaign_lifecycle_audit']
        if self.backend=='postgresql':
            for table in tables:
                trigger='trg_'+table+'_immutable'
                record=conn.execute('SELECT tgenabled FROM pg_trigger WHERE tgrelid=?::regclass AND tgname=?',(table,trigger)).fetchone()
                if not record or record['tgenabled']!=('D' if restore else 'O'):raise ValueError('Unexpected immutable guard state')
            for table in tables:conn.execute('ALTER TABLE '+table+' '+('ENABLE' if restore else 'DISABLE')+' TRIGGER trg_'+table+'_immutable')
            return True
        if restore is not None:
            for sql in restore:conn.execute(sql)
            return
        rows=conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN (?,?,?,?)",tables).fetchall()
        guards=[r for r in rows if ('BEFORE UPDATE' in r['sql'].upper() or 'BEFORE DELETE' in r['sql'].upper()) and 'RAISE' in r['sql'].upper()]
        for row in guards:conn.execute('DROP TRIGGER '+row['name'])
        return [r['sql'] for r in guards]

    def _version_union_reference(self,conn,wid,scope,case_references,actor):
        """Copy frozen source rows, never reproject historical human labels."""
        items=[];sources=[]
        for n,(iid,ref) in enumerate(case_references,1):
            if ref.get('reference_type')!='label_result_snapshot':raise ValueError('Version merge requires audited Label snapshot references')
            old=conn.execute('SELECT * FROM label_result_snapshot_items WHERE snapshot_id=? AND issue_id=?',(ref['reference_id'],iid)).fetchone()
            if old is None:raise ValueError('Original frozen reference lacks Issue')
            item=dict(old);item['ordinal']=n;items.append(item)
            sources.extend(dict(r) for r in conn.execute('SELECT * FROM label_result_snapshot_sources WHERE snapshot_id=? AND issue_id=? ORDER BY source_key',(ref['reference_id'],iid)).fetchall())
        body={'contract':'version-reference-union-v1','workset':wid,'scope':scope,'items':[{k:v for k,v in r.items() if k!='snapshot_id'} for r in items],'sources':[{k:v for k,v in r.items() if k not in {'id','snapshot_id'}} for r in sources]}
        sha=digest(body);sid='label-result-'+sha
        if not conn.execute('SELECT 1 FROM label_result_snapshots WHERE id=?',(sid,)).fetchone():
            counts=Counter(r['state'] for r in items);count=len(items)
            insert(conn,'label_result_snapshots',dict(id=sid,baseline_scope=scope,workset_id=wid,workset_members_sha256=hashlib.sha256('\n'.join(r['issue_id'] for r in items).encode()).hexdigest(),content_sha256=sha,member_count=count,resolved_count=counts['resolved'],pending_count=counts['pending'],conflict_count=counts['conflict'],stale_count=counts['stale'],unknown_count=counts['none'],coverage_status='complete' if counts['resolved']==count else 'partial',created_by=actor,created_by_source='version_reference_union',created_by_verified=False,created_at=utc_now()))
            for item in items:item['snapshot_id']=sid;insert(conn,'label_result_snapshot_items',item)
            for source in sources:source.pop('id');source['snapshot_id']=sid;insert(conn,'label_result_snapshot_sources',source)
        return dict(baseline_scope=scope,reference_type='label_result_snapshot',reference_id=sid,reference_sha256=sha)

    def consolidate_version_campaigns(self, *, dataset_id,backup_sha256,actor):
        if not re.fullmatch('[a-f0-9]{64}',backup_sha256) or not actor:raise ValueError('Verified backup and migration actor required')
        with self._write_lock,self.connect() as conn:
            if self.backend=='sqlite':conn.execute('BEGIN IMMEDIATE')
            if self.backend=='postgresql':conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(dataset_id,))
            dataset=conn.execute('SELECT * FROM version_datasets WHERE id=?',(dataset_id,)).fetchone()
            if not dataset:raise ValueError('Unknown version dataset')
            registered=self._version_registration(conn,dataset_id)
            campaigns=[dict(r) for r in conn.execute("SELECT * FROM issue_work_splits WHERE evaluation_run_id=? AND purpose='model_review' ORDER BY created_at,id",(dataset['run_id'],)).fetchall()]
            if registered:
                if len(campaigns)!=1 or campaigns[0]['id']!=registered['campaign_id']:raise ValueError('Unexpected new source Campaign after consolidation')
                return dict(registered,replayed=True)
            if not campaigns:raise ValueError('No source Campaigns to consolidate')
            if any(c['workflow_mode']!='model_review_and_case_label' or c['lifecycle']!='active' or c.get('task_group_id') for c in campaigns):raise ValueError('Source Campaign has unsupported lifecycle/group/workflow')
            guards=self._version_archive_guards(conn)
            root=campaigns[0]['id'];ids=[c['id'] for c in campaigns];marks=','.join('?' for _ in ids)
            for table in ['campaign_close_snapshots','review_task_group_campaigns']:
                if conn.execute('SELECT COUNT(*) AS n FROM '+table+' WHERE campaign_id IN ('+marks+')',ids).fetchone()['n']:raise ValueError('Closed/grouped Campaign requires separate migration')
            members=[dict(r) for r in conn.execute('SELECT * FROM campaign_issue_members WHERE campaign_id IN ('+marks+') ORDER BY campaign_id,ordinal',ids).fetchall()]
            if len({r['issue_id'] for r in members})!=len(members):raise ValueError('Duplicate original membership requires explicit conflict resolution')
            assignments=[dict(r) for r in conn.execute('SELECT * FROM review_work_assignments WHERE split_id IN ('+marks+')',ids).fetchall()]
            if len({r['issue_id'] for r in assignments})!=len(assignments):raise ValueError('Original assignments overlap')
            refs={(r['campaign_id'],r['baseline_scope']):dict(r) for r in conn.execute('SELECT * FROM campaign_reference_items WHERE campaign_id IN ('+marks+')',ids).fetchall()}
            source_tables=['campaign_config_revisions','campaign_config_members','campaign_reference_items','campaign_assignment_audit','campaign_lifecycle_audit','campaign_migration_map','campaign_issue_members','combined_review_progress']
            archives={}
            for campaign in campaigns:
                cid=campaign['id'];archive=dict(canonical_id=root,campaign=campaign,issue_ids=[m['issue_id'] for m in members if m['campaign_id']==cid],backup_sha256=backup_sha256,tables={})
                for table in source_tables:archive['tables'][table]=[dict(r) for r in conn.execute('SELECT * FROM '+table+' WHERE campaign_id=?',(cid,)).fetchall()]
                archive['tables']['review_work_assignments']=[a for a in assignments if a['split_id']==cid]
                self._version_event(conn,dataset_id,'campaign:'+cid,'version_task_archived',archive,actor);archives[cid]=archive
            # Rebind every mutable ownership pointer, preserving IDs/authors/times/data.
            namespace=digest({'contract':'version-task-reference-v1','dataset_id':dataset_id})
            for table,column in [('model_review_revisions','campaign_id'),('model_review_heads','campaign_id'),('combined_review_submissions','campaign_id'),('combined_review_progress','campaign_id'),('review_comments','campaign_id'),('review_work_assignment_changes','split_id'),('review_work_assignments','split_id'),('issue_work_assignments','split_id'),('annotations','work_split_id'),('label_cases','task_id'),('label_comment_links','task_id')]:
                conn.execute('UPDATE '+table+' SET '+column+'=? WHERE '+column+' IN ('+marks+')',[root,*ids])
            conn.execute('UPDATE model_review_revisions SET work_split_id=? WHERE work_split_id IN ('+marks+')',[root,*ids])
            for table in ['model_review_revisions','model_review_heads']:
                conn.execute('UPDATE '+table+' SET reference_id=? WHERE campaign_id=?',(namespace,root))
            # Historical configuration revisions are moved into one revision sequence.
            revisions=[]
            for cid in ids:
                for record in archives[cid]['tables']['campaign_config_revisions']:revisions.append((cid,record))
            revisions.sort(key=lambda p:(str(p[1]['changed_at']),p[0],p[1]['revision_no']))
            revision_map={(cid,r['revision_no']):n for n,(cid,r) in enumerate(revisions,1)}
            conn.execute('DELETE FROM campaign_config_members WHERE campaign_id IN ('+marks+')',ids)
            conn.execute('DELETE FROM campaign_config_revisions WHERE campaign_id IN ('+marks+')',ids)
            for cid,record in revisions:
                record=dict(record);record.update(campaign_id=root,revision_no=revision_map[cid,record['revision_no']]);insert(conn,'campaign_config_revisions',record)
            for cid in ids:
                for record in archives[cid]['tables']['campaign_config_members']:
                    record=dict(record);record.update(campaign_id=root,revision_no=revision_map[cid,record['revision_no']]);insert(conn,'campaign_config_members',record)
                for table in ['campaign_assignment_audit','campaign_lifecycle_audit']:
                    for record in archives[cid]['tables'][table]:
                        conn.execute('UPDATE '+table+' SET campaign_id=?,config_revision=? WHERE id=?',(root,revision_map[cid,record['config_revision']],record['id']))
            conn.execute('UPDATE campaign_migration_map SET campaign_id=? WHERE campaign_id IN ('+marks+')',[root,*ids])
            members.sort(key=lambda m:m['issue_id']);revision=len(revisions)+1
            conn.execute('DELETE FROM campaign_issue_members WHERE campaign_id IN ('+marks+')',ids)
            for n,member in enumerate(members,1):
                member=dict(member);member.update(campaign_id=root,ordinal=n,config_revision=revision);insert(conn,'campaign_issue_members',member)
            wid=self._version_workset(conn,dict(dataset),root,members,actor)
            by_scope=defaultdict(list)
            for member in members:by_scope[member['baseline_scope']].append((member['issue_id'],refs[(member['campaign_id'],member['baseline_scope'])]))
            unions=[self._version_union_reference(conn,wid,scope,rows,actor) for scope,rows in sorted(by_scope.items())]
            conn.execute('DELETE FROM campaign_reference_items WHERE campaign_id IN ('+marks+')',ids)
            for ref in unions:insert(conn,'campaign_reference_items',dict(campaign_id=root,**ref,created_at=utc_now()))
            conn.execute('UPDATE issue_work_splits SET workset_id=?,reference_type=\'reference_set\',reference_id=?,reference_sha256=?,campaign_name=?,filter_json=?,config_revision=?,total_count=?,assignment_count=?,updated_by=?,updated_at=? WHERE id=?',
                         (wid,namespace,namespace,dataset['release_family'][4:]+' · 版本联合复核',_json({'version_live':True,'version_dataset_id':dataset_id}),revision,len(members),len(assignments),actor,utc_now(),root))
            self._campaign_refresh_compat_assignment_snapshot(conn,root)
            self._campaign_insert_revision(conn,campaign_id=root,revision_no=revision,changed_by=actor,changed_by_source='authorized_migration',changed_by_verified=False,change_source='migration')
            # Sources stay in immutable manifests/archive events, active bindings move.
            conn.execute('UPDATE dataset_task_bindings SET campaign_id=? WHERE dataset_id=?',(root,dataset_id))
            for item in conn.execute('SELECT issue_id,binding_json FROM version_dataset_items WHERE dataset_id=?',(dataset_id,)).fetchall():
                binding=_json_load(item['binding_json'],{})
                if binding.get('campaign_id') in ids:binding['campaign_id']=root;conn.execute('UPDATE version_dataset_items SET binding_json=? WHERE dataset_id=? AND issue_id=?',(_json(binding),dataset_id,item['issue_id']))
            for cid in ids:
                if cid!=root:conn.execute('DELETE FROM issue_work_splits WHERE id=?',(cid,))
            receipt=dict(campaign_id=root,dataset_id=dataset_id,source_count=len(ids),archived_ids=[i for i in ids if i!=root],member_count=len(members),assignment_count=len(assignments),backup_sha256=backup_sha256,reference_namespace=namespace,contract='version_campaign_physical_v1')
            self._version_event(conn,dataset_id,'canonical','version_task_registered',receipt,actor)
            self._mark_labeling_change(conn);self._mark_run_collection_change(conn)
            self._version_archive_guards(conn,restore=guards)
            return receipt

    def _version_fresh_reference(self,conn,dataset,members,scope,actor):
        wid=self._version_workset(conn,dataset,'',members,actor)
        ids=[m['issue_id'] for m in members]
        projected=self.project_issue_label_states(scope,ids,include_sources=True,connection=conn)
        rows=[];source_rows=[]
        for n,iid in enumerate(ids,1):
            value=projected.get(iid) or {};decision=value.get('decision') or {}
            rows.append(dict(snapshot_id='',baseline_scope=scope,issue_id=iid,ordinal=n,state=value.get('state') or 'none',expected_output=value.get('expected_output') or None,method=value.get('method') or 'single',gt_relation=value.get('gt_relation') or 'unknown',decision_id=decision.get('id') if not decision.get('stale') else None))
            provenance=self._label_result_snapshot_provenance(value.get('sources') or [])
            source_rows.extend(dict(zip(['snapshot_id','issue_id','label_case_id','task_id','resolution_id','revision_id','source_role','source_key'],r)) for r in self._label_result_snapshot_source_rows('',iid,provenance))
        sha=digest({'contract':'version-admission-reference-v1','scope':scope,'members':ids,'items':rows,'sources':source_rows});sid='label-result-'+sha
        if not conn.execute('SELECT 1 FROM label_result_snapshots WHERE id=?',(sid,)).fetchone():
            counts=Counter(r['state'] for r in rows)
            insert(conn,'label_result_snapshots',dict(id=sid,baseline_scope=scope,workset_id=wid,workset_members_sha256=hashlib.sha256('\n'.join(ids).encode()).hexdigest(),content_sha256=sha,member_count=len(rows),resolved_count=counts['resolved'],pending_count=counts['pending'],conflict_count=counts['conflict'],stale_count=counts['stale'],unknown_count=counts['none'],coverage_status='complete' if counts['resolved']==len(rows) else 'partial',created_by=actor,created_by_source='version_task_service',created_by_verified=False,created_at=utc_now()))
            for row in rows:row['snapshot_id']=sid;insert(conn,'label_result_snapshot_items',row)
            for row in source_rows:row['snapshot_id']=sid;insert(conn,'label_result_snapshot_sources',row)
        return dict(baseline_scope=scope,reference_type='label_result_snapshot',reference_id=sid,reference_sha256=sha)

    def append_version_campaign_members(self, *, family,policy,issue_ids,current_target_ids,batch_key,actor):
        """Append directly to the same physical task; never allocate another batch Campaign."""
        did='release-'+family+'-odd2'
        if not re.fullmatch(r'20\d{6}',family) or not actor or len(set(issue_ids))!=len(issue_ids):raise ValueError('Invalid version append identity')
        expected=digest({'family':family,'issue_ids':sorted(issue_ids),'policy':policy})
        with self._write_lock,self.connect() as conn:
            if self.backend=='postgresql':conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(did,))
            dataset=conn.execute('SELECT * FROM version_datasets WHERE id=?',(did,)).fetchone()
            rid=str(uuid.uuid5(uuid.NAMESPACE_URL,'ra-triage:'+did))
            if not conn.execute("SELECT 1 FROM model_runs WHERE id=? AND kind='version_live'",(rid,)).fetchone():raise ValueError('Version Run not registered')
            if not dataset:
                now=utc_now();insert(conn,'version_datasets',dict(id=did,name=family[4:]+' 复核集',release_family=family,policy_json=_json(policy),revision=0,run_id=rid,created_at=now,updated_at=now))
                dataset=conn.execute('SELECT * FROM version_datasets WHERE id=?',(did,)).fetchone()
            if _json_load(dataset['policy_json'],{})!=policy:raise ValueError('Frozen version policy mismatch')
            registered=self._version_registration(conn,did)
            if not registered:
                if conn.execute('SELECT 1 FROM issue_work_splits WHERE evaluation_run_id=?',(rid,)).fetchone():raise ValueError('Existing batches require the authorized physical migration')
                if not issue_ids:return dict(campaign_id='',added=0,bindings={})
                root='campaign-version-'+family+'-odd2';namespace=digest({'contract':'version-task-reference-v1','dataset_id':did});now=utc_now()
                insert(conn,'issue_work_splits',dict(id=root,created_by=actor,created_at=now,seed=20261020,total_count=0,filter_json=_json({'version_live':True,'version_dataset_id':did}),assignees_json='[]',overlap_ratio=0,purpose='model_review',evaluation_run_id=rid,model_run_id=rid,reference_type='reference_set',reference_id=namespace,reference_sha256=namespace,lifecycle='active',config_revision=1,campaign_name=family[4:]+' · 版本联合复核',task_kind='model_review',mode='single',reviewers_per_issue=1,assignment_count=0,workset_id='',selection_source_run_id=rid,workflow_mode='model_review_and_case_label',updated_by=actor,updated_at=now))
                registered=dict(campaign_id=root,dataset_id=did,source_count=0,archived_ids=[],contract='version_campaign_physical_v1')
                self._version_event(conn,did,'canonical','version_task_registered',registered,actor)
            root=registered['campaign_id']
            campaign=conn.execute('SELECT * FROM issue_work_splits WHERE id=?'+(' FOR UPDATE' if self.backend=='postgresql' else ''),(root,)).fetchone()
            if not campaign or campaign['lifecycle']!='active':raise ValueError('Version task is not active')
            replay=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND batch_key=? AND action='version_task_append'",(did,batch_key)).fetchone()
            if replay:
                receipt=_json_load(replay['detail_json'],{})
                if receipt['fingerprint']!=expected:raise ValueError('Version append idempotency conflict')
            assigned={r['issue_id']:dict(r) for r in conn.execute('SELECT * FROM review_work_assignments WHERE split_id=?',(root,)).fetchall()}
            new=sorted(set(issue_ids)-set(assigned))
            if new:
                people=('jasperchen','liangxianghui')
                roles={r['username']:r['role'] for r in conn.execute('SELECT username,role FROM access_users WHERE username IN (?,?)',people).fetchall()}
                if any(roles.get(p) not in {'writer','admin'} for p in people):raise ValueError('Default review users unavailable')
                # New targets must already own a real immutable prediction.
                members=[dict(r) for r in conn.execute('SELECT * FROM campaign_issue_members WHERE campaign_id=? ORDER BY ordinal',(root,)).fetchall()]
                new_members=[]
                for iid in new:
                    row=conn.execute('SELECT i.issue_id,i.baseline_scope FROM issues i JOIN model_predictions p ON p.issue_id=i.issue_id WHERE p.model_run_id=? AND i.issue_id=?',(rid,iid)).fetchone()
                    if not row:raise ValueError('Target has no version prediction')
                    scope=row['baseline_scope'];state=conn.execute('SELECT status FROM labeling_scope_state WHERE baseline_scope=?',(scope,)).fetchone()
                    if not state:
                        if not scope.startswith('manual_sidecar_'):raise ValueError('Historical scope requires explicit activation')
                        if conn.execute('SELECT COUNT(*) AS n FROM label_cases WHERE baseline_scope=?',(scope,)).fetchone()['n'] or conn.execute('SELECT COUNT(*) AS n FROM annotations a JOIN issues i ON i.issue_id=a.issue_id WHERE i.baseline_scope=?',(scope,)).fetchone()['n']:raise ValueError('Scope already has labels')
                        conn.execute("INSERT INTO labeling_scope_state(baseline_scope,status,policy_version,epoch,source_inventory_sha256,updated_by,updated_at) VALUES (?,'active',?,1,?,?,?)",(scope,'native-version-combined-v1',digest(scope),actor,utc_now()))
                    elif state['status']!='active':raise ValueError('Labeling scope is not active')
                    new_members.append(dict(campaign_id=root,issue_id=iid,baseline_scope=scope,ordinal=len(members)+len(new_members)+1,required_submitter_count=1,reviewers_per_issue=1,assignment_kinds_json=_json(['base']),config_revision=int(campaign['config_revision'])+1,created_at=utc_now()))
                counts=Counter(a['assignee'] for iid,a in assigned.items() if iid in set(current_target_ids))
                ordinals={p:max([a['ordinal'] for a in assigned.values() if a['assignee']==p] or [0]) for p in people}
                for m in new_members:
                    person=min(people,key=lambda p:(counts[p],people.index(p)));counts[person]+=1;ordinals[person]+=1
                    insert(conn,'campaign_issue_members',m)
                    record=dict(split_id=root,issue_id=m['issue_id'],assignee=person,assignment_kind='base',ordinal=ordinals[person],assigned_by=actor,assigned_at=utc_now());insert(conn,'review_work_assignments',record);assigned[m['issue_id']]=record
                    insert(conn,'campaign_assignment_audit',dict(campaign_id=root,issue_id=m['issue_id'],action='assigned',assignment_kind='base',from_assignee='',to_assignee=person,changed_by=actor,changed_by_source='version_task_service',changed_by_verified=False,config_revision=int(campaign['config_revision'])+1,idempotency_key='version-add-'+digest([batch_key,m['issue_id']]),idempotency_fingerprint=digest(record),reason='append to version task',changed_at=utc_now()))
                refs={r['baseline_scope']:dict(r) for r in conn.execute('SELECT * FROM campaign_reference_items WHERE campaign_id=?',(root,)).fetchall()}
                fresh={}
                for scope in sorted({m['baseline_scope'] for m in new_members}):
                    fresh[scope]=self._version_fresh_reference(conn,dict(dataset),[m for m in new_members if m['baseline_scope']==scope],scope,actor)
                by_scope=defaultdict(list)
                for m in members:by_scope[m['baseline_scope']].append((m['issue_id'],refs[m['baseline_scope']]))
                for m in new_members:by_scope[m['baseline_scope']].append((m['issue_id'],fresh[m['baseline_scope']]))
                all_members=members+new_members;wid=self._version_workset(conn,dict(dataset),root,all_members,actor)
                unions=[self._version_union_reference(conn,wid,scope,rows,actor) for scope,rows in sorted(by_scope.items())]
                conn.execute('DELETE FROM campaign_reference_items WHERE campaign_id=?',(root,))
                for ref in unions:insert(conn,'campaign_reference_items',dict(campaign_id=root,**ref,created_at=utc_now()))
                revision=int(campaign['config_revision'])+1
                conn.execute('UPDATE issue_work_splits SET workset_id=?,config_revision=?,total_count=?,updated_by=?,updated_at=? WHERE id=?',(wid,revision,len(all_members),actor,utc_now(),root))
                self._campaign_refresh_compat_assignment_snapshot(conn,root)
                self._campaign_insert_revision(conn,campaign_id=root,revision_no=revision,changed_by=actor,changed_by_source='version_task_service',changed_by_verified=False,change_source='version_append',idempotency_key=batch_key)
            bindings={iid:dict(run_id=rid,campaign_id=root,assignee=a['assignee']) for iid,a in assigned.items()}
            receipt=dict(campaign_id=root,added=len(new),added_ids=new,fingerprint=expected)
            self._version_event(conn,did,batch_key,'version_task_append',receipt,actor)
            self._mark_labeling_change(conn);self._mark_run_collection_change(conn)
            return dict(receipt,bindings=bindings)
