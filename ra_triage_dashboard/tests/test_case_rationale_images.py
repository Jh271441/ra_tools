"""Upload cleanup and browser draft isolation contracts for Case evidence."""
import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
ROOT = Path(__file__).resolve().parents[1]


class CaseRationaleImagesTest(unittest.TestCase):
    def test_upload_cleanup_keeps_committed_files_even_if_response_fails(self):
        from ra_triage_dashboard.app.routers import case_annotations as route
        for committed, fail in [(False, False), (False, True), (True, False), (True, True)]:
            with self.subTest(committed=committed, fail=fail), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "image.png"; path.write_bytes(b"test")
                db = Mock(); db.get_label_attachment.return_value = {"id": "new"} if committed else None
                submit = AsyncMock(side_effect=RuntimeError("failure")) if fail else AsyncMock(return_value={"duplicate": True})
                with patch.object(route, "database", db), patch.object(route, "_writer_identity", return_value=object()), patch.object(route, "_store_review_attachments", AsyncMock(return_value=([{"id": "new"}], [path]))):
                    if fail:
                        with self.assertRaises(RuntimeError): asyncio.run(route._submit_case_images("cn1", object(), "{}", [], submit))
                    else: asyncio.run(route._submit_case_images("cn1", object(), "{}", [], submit))
                self.assertEqual(path.exists(), committed)

    def test_request_cancellation_does_not_race_database_commit(self):
        from ra_triage_dashboard.app.routers import case_annotations as route
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"; path.write_bytes(b"test")
            db = Mock(); db.get_label_attachment.return_value = None
            with patch.object(route, "database", db), patch.object(route, "_writer_identity", return_value=object()), patch.object(route, "_store_review_attachments", AsyncMock(return_value=([{"id": "new"}], [path]))):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(route._submit_case_images("cn1", object(), "{}", [], AsyncMock(side_effect=asyncio.CancelledError())))
            self.assertTrue(path.exists())
            db.get_label_attachment.assert_not_called()

    def test_invalid_payload_or_identity_never_stores_images(self):
        from fastapi import HTTPException
        from ra_triage_dashboard.app.routers import case_annotations as route
        for payload in ["bad", "[]"]:
            with patch.object(route, "_writer_identity", return_value=object()), patch.object(route, "_store_review_attachments", AsyncMock()) as store:
                with self.assertRaises(HTTPException): asyncio.run(route._submit_case_images("cn1", object(), payload, [], AsyncMock()))
                store.assert_not_called()
        with patch.object(route, "_writer_identity", side_effect=HTTPException(403)), patch.object(route, "_store_review_attachments", AsyncMock()) as store:
            with self.assertRaises(HTTPException): asyncio.run(route._submit_case_images("cn1", object(), "{}", [], AsyncMock()))
            store.assert_not_called()

    def test_pending_files_are_scoped_and_only_saved_snapshot_is_cleared(self):
        script = (ROOT / "static/js/review-attachments.js").read_text() + r'''
const assert = require('node:assert/strict');
state={selectedCase:{issue_id:'cn1'},session:{username:'alice'},config:{},reviewFormDirty:false};
reviewDraftStorageKey=(issue,run,task,actor)=>[issue,run,task,actor].join('|');
currentReviewRunId=()=>state.run||'run1';reviewWorkSplitBinding=()=>state.task||'';reviewDraftReviewer=()=>state.session.username;
let errors=[],revoked=[];hasDashboardWriteRole=()=>true;uiText=(zh,en)=>en;showToast=(text)=>errors.push(text);
URL={createObjectURL:()=> 'blob:'+Math.random(),revokeObjectURL:(url)=>revoked.push(url)};
window={setTimeout:(fn)=>fn()};crypto={randomUUID:()=>Math.random().toString()};$=()=>null;
const file={name:'e.png',type:'image/png',size:100};
addCaseRationaleImages([file]);const original=caseRationalePendingImages(),key=caseRationaleImageKey();
assert.equal(original.length,1);assert.equal(state.pendingReviewImages,undefined);
state.selectedCase={issue_id:'cn2'};assert.equal(caseRationalePendingImages().length,0);
state.selectedCase={issue_id:'cn1'};state.run='other';assert.equal(caseRationalePendingImages().length,0);
state.run='run1';state.reviewWorkSplitId='task';assert.equal(caseRationalePendingImages().length,0);
state.reviewWorkSplitId='';state.session.username='bob';assert.equal(caseRationalePendingImages().length,0);
state.session.username='alice';assert.equal(caseRationalePendingImages().length,1);
const snapshot=[...caseRationalePendingImages()];addCaseRationaleImages([file]);
clearSavedCaseRationaleImages(key,snapshot);assert.equal(caseRationalePendingImages().length,1);assert.equal(revoked.length,1);
addCaseRationaleImages([{...file,type:'text/plain'},{...file,size:8388609}]);assert.equal(caseRationalePendingImages().length,1);assert.equal(errors.length,1);
addCaseRationaleImages([file,file,file,file]);assert.equal(caseRationalePendingImages().length,4);
let calls=[];FormData=class{constructor(){this.values=[]}append(...args){this.values.push(args)}};
api=async(path,options)=>{calls.push({path,options});throw new Error('offline')};
(async()=>{try{await submitCaseRationalePayload('cn1','combined-review',{},caseRationalePendingImages(),{'Idempotency-Key':'key'})}catch(_){}
assert.equal(caseRationalePendingImages().length,4);assert.equal(calls[0].options.headers['X-RA-Triage-Request'],'labeling-v1');
assert.equal(calls[0].options.headers['Idempotency-Key'],'key');assert.equal(calls[0].options.body.values.filter(v=>v[0]==='attachments').length,4);
assert.ok(calls[0].path.endsWith('combined-review-with-attachments'));
})();
'''
        subprocess.run(["node"], input=script, text=True, check=True, capture_output=True)


class CaseImageUploadIntegrationTest(unittest.TestCase):
    # Reuse a disposable SQLite/active-scope fixture, with no external writers.
    def setUp(self):
        from test_combined_reviews import CombinedReviewWorkflowTest
        CombinedReviewWorkflowTest.setUp(self)

    def test_real_image_normalization_atomic_save_replay_conflict_and_invalid_file(self):
        from contextlib import ExitStack
        from io import BytesIO
        from PIL import Image
        from fastapi import HTTPException, UploadFile
        from ra_triage_dashboard.app.routers import case_annotations as route
        from ra_triage_dashboard.app.support import attachments as storage, catalogs
        from test_combined_reviews import CombinedReviewWorkflowTest
        campaign = CombinedReviewWorkflowTest.campaign(self, 0)
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        body = dict(campaign_id=campaign["id"], work_split_id=campaign["id"], model_run_id=campaign["evaluation_run_id"],
            expected_output="误触发", tags=[], rationale="image evidence", update_case_details=True,
            model_review_status="completed", expected_model_review_storage_id=None, expected_case_revision_id=None,
            expected_label_state_fingerprint=context["label_state_fingerprint"])
        request = SimpleNamespace(headers={"idempotency-key": "upload-key"})
        root = Path(self.tmp.name) / "images"
        output = BytesIO(); Image.new("RGB", (16, 9), "blue").save(output, format="PNG")
        def upload(content=output.getvalue()): return UploadFile(filename="proof.png", file=BytesIO(content))
        async def submit(content=output.getvalue()):
            return await route._submit_case_images("cn1", request, json.dumps(body), [upload(content)], route._submit_combined_review)
        with ExitStack() as stack:
            for module in (route, storage, catalogs): stack.enter_context(patch.object(module, "database", self.db))
            stack.enter_context(patch.object(storage, "settings", SimpleNamespace(review_attachments_dir=root)))
            stack.enter_context(patch.object(route, "settings", SimpleNamespace(dchat_notifications_enabled=False)))
            stack.enter_context(patch.object(route, "_writer_identity", return_value=SimpleNamespace(username="alice")))
            stack.enter_context(patch.object(route, "_action_actor", return_value=("alice", "test", True)))
            stack.enter_context(patch.object(route, "_review_tag_catalog", return_value=[]))
            result = asyncio.run(submit())["combined_review"]
            self.assertEqual(len(result["case_attachments"]), 1)
            self.assertEqual(len(list(root.rglob("*.png"))), 1)
            self.assertTrue(asyncio.run(submit())["combined_review"]["duplicate"])
            self.assertEqual(len(list(root.rglob("*.png"))), 1)
            request.headers["idempotency-key"] = "stale"
            with self.assertRaises(HTTPException) as exc: asyncio.run(submit())
            self.assertEqual(exc.exception.status_code, 409)
            self.assertEqual(len(list(root.rglob("*.png"))), 1)
            with self.assertRaises(HTTPException): asyncio.run(submit(b"not an image"))
            self.assertEqual(len(list(root.rglob("*.png"))), 1)
            self.assertIsNotNone(self.db.get_label_attachment(result["case_attachments"][0]["id"]))

    def test_new_upload_routes_enforce_marker_and_size_guard(self):
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from ra_triage_dashboard.app.main import request_size_guard
        for action in ("combined-review", "case-label-from-review"):
            path = f"/api/cases/cn1/{action}-with-attachments"
            def request(headers): return Request({"type": "http", "method": "POST", "path": path, "headers": [(k.encode(), v.encode()) for k,v in headers.items()]})
            next_handler = AsyncMock(return_value=JSONResponse({"ok": True}))
            response = asyncio.run(request_size_guard(request({"content-length": "20"}), next_handler))
            self.assertEqual(response.status_code, 403); next_handler.assert_not_called()
            response = asyncio.run(request_size_guard(request({"x-ra-triage-request": "labeling-v1", "content-length": str(27*1024*1024)}), next_handler))
            self.assertEqual(response.status_code, 413); next_handler.assert_not_called()
            response = asyncio.run(request_size_guard(request({"x-ra-triage-request": "labeling-v1", "content-length": "20"}), next_handler))
            self.assertEqual(response.status_code, 200); next_handler.assert_awaited_once()
