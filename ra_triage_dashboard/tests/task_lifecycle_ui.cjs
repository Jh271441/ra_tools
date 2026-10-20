const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = {reviewAssignmentMetrics:{innerHTML:''}};
let requests=[];
const store={splits:[],lifecycle:'current',assignedToMe:false,loadedKey:'current:false',requestSeq:0};
const sandbox={URL,URLSearchParams,state:{reviewAssignments:store,modelRuns:[{id:'run',name:'Run'}],session:{is_admin:false}},
 withBase:x=>x,$:selector=>elements[selector.slice(1)]||null,uiText:x=>x,escapeHtml:String,formatTime:String,
 window:{location:{origin:'https://example.com',search:'?lifecycle=history&assigned_to_me=true'}},
 pageUrl:(page,options)=>`/${page}?campaign=${options.campaignId||''}`,showToast:()=>{},
 api:async url=>{requests.push(url);return {items:[{split_id:'old',lifecycle:'superseded',is_current:false}],metrics:{batch_count:1,assignment_count:1,completed_count:1,pending_count:0}};}
};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/review-assignments.js','utf8'),sandbox);
const old={split_id:'old',lifecycle:'superseded',is_current:true,campaign_name:'Old task',members:[],assignment_count:4};
const card=sandbox.renderReviewAssignmentBatch(old);
assert(card.includes('已替代'));assert(card.includes('查看审计与复核'));assert(!card.includes('去判错复核'));assert(!card.includes('href="/review'));
store.metrics={assignment_count:1,completed_count:1,pending_count:0};sandbox.renderReviewAssignmentMetrics([old]);
assert(elements.reviewAssignmentMetrics.innerHTML.includes('<strong>1</strong>'));
assert(!elements.reviewAssignmentMetrics.innerHTML.includes('<strong>4</strong>'));
store.lifecycle='history';store.assignedToMe=true;
assert(sandbox.reviewAssignmentDetailUrl('old').includes('lifecycle=history'));
assert(sandbox.reviewAssignmentDetailUrl('old').includes('assigned_to_me=true'));
// A writer can inspect live rows and enter Review, but cannot transfer ownership.
for (const id of ['reviewAssignmentDetail', 'reviewAssignmentDetailTitle', 'reviewAssignmentDetailMeta', 'reviewAssignmentDetailRows', 'reviewAssignmentsHeading', 'workSplitPanel']) elements[id] = {};
store.detail = {split_id:'active',model_run_id:'run',is_current:true,lifecycle:'active',members:[],items:[{issue_id:'cn1',assignee:'writer',submitted:false}]};
store.detailRequestSeq=0;store.detailLoading=false;
sandbox.renderReviewAssignmentDetailFilters=()=>{};
sandbox.renderReviewAssignmentPermissions(); assert.equal(elements.workSplitPanel.hidden,true);
assert.equal(elements.reviewAssignmentsHeading.textContent,'任务分配');
sandbox.renderReviewAssignmentDetail();
assert(elements.reviewAssignmentDetailRows.innerHTML.includes('review-assignment-issue-link'));
assert(elements.reviewAssignmentDetailRows.innerHTML.includes('仅管理员可转派'));
assert(!elements.reviewAssignmentDetailRows.innerHTML.includes('data-review-assignment-save'));
assert(!elements.reviewAssignmentDetailRows.innerHTML.includes('review-assignment-person-picker'));
assert(!elements.reviewAssignmentDetailRows.innerHTML.includes('历史批次'));
const active={...old,split_id:'active',is_current:true,lifecycle:'active'};
assert(sandbox.renderReviewAssignmentBatch(active).includes('去判错复核'));
let adminUserReads=0; sandbox.loadAccessUsers=async()=>{adminUserReads++;};
sandbox.reassignReviewAssignment({dataset:{issueId:'cn1',originalAssignee:'bob'},querySelector:()=>({value:'writer'})});
assert.equal(requests.length,0,'writer transfer must not call PATCH');
// Administrator controls remain available on unfinished, current tasks.
sandbox.state.session.is_admin=true;sandbox.document={querySelectorAll:()=>[]};
sandbox.renderReviewAssignmentDetail();
assert(elements.reviewAssignmentDetailRows.innerHTML.includes('data-review-assignment-save'));
sandbox.state.session.is_admin=false;
sandbox.renderReviewAssignmentPage=()=>{};sandbox.restoreReviewAllocationDraft=async()=>{};
store.splits=[old]; // A nonempty cached current list must not block historical fetch.
(async()=>{await sandbox.loadReviewAssignments();assert.equal(adminUserReads,0);assert.equal(requests.length,1);assert(requests[0].includes('lifecycle=history'));assert(requests[0].includes('assigned_to_me=true'));assert.equal(store.loadedKey,'history:true');console.log('history guards, scoped metrics, route and cache passed');})().catch(e=>{console.error(e);process.exitCode=1;});
