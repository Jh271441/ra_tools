const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=path.join(__dirname,'../static/js');
function extract(file,name){const text=fs.readFileSync(path.join(source,file),'utf8'),start=text.indexOf('function '+name+'(');assert.ok(start>=0);return text.slice(start,text.indexOf('\n}',start)+2);}
Object.assign(global,{
  state:{selectedRunId:'run-a',selectedId:'',uiLanguage:'zh',reviewWorkflowMode:'model_review_only',caseLabeling:{}},
  uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,t:key=>key,reviewPendingGalleryTargetId:()=>'',
  safeSameOriginAssetUrl:()=>'',safeUrl:()=>'',evidenceLabel:key=>key,
});
vm.runInThisContext(fs.readFileSync(path.join(source,'core-base.js'),'utf8').split('const CONFIGURED_BASE_PATH =')[0]);
vm.runInThisContext(extract('format-api.js','escapeHtml')+'\n'+extract('format-api.js','labelBadge'));
vm.runInThisContext(fs.readFileSync(path.join(source,'review-label-state.js'),'utf8'));
const gallery=fs.readFileSync(path.join(source,'review-gallery.js'),'utf8');
vm.runInThisContext(gallery.slice(0,gallery.indexOf('function reuseGalleryThumbnails(')));
const item={issue_id:'cn123',gt_label:'正确触发',prediction:{label:'正确触发',model_run_id:'run-a',mismatch:false},
  annotation:{id:1,model_run_id:'run-a',model_review_status:'completed',label:'正确触发'},
  expected_output:'正确触发',label_state:{state:'resolved',expected_output:'误触发',gt_relation:'differs_from_gt',source_revision_ids:[1]}};
const human=issueCardHumanLabelMarkup(item);
assert.match(human,/data-shared-human-label="误触发"/);
assert.doesNotMatch(human,/>正确触发</);
const relation=sharedLabelStateButtonMarkup(item,{compact:true});
for(const mode of ['model_review_only','model_review_and_case_label']){
  state.reviewWorkflowMode=mode;
  const card=issueCard(item);
  assert.ok(card.includes(human));assert.ok(card.includes(relation));
  assert.match(card,/comparison-match/); // Model vs GT stays independent of Human vs GT.
  assert.match(card,/issue-card-human-summary/);
}
const before=caseGallerySignature([item]);
item.label_state={...item.label_state,expected_output:'正确触发',gt_relation:'matches_gt',source_revision_ids:[2]};
assert.notEqual(caseGallerySignature([item]),before);
assert.match(issueCard(item),/data-shared-human-label="正确触发"/);
for(const [status,fallback] of [['none','未标注'],['pending','待补齐'],['conflict','有分歧'],['stale','待复核']]){
  item.label_state={state:status,expected_output:'误触发'};
  const result=issueCardHumanLabelMarkup(item);
  assert.match(result,/data-shared-human-label=""/);assert.ok(result.includes(fallback));assert.doesNotMatch(result,/>误触发</);
}
delete item.label_state;
assert.match(issueCardHumanLabelMarkup(item),/未标注/);
item.label_state={state:'resolved',expected_output:'out_of_scope'};
assert.doesNotMatch(issueCardHumanLabelMarkup(item),/out_of_scope/);
state.uiLanguage='en';item.label_state={state:'conflict'};
assert.match(issueCardHumanLabelMarkup(item),/Human/);assert.match(issueCardHumanLabelMarkup(item),/Disagreement/);
const labeling=issueCard({...item,expected_output:'无需协助',gallery_workspace:'labeling'});
assert.doesNotMatch(labeling,/issue-card-human-summary/);assert.match(labeling,/>无需协助</);
console.log('Shared Human result, modes, unresolved states, refresh signature, independent comparisons and Case labeling: passed');
