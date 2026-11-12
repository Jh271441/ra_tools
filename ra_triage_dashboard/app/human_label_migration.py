"""Backup-bound 1106 cutover. Original records remain in an immutable audit receipt.

No Trail calls. Historical sources remain unarmed until a separate activation.
"""
import json
import re
from contextlib import nullcontext

from .db_parts.shared import _json,utc_now
from .human_label_policy import digest
from .db_parts.role_version_tasks import sampled


def migration_plan(db,dataset_id,*,connection=None):
    with (nullcontext(connection) if connection is not None else db.connect()) as conn:
        row=conn.execute('SELECT * FROM version_datasets WHERE id=?',(dataset_id,)).fetchone()
        if not row or row['release_family']<'20261106':raise ValueError('Only registered 1106+ datasets can cut over')
        dataset=dict(row);policy=json.loads(dataset['policy_json']);blocks=[]
        if conn.execute('SELECT 1 FROM human_version_tasks WHERE dataset_id=?',(dataset_id,)).fetchone():blocks.append('already_registered')
        campaigns=[dict(r) for r in conn.execute("SELECT * FROM issue_work_splits WHERE evaluation_run_id=? AND purpose='model_review' ORDER BY id",(dataset['run_id'],)).fetchall()
                   if not json.loads(r['filter_json']).get('supplemental_review')]
        if not campaigns:blocks.append('no_source_tasks')
        archive={};proposed={};revisions={}
        for campaign in campaigns:
            cid=campaign['id']
            if campaign['lifecycle']!='active' or campaign['workflow_mode']!='model_review_and_case_label' or campaign.get('task_group_id'):blocks.append('unsupported_task:'+cid)
            tables={}
            for table,key in [('campaign_issue_members','campaign_id'),('review_work_assignments','split_id'),
                              ('campaign_reference_items','campaign_id'),('combined_review_progress','campaign_id'),
                              ('model_review_heads','campaign_id'),('combined_review_submissions','campaign_id'),
                              ('campaign_config_revisions','campaign_id'),('campaign_config_members','campaign_id'),
                              ('campaign_assignment_audit','campaign_id'),('review_comments','campaign_id')]:
                tables[table]=sorted([dict(r) for r in conn.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(cid,)).fetchall()],key=_json)
            archive[cid]=dict(campaign=campaign,tables=tables)
            refs={r['baseline_scope']:r for r in tables['campaign_reference_items']}
            for member in tables['campaign_issue_members']:
                iid=member['issue_id'];owners=[a['assignee'] for a in tables['review_work_assignments'] if a['issue_id']==iid]
                item=conn.execute('SELECT * FROM version_dataset_items WHERE dataset_id=? AND issue_id=?',(dataset_id,iid)).fetchone()
                if iid in proposed or len(owners)!=1 or not item or member['baseline_scope'] not in refs:
                    blocks.append('ambiguous_member:'+iid);continue
                cohort='sampling' if sampled(policy['seed'],dataset['release_family'],iid) else 'low'
                if bool(item['is_sample'])!=(cohort=='sampling'):blocks.append('sampling_identity_mismatch:'+iid)
                proposed[iid]=dict(owner=owners[0],cohort=cohort,campaign_id=cid,baseline_scope=member['baseline_scope'],
                                   reference=refs[member['baseline_scope']],item=dict(item))
                revisions[iid]=[dict(r) for r in conn.execute('''SELECT r.*,v.role AS captured_role FROM label_revisions r
                    JOIN label_cases c ON c.id=r.label_case_id LEFT JOIN human_vote_roles v ON v.revision_id=r.id
                    WHERE c.issue_id=? AND c.baseline_scope=? ORDER BY r.id''',(iid,member['baseline_scope'])).fetchall()]
        targets={r['issue_id'] for r in conn.execute('SELECT issue_id FROM version_dataset_items WHERE dataset_id=? AND is_target=1',(dataset_id,)).fetchall()}
        if targets-set(proposed):blocks.append('targets_without_formal_owner')
        source=json.loads(_json(dict(dataset=dataset,archive=archive,proposed=proposed,revisions=revisions)))
        missing=[dict(revision_id=r['id'],issue_id=iid,author=r['author'],created_at=r['created_at'])
                 for iid,rows in revisions.items() for r in rows if not r['captured_role']]
        return dict(contract='human-role-cutover-v1',dataset_id=dataset_id,fingerprint=digest(source),blocked=sorted(set(blocks)),
                    total=len(proposed),sampling=sum(p['cohort']=='sampling' for p in proposed.values()),
                    low=sum(p['cohort']=='low' for p in proposed.values()),missing_role_evidence=missing,
                    historical_publication_armed=False,source=source)


def apply_migration(db,*,dataset_id,expected_fingerprint,backup_sha256,actor,historical_role=None):
    if not re.fullmatch('[a-f0-9]{64}',backup_sha256) or historical_role not in {None,'rd','te'}:
        raise ValueError('Verified backup and explicit historical role policy required')
    if db.access_role(actor)!='admin':raise PermissionError('Cutover requires a directory administrator')
    with db._write_lock,db.connect() as conn:
        if db.backend=='sqlite':conn.execute('BEGIN IMMEDIATE')
        else:
            conn.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
            conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(dataset_id,))
        replay=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND action='role_task_cutover'",(dataset_id,)).fetchone()
        if replay:
            receipt=json.loads(replay['detail_json'])
            if receipt['source_fingerprint']!=expected_fingerprint:raise ValueError('Cutover already applied from another inventory')
            return dict(receipt,replayed=True)
        plan=migration_plan(db,dataset_id,connection=conn)
        if plan['fingerprint']!=expected_fingerprint:raise ValueError('Migration inventory changed; regenerate and review')
        if plan['blocked']:raise ValueError('Migration blocked: '+','.join(plan['blocked']))
        if plan['missing_role_evidence'] and historical_role is None:raise ValueError('Historical submission roles require explicit classification')
        source=plan['source'];dataset=source['dataset'];proposed=source['proposed'];now=utc_now()
        for entry in plan['missing_role_evidence']:
            conn.execute('INSERT INTO human_vote_roles(revision_id,role,captured_at) VALUES(?,?,?)',(entry['revision_id'],historical_role,now))
        targets=[i for i,p in proposed.items() if p['item']['is_target']]
        # Preserve inactive historical members as well; active quotas are computed from targets.
        result=db.append_role_version_campaign_members(family=dataset['release_family'],policy=json.loads(dataset['policy_json']),
            issue_ids=list(proposed),current_target_ids=list(proposed),batch_key='cutover:'+expected_fingerprint,actor=actor,
            _connection=conn,_historical=proposed)
        for iid,old in proposed.items():
            binding=result['bindings'][iid];new=binding['campaign_id'];previous=old['campaign_id']
            reference=conn.execute('SELECT reference_id FROM issue_work_splits WHERE id=?',(new,)).fetchone()['reference_id']
            # Only mutable heads and progress move. Revision payloads and submission IDs survive.
            conn.execute('UPDATE model_review_heads SET campaign_id=?,reference_id=? WHERE campaign_id=? AND issue_id=?',(new,reference,previous,iid))
            conn.execute('UPDATE combined_review_progress SET campaign_id=? WHERE campaign_id=? AND issue_id=?',(new,previous,iid))
            conn.execute('UPDATE review_comments SET campaign_id=? WHERE campaign_id=? AND issue_id=?',(new,previous,iid))
            conn.execute('INSERT INTO human_campaign_redirects(campaign_id,issue_id,target_campaign_id,created_at) VALUES(?,?,?,?)',(previous,iid,new,now))
            conn.execute('UPDATE dataset_task_bindings SET campaign_id=?,assignee=? WHERE dataset_id=? AND issue_id=?',(new,binding['assignee'],dataset_id,iid))
            conn.execute('UPDATE version_dataset_items SET binding_json=? WHERE dataset_id=? AND issue_id=?',(_json(binding),dataset_id,iid))
            # All original assignments are RD in the authorized pre-TE policy. Preserve
            # their business identity even if the current directory has since changed.
            old_role=conn.execute('SELECT role FROM human_assignment_roles WHERE campaign_id=? AND issue_id=? AND username=?',(previous,iid,old['owner'])).fetchone()
            role=old_role['role'] if old_role else historical_role
            if role!='rd':raise ValueError('Original owner is not a verified historical RD: '+iid)
            conn.execute("""INSERT INTO human_assignment_roles(campaign_id,issue_id,username,role,captured_at)
                VALUES(?,?,?,'rd',?) ON CONFLICT(campaign_id,issue_id,username) DO UPDATE SET role='rd'""",
                (new,iid,old['owner'].lower(),now))
            conn.execute('UPDATE human_label_scopes SET publication_armed=0 WHERE issue_id=?',(iid,))
        for cid,archive in source['archive'].items():
            # Preserve the original task, assignments, configuration and revisions for history.
            original=archive['campaign'];revision=int(original['config_revision'])+1
            conn.execute('''INSERT INTO campaign_lifecycle_audit(campaign_id,action,from_lifecycle,to_lifecycle,changed_by,changed_by_source,
                changed_by_verified,config_revision,idempotency_key,idempotency_fingerprint,reason,changed_at)
                VALUES(?, 'superseded','active','superseded',?,'role_cutover',true,?,?,?,?,?)''',
                (cid,actor,revision,'role-cutover:'+expected_fingerprint,expected_fingerprint,'Split into role-aware version tasks',now))
            conn.execute("UPDATE issue_work_splits SET lifecycle='superseded',config_revision=?,updated_by=?,updated_at=? WHERE id=?",(revision,actor,now,cid))
            db._campaign_insert_revision(conn,campaign_id=cid,revision_no=revision,changed_by=actor,changed_by_source='role_cutover',
                changed_by_verified=True,change_source='lifecycle',idempotency_key='role-cutover:'+expected_fingerprint)
        receipt=dict(dataset_id=dataset_id,source_fingerprint=expected_fingerprint,backup_sha256=backup_sha256,
            historical_role_policy=historical_role,actor=actor,created_at=now,campaign_ids=result['campaign_ids'],
            preserved_issues=len(proposed),historical_publication_armed=False,archive=source)
        db._version_event(conn,dataset_id,'role-cutover:'+expected_fingerprint,'role_task_cutover',receipt,actor)
        db._mark_labeling_change(conn);db._mark_run_collection_change(conn)
        return receipt


def arm_migrated_sources(db,*,dataset_id,source_fingerprint,actor):
    if db.access_role(actor)!='admin':raise PermissionError('Activation requires a directory administrator')
    with db._write_lock,db.connect() as conn:
        receipt=conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND action='role_task_cutover'",(dataset_id,)).fetchone()
        if not receipt or json.loads(receipt['detail_json'])['source_fingerprint']!=source_fingerprint:raise ValueError('Reviewed cutover receipt required')
        conn.execute('UPDATE human_label_scopes SET publication_armed=1 WHERE dataset_id=?',(dataset_id,))
        db._version_event(conn,dataset_id,'arm:'+source_fingerprint,'role_task_armed',dict(source_fingerprint=source_fingerprint),actor)
        return dict(dataset_id=dataset_id,armed=True)
