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
sandbox.renderReviewAssignmentPage=()=>{};sandbox.restoreReviewAllocationDraft=async()=>{};
store.splits=[old]; // A nonempty cached current list must not block historical fetch.
(async()=>{await sandbox.loadReviewAssignments();assert.equal(requests.length,1);assert(requests[0].includes('lifecycle=history'));assert(requests[0].includes('assigned_to_me=true'));assert.equal(store.loadedKey,'history:true');console.log('history guards, scoped metrics, route and cache passed');})().catch(e=>{console.error(e);process.exitCode=1;});
