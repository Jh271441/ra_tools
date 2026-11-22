"""Audited addition of TE reviewers to existing 1106+ low-confidence tasks."""
from collections import Counter, defaultdict
from contextlib import nullcontext
import json

from .db_parts.shared import _json, utc_now
from .db_parts.version_campaigns import digest, insert
from .human_label_policy import RD_REVIEWERS, TE_REVIEWERS, allocate_role_pairs

CONTRACT = 'low-confidence-rd-te-cross-v1'


def plan_te_extension(db, dataset_id, *, connection=None):
    with (nullcontext(connection) if connection is not None else db.connect()) as conn:
        dataset = conn.execute('SELECT * FROM version_datasets WHERE id=?', (dataset_id,)).fetchone()
        campaign = conn.execute('''SELECT s.*,h.seed FROM human_version_tasks h
            JOIN issue_work_splits s ON s.id=h.campaign_id WHERE h.dataset_id=? AND h.cohort='low' ''', (dataset_id,)).fetchone()
        if not dataset or dataset['release_family'] < '20261106' or not campaign or campaign['lifecycle'] != 'active':
            raise ValueError('An active 1106+ low-confidence task is required')
        cid = campaign['id']
        members = [dict(r) for r in conn.execute('SELECT * FROM campaign_issue_members WHERE campaign_id=? ORDER BY issue_id', (cid,)).fetchall()]
        assignments = [dict(r) for r in conn.execute('''SELECT a.*,r.role FROM review_work_assignments a
            LEFT JOIN human_assignment_roles r ON r.campaign_id=a.split_id AND r.issue_id=a.issue_id AND r.username=a.assignee
            WHERE a.split_id=? ORDER BY a.issue_id,a.assignee''', (cid,)).fetchall()]
        people = {person: [] for person in [m['issue_id'] for m in members]}
        for row in assignments:
            people[row['issue_id']].append(row)
        missing = {}; previous = []
        for iid, owners in people.items():
            rd = [r for r in owners if r['role'] == 'rd']
            te = [r for r in owners if r['role'] == 'te']
            if len(rd) != 1 or len(te) > 1 or len(rd) + len(te) != len(owners):
                raise ValueError('Expected one RD and at most one TE per Issue: ' + iid)
            if any(r['assignee'] not in TE_REVIEWERS for r in te):
                raise ValueError('Existing TE is outside the confirmed roster: ' + iid)
            if te:
                previous.append(dict(assignees=[rd[0]['assignee'], te[0]['assignee']]))
            else:
                missing[iid] = rd[0]['assignee']
        users = [dict(r) for r in conn.execute('''SELECT a.username,a.role AS access_role,h.role
            FROM access_users a JOIN human_user_roles h ON h.username=a.username
            WHERE a.username IN (?,?) ORDER BY a.username''', TE_REVIEWERS).fetchall()]
        if {u['username'] for u in users if u['access_role'] in {'writer', 'admin'} and u['role'] == 'te'} != set(TE_REVIEWERS):
            raise ValueError('Both confirmed TE reviewers need existing annotation access')
        allocations = allocate_role_pairs(list(missing), seed=campaign['seed'], previous=previous, fixed_rd=missing)
        proposed = [dict(issue_id=row['issue_id'], rd=row['assignees'][0], te=row['assignees'][1]) for row in allocations]
        source = dict(dataset_id=dataset_id, campaign=dict(campaign), members=members, assignments=assignments, users=users)
        return dict(contract=CONTRACT, dataset_id=dataset_id, campaign_id=cid, fingerprint=digest(source),
                    added=len(proposed), te_counts=dict(Counter(r['te'] for r in proposed)),
                    pairs=dict(Counter(r['rd']+' / '+r['te'] for r in proposed)), proposed=proposed, source=source)


def apply_te_extension(db, *, dataset_id, actor, expected_fingerprint):
    if db.access_role(actor) != 'admin':
        raise PermissionError('Task extension requires a Dashboard administrator')
    with db._write_lock, db.connect() as conn:
        db._lock_task_work(conn)
        if db.backend == 'postgresql':
            conn.execute('SELECT pg_advisory_xact_lock(hashtext(?))', (dataset_id,))
        replay = conn.execute("SELECT detail_json FROM dataset_audit_events WHERE dataset_id=? AND batch_key=? AND action=?",
                              (dataset_id, expected_fingerprint, CONTRACT)).fetchone()
        if replay:
            return dict(json.loads(replay['detail_json']), replayed=True)
        plan = plan_te_extension(db, dataset_id, connection=conn)
        if plan['fingerprint'] != expected_fingerprint:
            raise ValueError('Task inventory changed; review a fresh extension plan')
        cid = plan['campaign_id']; now = utc_now()
        revision = int(plan['source']['campaign']['config_revision']) + 1
        ordinals = defaultdict(int)
        for row in plan['source']['assignments']:
            ordinals[row['assignee']] = max(ordinals[row['assignee']], int(row['ordinal']))
        for row in plan['proposed']:
            person = row['te']; iid = row['issue_id']; ordinals[person] += 1
            insert(conn, 'review_work_assignments', dict(split_id=cid, issue_id=iid, assignee=person, assignment_kind='cross',
                ordinal=ordinals[person], assigned_by=actor, assigned_at=now))
            insert(conn, 'campaign_assignment_audit', dict(campaign_id=cid, issue_id=iid, action='assigned', assignment_kind='cross',
                from_assignee='', to_assignee=person, changed_by=actor, changed_by_source=CONTRACT, changed_by_verified=True,
                config_revision=revision, idempotency_key=CONTRACT+'-'+iid, idempotency_fingerprint=digest(row),
                reason='Add one independent TE reviewer; retain the original RD and all submissions', changed_at=now))
            conn.execute('''UPDATE campaign_issue_members SET required_submitter_count=2,reviewers_per_issue=2,
                assignment_kinds_json=?,config_revision=? WHERE campaign_id=? AND issue_id=?''', (_json(['base', 'cross']), revision, cid, iid))
        conn.execute('''UPDATE issue_work_splits SET mode='blind',overlap_ratio=1,reviewers_per_issue=2,
            config_revision=?,updated_by=?,updated_by_source=?,updated_by_verified=true,updated_at=? WHERE id=?''',
                     (revision, actor, CONTRACT, now, cid))
        db._campaign_refresh_compat_assignment_snapshot(conn, cid)
        db._campaign_insert_revision(conn, campaign_id=cid, revision_no=revision, changed_by=actor,
            changed_by_source=CONTRACT, changed_by_verified=True, change_source='assignment', idempotency_key=expected_fingerprint)
        owners = defaultdict(list)
        for row in conn.execute('SELECT issue_id,assignee FROM review_work_assignments WHERE split_id=? ORDER BY assignee', (cid,)).fetchall():
            owners[row['issue_id']].append(row['assignee'])
        for item in conn.execute('SELECT issue_id,binding_json FROM version_dataset_items WHERE dataset_id=?', (dataset_id,)).fetchall():
            binding = json.loads(item['binding_json'])
            if binding.get('campaign_id') == cid:
                binding['assignees'] = owners[item['issue_id']]
                conn.execute('UPDATE version_dataset_items SET binding_json=? WHERE dataset_id=? AND issue_id=?', (_json(binding), dataset_id, item['issue_id']))
        result = {key: plan[key] for key in ['contract', 'dataset_id', 'campaign_id', 'fingerprint', 'added', 'te_counts', 'pairs']}
        result.update(config_revision=revision, actor=actor, shared_history=True)
        db._version_event(conn, dataset_id, expected_fingerprint, CONTRACT, result, actor)
        conn.execute('UPDATE version_datasets SET revision=revision+1,updated_at=? WHERE id=?', (now, dataset_id))
        db._mark_change_topic(conn, 'review'); db._mark_labeling_change(conn)
        return result
