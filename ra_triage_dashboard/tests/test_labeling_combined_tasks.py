"""Same task IDs and exact acknowledged votes, without copying or writing work."""
import asyncio
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_combined_reviews as workflow
import test_version_campaign_physical as version
from ra_triage_dashboard.app.combined_task_summary import combined_task_summaries


class CombinedTaskSummaryTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    campaign = workflow.CombinedReviewWorkflowTest.campaign
    submit = workflow.CombinedReviewWorkflowTest.submit

    def test_exact_acknowledgement_separate_counts_and_read_only(self):
        campaign = self.campaign(0)
        self.campaign(1, workflow='model_review_only')
        free = dict(id='', evaluation_run_id=campaign['evaluation_run_id'])
        context = self.db.combined_review_context(issue_id='cn1', campaign_id='', reviewer='alice', model_run_id=free['evaluation_run_id'])
        self.submit(free, context)
        initial = combined_task_summaries(self.db, ['scope'])
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0]['split_id'], campaign['id'])
        self.assertEqual(initial[0]['labeled'], 0)  # A free vote is not task completion.
        context = self.db.combined_review_context(issue_id='cn1', campaign_id=campaign['id'], reviewer='alice')
        self.submit(campaign, context, status='pending', key='partial')
        # Imported/partially acknowledged progress is distinct from a successful
        # combined submit (which confirms model submission even for pending judgment).
        with self.db.connect() as conn:
            conn.execute('UPDATE combined_review_progress SET model_review_submitted=false WHERE campaign_id=?', (campaign['id'],))
        revision = self.db.change_revision()
        item = combined_task_summaries(self.db, ['scope'])[0]
        self.assertEqual((item['total'], item['labeled'], item['reviewed'], item['completed']), (1, 1, 0, 0))
        self.assertEqual(self.db.change_revision(), revision)
        self.assertEqual(combined_task_summaries(self.db, ['other']), [])
        self.assertEqual(combined_task_summaries(self.db, []), [])
        context = self.db.combined_review_context(issue_id='cn1', campaign_id=campaign['id'], reviewer='alice')
        self.submit(campaign, context, key='complete')
        item = combined_task_summaries(self.db, ['scope'])[0]
        self.assertEqual((item['labeled'], item['reviewed'], item['completed']), (1, 1, 1))

    def test_assignees_are_not_collapsed_to_case_count(self):
        campaign = self.campaign(0, assignees=['alice', 'bob'])
        context = self.db.combined_review_context(issue_id='cn1', campaign_id=campaign['id'], reviewer='alice')
        self.submit(campaign, context)
        item = combined_task_summaries(self.db, ['scope'])[0]
        self.assertEqual(item['member_count'], 1)
        self.assertEqual((item['total'], item['completed']), (2, 1))
        self.assertEqual([p['labeled'] for p in item['members']], [1, 0])

    def test_api_requires_writer_and_keeps_version_selection(self):
        from ra_triage_dashboard.app.routers.labeling_api import tasks
        from ra_triage_dashboard.app.routers import labeling
        self.assertTrue(any(route.path == '/api/labeling/combined-tasks' and route.endpoint is tasks.list_combined_labeling_tasks for route in labeling.router.routes))
        async def run():
            with patch.object(tasks, '_require_labeling_writer', new=AsyncMock(side_effect=PermissionError)):
                with self.assertRaises(PermissionError):
                    await tasks.list_combined_labeling_tasks(None)
            items = [dict(dataset_id='release-20261009-odd2', appendable=True),
                     dict(dataset_id='release-20261016-odd2', appendable=True)]
            with patch.object(tasks, '_require_labeling_writer', new=AsyncMock()), \
                 patch.object(tasks, '_active_labeling_scopes', new=AsyncMock(return_value=['scope'])), \
                 patch.object(tasks, 'resolve_request_baseline_scopes', return_value=['scope']), \
                 patch.object(tasks, 'resolve_request_baseline_ids', return_value=['version-20261009']), \
                 patch.object(tasks, 'combined_task_summaries', return_value=items):
                payload = await tasks.list_combined_labeling_tasks(None, 'version-20261009')
                self.assertEqual(payload['items'], items[:1])
        asyncio.run(run())


class CombinedVersionSummaryTest(unittest.TestCase):
    setUp = version.VersionCampaignPhysicalTest.setUp
    submit = version.VersionCampaignPhysicalTest.submit

    def test_current_targets_exclude_historical_completion_and_keep_canonical_id(self):
        old = self.campaigns[0]
        ctx = self.db.combined_review_context(issue_id='cn1', campaign_id=old['id'], reviewer='jasperchen')
        self.submit(old, ctx)
        receipt = self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2', backup_sha256='a'*64, actor='test')
        self.items[0]['is_target'] = False
        self.items[0]['is_low'] = False
        self.db.ingest_version_dataset(family='20261009', policy=self.policy, items=self.items, batch_key='retire', actor='test')
        rev = self.db.change_revision()
        item = combined_task_summaries(self.db, ['manual_sidecar_test'])[0]
        self.assertEqual(item['split_id'], receipt['campaign_id'])
        self.assertEqual(item['baseline_ids'], ['version-20261009'])
        self.assertEqual((item['total'], item['labeled'], item['completed']), (1, 0, 0))
        self.assertEqual(item['members'][0]['username'], 'liangxianghui')
        self.assertEqual(self.db.change_revision(), rev)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM label_revisions').fetchone()['n'], 1)


class CombinedTaskFrontendTest(unittest.TestCase):
    def test_entry_context_and_late_response_guard(self):
        module = Path(__file__).parents[1] / 'static/js/labeling-combined-tasks.js'
        script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
let scope='1009',pending=[],requests=[];
const context={URLSearchParams,console,state:{session:{verified:true,username:'Alice'}},
 selectedBaselineQueryValue:()=>scope,api:(path)=>{requests.push(path);return new Promise(resolve=>pending.push(resolve));},
 pageUrl:(page,args)=>({page,args})};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'review-assignments.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
vm.runInContext('renderLabelingCombinedTasks=()=>{}',context);
const item={appendable:true,dataset_id:'release-20261009-odd2',members:[{username:'alice'}]};
let link=context.labelingCombinedTaskHref(item);
assert.equal(link.page,'review');assert.equal(link.args.workAssignee[0],'alice');assert.equal(link.args.taskView,'pending');
link=context.labelingCombinedTaskHref({split_id:'same-task',model_run_id:'same-run',workflow_mode:'model_review_and_case_label',baseline_ids:['0508'],members:[{username:'alice'}]});
assert.equal(link.args.workSplitId,'same-task');assert.equal(link.args.runId,'same-run');
assert.equal(link.args.workAssignee[0],'alice');assert.equal(link.args.baselines[0],'0508');
assert.equal(link.args.comparisonStatus,'all');assert.equal(link.args.workflowMode,'model_review_and_case_label');
const task=id=>({split_id:id,is_current:true,lifecycle:'active',workflow_mode:'model_review_and_case_label'});
(async()=>{const first=context.loadLabelingCombinedTasks();scope='1016';const second=context.loadLabelingCombinedTasks();
assert.ok(requests.every(path=>path.startsWith('/api/cases/work-splits?') && !path.includes('baselines=')));
pending[1]({items:[task('new'),{...task('model-only'),workflow_mode:'model_review_only'},
 {...task('cancelled'),lifecycle:'cancelled'},{...task('old-active'),is_current:false}]});await second;
pending[0]({items:[task('old')]});await first;
assert.equal(vm.runInContext('labelingCombinedTasks.items[0].split_id',context),'new');
assert.equal(vm.runInContext('labelingCombinedTasks.items.length',context),1);
const third=context.loadLabelingCombinedTasks();context.state.session.username='Bob';pending[2]({items:[{split_id:'wrong-actor'}]});await third;
assert.equal(vm.runInContext('labelingCombinedTasks.items[0].split_id',context),'new');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(['node', '-e', script, str(module)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_cards_and_refresh_states(self):
        script = Path(__file__).with_name('labeling_combined_cards.cjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
