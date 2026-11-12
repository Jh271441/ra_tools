"""1106+ append-only sampling and low-confidence campaigns, sharing one Run."""
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime
import re
import uuid

from .shared import _json, _json_load, utc_now
from .version_campaigns import insert
from ..human_label_policy import allocate_role_pairs, digest, RD_REVIEWERS, TE_REVIEWERS, POLICY


def sampled(seed, family, issue_id):
    # Byte-identical to the frozen version_probability_v3 selection protocol.
    return int(digest(['version_probability_v3',seed,family,issue_id])[:16],16) < (1 << 64)//10


class RoleVersionTasksMixin:
    def role_version_campaigns(self, dataset_id):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM human_version_tasks WHERE dataset_id=? ORDER BY cohort DESC', (dataset_id,)).fetchall()]

    def append_role_version_campaign_members(self, *, family,policy,issue_ids,current_target_ids,batch_key,actor,_connection=None,_historical=None):
        datetime.strptime(family,'%Y%m%d')
        if family<'20261106' or policy.get('sampling_policy')!='version_probability_v3' or not re.fullmatch('[a-f0-9]{64}',str(policy.get('seed',''))):
            raise ValueError('Invalid role allocation policy')
        if not actor or not batch_key or len(issue_ids)!=len(set(issue_ids)) or len(issue_ids)>5000 or any(not re.fullmatch('cn[0-9]+',i) for i in issue_ids):
            raise ValueError('Invalid version append identity')
        if not set(issue_ids)<=set(current_target_ids):
            raise ValueError('New allocation includes inactive targets')
        did='release-'+family+'-odd2';rid=str(uuid.uuid5(uuid.NAMESPACE_URL,'ra-triage:'+did))
        expected=digest(dict(family=family,policy=policy,issue_ids=sorted(issue_ids)))
        with self._write_lock,(nullcontext(_connection) if _connection is not None else self.connect()) as conn:
            if self.backend=='sqlite' and _connection is None:conn.execute('BEGIN IMMEDIATE')
            elif self.backend=='postgresql':conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(did,))
            if not conn.execute("SELECT 1 FROM model_runs WHERE id=? AND kind='version_live'",(rid,)).fetchone():
                raise ValueError('Version Run not registered')
            dataset=conn.execute('SELECT * FROM version_datasets WHERE id=?',(did,)).fetchone()
            if not dataset:
                now=utc_now()
                insert(conn,'version_datasets',dict(id=did,name=family[4:]+' 复核集',release_family=family,policy_json=_json(policy),revision=0,run_id=rid,created_at=now,updated_at=now))
                dataset=conn.execute('SELECT * FROM version_datasets WHERE id=?',(did,)).fetchone()
            dataset=dict(dataset)
            if _json_load(dataset['policy_json'],{})!=policy:raise ValueError('Frozen version policy mismatch')
            legacy=self._version_registration(conn,did) or conn.execute('SELECT 1 FROM dataset_task_bindings WHERE dataset_id=?',(did,)).fetchone()
            registered_roles=conn.execute('SELECT 1 FROM human_version_tasks WHERE dataset_id=?',(did,)).fetchone()
            if legacy and not registered_roles and _historical is None:
                raise ValueError('1106旧任务需要先按迁移清单切换 / Existing 1106 task requires an audited cutover')
            replay=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND batch_key=? AND action='role_task_append'",(did,batch_key)).fetchone()
            if replay and _json_load(replay['detail_json'],{})['fingerprint']!=expected:raise ValueError('Version append idempotency conflict')
            added=[];bindings={};campaign_ids=[]
            for cohort in ('sampling','low'):
                ids=[iid for iid in issue_ids if sampled(policy['seed'],family,iid)==(cohort=='sampling')]
                registered=conn.execute('SELECT * FROM human_version_tasks WHERE dataset_id=? AND cohort=?',(did,cohort)).fetchone()
                if not registered and not ids:continue
                root='campaign-version-'+family+'-odd2-'+cohort
                if not registered:
                    namespace=digest([POLICY,did,cohort]);now=utc_now()
                    insert(conn,'issue_work_splits',dict(id=root,created_by=actor,created_at=now,seed=int(policy['seed'][:7],16),total_count=0,
                        filter_json=_json(dict(version_live=True,version_dataset_id=did,role_cohort=cohort,publication_policy=POLICY)),
                        assignees_json='[]',overlap_ratio=1 if cohort=='sampling' else 0,purpose='model_review',evaluation_run_id=rid,model_run_id=rid,
                        reference_type='reference_set',reference_id=namespace,reference_sha256=namespace,lifecycle='active',config_revision=1,
                        campaign_name=family[4:]+' · '+('抽样集' if cohort=='sampling' else '低置信集'),task_kind='model_review',mode='blind' if cohort=='sampling' else 'single',
                        reviewers_per_issue=2 if cohort=='sampling' else 1,assignment_count=0,workset_id='',selection_source_run_id=rid,
                        workflow_mode='model_review_and_case_label',updated_by=actor,updated_at=now))
                    insert(conn,'human_version_tasks',dict(dataset_id=did,cohort=cohort,campaign_id=root,seed=policy['seed'],created_at=now))
                else:root=registered['campaign_id']
                campaign_ids.append(root)
                campaign=dict(conn.execute('SELECT * FROM issue_work_splits WHERE id=?',(root,)).fetchone())
                if campaign['lifecycle']!='active':raise ValueError('Version task is not active')
                members=[dict(r) for r in conn.execute('SELECT * FROM campaign_issue_members WHERE campaign_id=? ORDER BY ordinal',(root,)).fetchall()]
                assigned=defaultdict(list)
                assignments=[dict(r) for r in conn.execute('SELECT * FROM review_work_assignments WHERE split_id=? ORDER BY issue_id,assignment_kind',(root,)).fetchall()]
                for a in assignments:assigned[a['issue_id']].append(a['assignee'])
                new=sorted(set(ids)-{m['issue_id'] for m in members})
                people=(*RD_REVIEWERS,*TE_REVIEWERS) if cohort=='sampling' else RD_REVIEWERS
                if new:
                    for person in people:
                        account=conn.execute('SELECT a.role AS permission,h.role FROM access_users a JOIN human_user_roles h ON h.username=a.username WHERE a.username=?',(person,)).fetchone()
                        expected_role='rd' if person in RD_REVIEWERS else 'te'
                        if not account or account['permission'] not in {'writer','admin'} or account['role']!=expected_role:
                            raise ValueError('默认标注人员不可用 / Default reviewer unavailable: '+person)
                previous=[dict(assignees=sorted(owners,key=lambda p:p not in RD_REVIEWERS)) for iid,owners in assigned.items() if iid in set(current_target_ids)]
                allocations=allocate_role_pairs(new,sampled=cohort=='sampling',seed=policy['seed'],previous=previous,
                    fixed_rd={i:v['owner'] for i,v in (_historical or {}).items()})
                ordinals={p:max([a['ordinal'] for a in assignments if a['assignee']==p] or [0]) for p in people}
                fresh_members=[]
                for allocation in allocations:
                    iid=allocation['issue_id']
                    row=conn.execute('SELECT i.baseline_scope FROM issues i JOIN model_predictions p ON p.issue_id=i.issue_id WHERE p.model_run_id=? AND i.issue_id=?',(rid,iid)).fetchone()
                    if not row:raise ValueError('Target has no immutable prediction')
                    scope=row['baseline_scope'];active=conn.execute('SELECT status FROM labeling_scope_state WHERE baseline_scope=?',(scope,)).fetchone()
                    if not active:
                        if not scope.startswith('manual_sidecar_'):raise ValueError('Historical scope requires explicit activation')
                        if conn.execute('SELECT 1 FROM label_cases WHERE baseline_scope=? LIMIT 1',(scope,)).fetchone():raise ValueError('Scope already has labels')
                        conn.execute("INSERT INTO labeling_scope_state(baseline_scope,status,policy_version,epoch,source_inventory_sha256,updated_by,updated_at) VALUES(?,'active',?,1,?,?,?)",(scope,POLICY,digest(scope),actor,utc_now()))
                    elif active['status']!='active':raise ValueError('Labeling scope is not active')
                    owners=allocation['assignees'];required=len(owners)
                    member=dict(campaign_id=root,issue_id=iid,baseline_scope=scope,ordinal=len(members)+len(fresh_members)+1,
                                required_submitter_count=required,reviewers_per_issue=required,assignment_kinds_json=_json(['base','cross'][:required]),
                                config_revision=int(campaign['config_revision'])+1,created_at=utc_now())
                    insert(conn,'campaign_issue_members',member);fresh_members.append(member)
                    for index,person in enumerate(owners):
                        # Audited history can retain an RD outside the new roster.
                        ordinals[person]=ordinals.get(person,0)+1
                        record=dict(split_id=root,issue_id=iid,assignee=person,assignment_kind='base' if index==0 else 'cross',
                                    ordinal=ordinals[person],assigned_by=actor,assigned_at=utc_now())
                        insert(conn,'review_work_assignments',record)
                        insert(conn,'campaign_assignment_audit',dict(campaign_id=root,issue_id=iid,action='assigned',assignment_kind=record['assignment_kind'],
                            from_assignee='',to_assignee=person,changed_by=actor,changed_by_source=POLICY,changed_by_verified=False,
                            config_revision=int(campaign['config_revision'])+1,idempotency_key='role-add-'+digest([batch_key,iid,person]),
                            idempotency_fingerprint=digest(record),reason='append role review',changed_at=utc_now()))
                    assigned[iid]=owners;added.append(iid)
                    self.register_human_label_scope(issue_id=iid,campaign_id=root,dataset_id=did,actor=actor,connection=conn)
                if fresh_members:
                    refs={r['baseline_scope']:dict(r) for r in conn.execute('SELECT * FROM campaign_reference_items WHERE campaign_id=?',(root,)).fetchall()}
                    fresh={scope:self._version_fresh_reference(conn,dataset,[m for m in fresh_members if m['baseline_scope']==scope],scope,actor)
                           for scope in sorted({m['baseline_scope'] for m in fresh_members})}
                    by_scope=defaultdict(list)
                    for member in members:by_scope[member['baseline_scope']].append((member['issue_id'],refs[member['baseline_scope']]))
                    for member in fresh_members:
                        reference=(_historical or {}).get(member['issue_id'],{}).get('reference') or fresh[member['baseline_scope']]
                        by_scope[member['baseline_scope']].append((member['issue_id'],reference))
                    all_members=members+fresh_members;wid=self._version_workset(conn,dataset,root,all_members,actor)
                    unions=[self._version_union_reference(conn,wid,scope,rows,actor) for scope,rows in sorted(by_scope.items())]
                    conn.execute('DELETE FROM campaign_reference_items WHERE campaign_id=?',(root,))
                    for ref in unions:insert(conn,'campaign_reference_items',dict(campaign_id=root,**ref,created_at=utc_now()))
                    revision=int(campaign['config_revision'])+1
                    conn.execute('UPDATE issue_work_splits SET workset_id=?,config_revision=?,total_count=?,updated_by=?,updated_at=? WHERE id=?',
                                 (wid,revision,len(all_members),actor,utc_now(),root))
                    self._campaign_refresh_compat_assignment_snapshot(conn,root)
                    self._campaign_insert_revision(conn,campaign_id=root,revision_no=revision,changed_by=actor,changed_by_source=POLICY,
                                                  changed_by_verified=False,change_source='version_append',idempotency_key=batch_key)
                for iid,owners in assigned.items():
                    ordered=sorted(owners,key=lambda p:p not in RD_REVIEWERS)
                    bindings[iid]=dict(run_id=rid,campaign_id=root,assignee=ordered[0],assignees=ordered,cohort=cohort)
            receipt=dict(campaign_ids=campaign_ids,added=len(added),added_ids=added,fingerprint=expected)
            self._version_event(conn,did,batch_key,'role_task_append',receipt,actor)
            self._mark_labeling_change(conn);self._mark_run_collection_change(conn)
            return dict(receipt,bindings=bindings)
