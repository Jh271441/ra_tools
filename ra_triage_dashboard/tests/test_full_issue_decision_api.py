"""Real image storage and transactional decisions against an isolated fixture."""
import asyncio
import io
import json
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException, UploadFile
from PIL import Image
import test_case_labeling as fixtures
from ra_triage_dashboard.app.routers.labeling_api import decisions
from ra_triage_dashboard.app.support import attachments, catalogs
from ra_triage_dashboard.app.db import LabelAnnotationConflictError


class FullDecisionApiTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=fixtures.CaseLabelingTest().make_db(self.tmp.name);self.addCleanup(self.db.close)
        self.db.set_labeling_scope_state(baseline_scope='scope',status='active',policy_version='test',source_inventory_sha256='a'*64,updated_by='test')
        self.db.create_label_revision(issue_id='cn1',expected_output='误触发',tags=[],evidence_gaps=[],rationale='original',is_excluded=True,author='alice',author_source='test',author_verified=True,expected_previous_revision_id=None)
        self.images=Path(self.tmp.name)/'images';self.images.mkdir()
        stack=ExitStack();self.addCleanup(stack.close)
        for target,name,value in [(attachments,'database',self.db),(catalogs,'database',self.db),(decisions,'database',self.db),(decisions,'_labeling_actor',Mock(return_value=('judge','test',True))),
            (decisions,'_require_active_labeling_issue',AsyncMock(return_value={'baseline_scope':'scope'})),
            (attachments,'settings',SimpleNamespace(review_attachments_dir=self.images))]:
            stack.enter_context(patch.object(target,name,value))
        state=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        self.body=dict(full_result=True,expected_output='误触发',is_excluded=False,tags=[],evidence_gaps=[],label_rationale='label evidence',rationale='judge evidence',expected_source_fingerprint=state['source_fingerprint'])
        self.request=Mock(json=AsyncMock(return_value=self.body))

    def upload(self):
        content=io.BytesIO();Image.new('RGB',(3,3),'red').save(content,format='PNG');content.seek(0)
        return UploadFile(filename='evidence.png',file=content)

    async def test_optional_review_rationale_preserves_original_evidence(self):
        original=self.db.label_cases_for_issue('cn1')[0]['resolution']['heads'][0]
        self.body.update(rationale='',adopted_revision_id=original['id'])
        saved=await decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps(self.body),[])
        decision=saved['decision']
        self.assertEqual(decision['rationale'],'')
        self.assertEqual(decision['full_result']['label_rationale'],'label evidence')
        self.assertEqual(decision['full_result']['adopted_revision']['rationale'],'original')
        self.assertEqual(self.db.label_cases_for_issue('cn1')[0]['resolution']['heads'][0]['rationale'],'original')

    async def test_multipart_stores_protected_image_and_conflict_cleans_only_new_file(self):
        saved=await decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps(self.body),[self.upload()])
        image=saved['decision']['attachments'][0]
        record=self.db.get_label_attachment(image['id']);path=self.images/record['stored_name']
        self.assertTrue(path.is_file());self.assertNotIn('stored_name',image)
        self.assertEqual(record['issue_id'],'cn1')
        with self.assertRaises(HTTPException) as caught:
            await decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps(self.body),[self.upload()])
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual([p for p in self.images.rglob('*') if p.is_file()],[path])

    async def test_permission_and_explicit_boolean_before_file_storage(self):
        for value in [None,'false',0]:
            with self.assertRaises(HTTPException) as caught:
                await decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps({**self.body,'is_excluded':value}),[self.upload()])
            self.assertEqual(caught.exception.status_code,400)
        with patch.object(decisions,'_labeling_actor',side_effect=HTTPException(403,'read only')):
            with self.assertRaises(HTTPException) as caught:
                await decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps(self.body),[self.upload()])
            self.assertEqual(caught.exception.status_code,403)
        self.assertFalse(any(self.images.rglob('*.png')))

    async def test_cancellation_does_not_delete_image_under_committing_worker(self):
        started=threading.Event();finish=threading.Event();completed=threading.Event()
        original=self.db.adjudicate_issue_label
        def delayed(**kwargs):
            started.set();finish.wait(5)
            try:return original(**kwargs)
            finally:completed.set()
        with patch.object(self.db,'adjudicate_issue_label',side_effect=delayed):
            task=asyncio.create_task(decisions.adjudicate_issue_with_attachments('cn1',self.request,json.dumps(self.body),[self.upload()]))
            self.assertTrue(await asyncio.to_thread(started.wait,3))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(any(self.images.rglob('*.png')))
            finish.set();self.assertTrue(await asyncio.to_thread(completed.wait,3));await asyncio.sleep(.02)
        saved=self.db.list_issue_label_decisions(baseline_scope='scope',issue_id='cn1')[0]
        image=self.db.get_label_attachment(saved['attachments'][0]['id'])
        self.assertTrue((self.images/image['stored_name']).is_file())

    async def test_route_registered_in_public_router(self):
        from ra_triage_dashboard.app.routers.labeling import router
        self.assertTrue(any(r.path=='/api/labeling/issues/{issue_id}/decisions-with-attachments' for r in router.routes))
