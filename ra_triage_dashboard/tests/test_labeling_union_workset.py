import tempfile
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Request, HTTPException

from ra_triage_dashboard.app.db import Database


def test_union_task_preserves_sources_and_is_discoverable_from_each_scope():
    with tempfile.TemporaryDirectory() as folder:
        db = Database(Path(folder) / 'test.sqlite')
        db.init()
        for scope, issue in [('original', 'cn1'), ('extra', 'cn2'), ('new', 'cn3')]:
            db.upsert_issues([{'issue_id': issue}], source='test', baseline_scope=scope, replace_gt=False)
            db.apply_gt_sync_snapshot(scope=scope, rows=[], source_name='test',
                source_view_id=1000, source_field='ra_merge_result', trigger='test',
                requested_by='admin', requested_by_source='test', requested_by_verified=False,
                expected_issue_ids=[issue], allow_sparse=True)
        old = db.create_review_workset(baseline_scope='original', issue_ids=['cn1'])
        old_task = db.create_labeling_task(workset_id=old['id'], assignments=[{'name':'alice','issue_ids':['cn1']}],
            created_by='admin', seed=1, reviewers_per_issue=1, overlap_ratio=0)
        saved = db.create_label_revision(issue_id='cn1', task_id=old_task['id'], expected_output='误触发',
            tags=[], evidence_gaps=[], is_excluded=False, rationale='preserve me', author='alice', author_source='test',
            author_verified=True, expected_previous_revision_id=None)
        with db.connect() as conn:
            before = [tuple(row) for row in conn.execute('SELECT * FROM label_revisions').fetchall()]
        ws = db.create_review_workset(baseline_scopes=['original','extra','new'], issue_ids=['cn1','cn2','cn3'])
        assert ws['baseline_scopes'] == ['extra','new','original']
        assert db.create_review_workset(baseline_scopes=['new','extra','original'], issue_ids=['cn1','cn2','cn3'])['id'] == ws['id']
        task = db.create_labeling_task(workset_id=ws['id'], assignments=[{'name':'bob','issue_ids':['cn1','cn2','cn3']}],
            created_by='admin', seed=1, reviewers_per_issue=1, overlap_ratio=0)
        for scope in ws['baseline_scopes']:
            assert task['id'] in {row['id'] for row in db.list_labeling_tasks([scope])}
        assert db.get_review_workset(old['id'])['baseline_scope'] == 'original'
        with db.connect() as conn:
            assert before == [tuple(row) for row in conn.execute('SELECT * FROM label_revisions').fetchall()]
            assert conn.execute('SELECT assignee FROM review_work_assignments WHERE split_id=?',(old_task['id'],)).fetchone()['assignee'] == 'alice'
        db.create_label_revision(issue_id='cn2',task_id=task['id'],expected_output='正确触发',tags=[],evidence_gaps=[],is_excluded=False,
            rationale='new submission',author='bob',author_source='test',author_verified=True,expected_previous_revision_id=None)
        result = db.list_labeling_cases(baseline_scopes=ws['baseline_scopes'], task_id=task['id'])
        assert result['total'] == 3
        assert next(x for x in result['items'] if x['issue_id']=='cn2')['label_state'] == 'resolved'
        assert saved['rationale'] == 'preserve me'
        with pytest.raises(ValueError, match='scope|数据集'):
            db.create_review_workset(baseline_scopes=['original'],issue_ids=['cn1','cn2'])
        with pytest.raises(ValueError, match='exactly'):
            db.create_review_workset(baseline_scopes=['original','extra'],issue_ids=['cn1'])


def test_union_task_api_requires_all_scopes_registered_and_active(tmp_path):
    from ra_triage_dashboard.app.routers.labeling_api import tasks
    db = Database(tmp_path / 'api.sqlite')
    db.init()
    for scope, issue in [('one', 'cn1'), ('two', 'cn2')]:
        db.upsert_issues([{'issue_id': issue}], source='test', baseline_scope=scope, replace_gt=False)
        db.apply_gt_sync_snapshot(scope=scope, rows=[], source_name='test', source_view_id=2410,
            source_field='unobserved', trigger='test', requested_by='admin', requested_by_source='test',
            requested_by_verified=False, expected_issue_ids=[issue], allow_sparse=True)
        db.set_labeling_scope_state(baseline_scope=scope, status='active', policy_version='test',
            source_inventory_sha256='test', updated_by='admin')

    def request():
        async def receive():
            return {'type': 'http.request', 'body': json.dumps({'issue_ids': ['cn1','cn2'],
                'assignees': [{'name':'alice'}], 'name': '0821 full', 'seed': 1}).encode()}
        return Request({'type':'http','headers':[],'query_string':b''}, receive)

    with patch.object(tasks, 'database', db), patch.object(tasks, '_admin_identity',
            return_value=SimpleNamespace(username='admin', source='test')):
        with patch.object(tasks, 'baseline_registry', SimpleNamespace(allowed_scopes=lambda: {'one'})):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(tasks.create_labeling_task(request()))
            assert exc.value.status_code == 400
            assert 'registered' in exc.value.detail
        with patch.object(tasks, 'baseline_registry', SimpleNamespace(allowed_scopes=lambda: {'one','two'})):
            result = asyncio.run(tasks.create_labeling_task(request()))
            assert result['total'] == 2
            assert result['workset']['baseline_scopes'] == ['one','two']
            db.set_labeling_scope_state(baseline_scope='two', status='paused', policy_version='test',
                source_inventory_sha256='test', updated_by='admin')
            with pytest.raises(HTTPException) as exc:
                asyncio.run(tasks.create_labeling_task(request()))
            assert exc.value.status_code == 400
            assert '尚未激活' in exc.value.detail
