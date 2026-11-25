const fs = require('fs'), vm = require('vm'), assert = require('assert');
const path = require('path');
const root = path.join(__dirname, '../static/js');
const nodes = new Map();
function node() { return {dataset:{},classList:{toggle(){}},setAttribute(){},querySelector(){return node();},textContent:''}; }
const state={selectedBaselineIds:['version-20261009'],baselineCatalog:[{id:'version-20261009',label:'1009'}]};
const ctx=vm.createContext({state, normalizeBaselineIds:x=>x, uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,
  $:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}, Intl,Date,Set});
vm.runInContext(fs.readFileSync(path.join(root,'gt-sync.js'),'utf8'),ctx);
ctx.renderGtSyncTooltip=()=>{};
const old={baseline_id:'old',status:'ready',last_checked_at:'2026-10-27T08:00:00Z'};
const incremental={baseline_id:'version-20261009',status:'not_started'};
let current={status:'ready',baselines:[old]};
ctx.renderGtSyncStatus(current);
assert.equal(nodes.get('#gtSyncControl').dataset.status,'failed');
assert.equal(nodes.get('#gtSyncSourceTime').textContent,'校验不可用');
current={status:'not_started',baseline_sources:{'version-20261009':['old','version-20261009']},baselines:[old,incremental]};
ctx.renderGtSyncStatus(current);
assert.equal(ctx.selectedGtSyncItems(current).length,2);
assert.equal(nodes.get('#gtSyncSourceTime').textContent,'待校验');
incremental.status='ready';incremental.last_checked_at=old.last_checked_at;
ctx.renderGtSyncStatus({...current,status:'running',baselines:[old,incremental,{baseline_id:'other',status:'running'}]});
assert.equal(nodes.get('#gtSyncControl').dataset.status,'ready','unrelated running scope must not replace selected status');
state.uiLanguage='en';incremental.status='not_started';ctx.renderGtSyncStatus(current);
assert.equal(nodes.get('#gtSyncSourceTime').textContent,'Awaiting check');
state.selectedBaselineIds=['partition'];state.baselineCatalog=[{id:'partition',source_ids:['old']}];
assert.equal(ctx.selectedGtSyncItems(current)[0].baseline_id,'old');
state.selectedBaselineIds=['unknown'];assert.equal(ctx.selectedGtSyncItems(current)[0].status,'unavailable');
state.selectedBaselineIds=[];assert.equal(ctx.selectedGtSyncItems(current).length,2);
// Execute the actual comparison expressions in both rendered contexts.
for(const file of ['review-form.js','media-dialog.js']) {
  const src=fs.readFileSync(path.join(root,file),'utf8');
  const expression=src.match(/const predictionComparable = ([^;]+);/)[1];
  for(const gt of ['',null,'成功','正确触发','误触发','无需协助']) {
    const context={LABELS:['正确触发','误触发','无需协助'],MODEL_LABELS:['正确触发','误触发','无需协助','真实卡住'],caseData:{gt_label:gt},primary:{model_label:'误触发'},gtLabel:gt,modelLabel:'误触发'};
    assert.equal(vm.runInNewContext(expression,context),context.LABELS.includes(gt),file+' '+gt);
  }
}
const detailSource=fs.readFileSync(path.join(root,'review-form.js'),'utf8');
const compareText=detailSource.match(/const compareText = ([\s\S]*?);/)[1];
assert.equal(vm.runInNewContext(compareText,{predictionComparable:false,predictionMatches:false}),'');
assert.match(vm.runInNewContext(compareText,{predictionComparable:true,predictionMatches:true}),/Match/);
assert.match(vm.runInNewContext(compareText,{predictionComparable:true,predictionMatches:false}),/Mismatch/);
assert(detailSource.includes('${predictionComparable ? `<strong'));
console.log('PASS version GT scope status, language and missing-GT comparisons');
