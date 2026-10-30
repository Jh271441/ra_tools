const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.join(__dirname, '../static/js');
const source = name => process.env.IME_TEST_REF && name !== 'text-input.js'
  ? execFileSync('git', ['show', `${process.env.IME_TEST_REF}:ra_triage_dashboard/static/js/${name}`], {encoding:'utf8'})
  : fs.readFileSync(path.join(root, name), 'utf8');
function context() {
  const s = {console, Event, WeakMap, document:{activeElement:null}, window:{addEventListener(){}, matchMedia(){return {matches:false};}}};
  vm.createContext(s);
  vm.runInContext(source('text-input.js'), s);
  return s;
}
function key(props) {
  return {key:'Enter', defaultPrevented:false, ...props,
    preventDefault(){this.defaultPrevented=true;}, stopPropagation(){}};
}
function mentions() {
  const s=context(), listeners={};
  vm.runInContext(source('review-mentions.js'),s);
  s.state={mentionUsers:[],config:{},session:{}};
  s.updateReviewMentionComposer=()=>{};
  const option={dataset:{reviewMention:'alice'},scrollIntoView(){}};
  const popover={hidden:false};
  const root={hidden:false,querySelectorAll(){return [option];},querySelector(selector){return selector==='.review-mention-popover'?popover:option;},replaceChildren(){},contains(){return false;}};
  const input={value:'@a',selectionStart:2,selectionEnd:2,dataset:{},setAttribute(){},focus(){},dispatchEvent(){},
    addEventListener(type,fn){listeners[type]=fn;},
    setRangeText(value,start,end){this.value=this.value.slice(0,start)+value+this.value.slice(end);this.selectionStart=this.selectionEnd=start+value.length;}};
  s.bindReviewMentionComposer(input,root);
  return {s,input,root,popover,listeners};
}
for(const props of [{isComposing:true},{keyCode:229},{which:229}]) {
  for(const name of ['Enter','Tab','ArrowDown','ArrowUp','Escape']) {
    const m=mentions(), event=key({key:name,target:m.input,...props});
    m.listeners.keydown(event);
    assert.equal(m.input.value,'@a',`${name}: must leave IME text untouched`);
    assert.equal(event.defaultPrevented,false,`${name}: IME owns the key`);
  }
}
{
  const m=mentions();
  m.listeners.compositionstart();
  assert.equal(m.popover.hidden,true,'hide web suggestions during native composition');
  assert.equal(m.root.hidden,false,'keep status layout stable during native composition');
  const event=key({target:m.input});
  m.listeners.keydown(event);
  assert.equal(event.defaultPrevented,false,'composition lifecycle guards a missing browser flag');
  m.listeners.compositionend();
  assert.equal(m.input.dataset.imeComposing,undefined);
  m.root.hidden=false;
  m.popover.hidden=false;
  m.listeners.keydown(key({target:m.input}));
  assert.equal(m.input.value,'@alice ','ordinary mention selection still works');
}
{
  const s=context();
  vm.runInContext(source('review-tags.js'),s);
  let submitted=0;
  s.state={savingAnnotation:false};
  s.$=selector=>selector==='#annotationForm'?{requestSubmit(){submitted++;}}:null;
  const target={matches(){return true;},closest(){return null;},dataset:{}};
  for(const props of [{isComposing:true},{keyCode:229},{which:229}]) {
    assert.equal(s.submitReviewFromKeyboard(key(props),target),false);
    assert.equal(s.submitReviewFromDropdown(key(props),{closest(){return {};}}),false);
  }
  assert.equal(submitted,0);
  assert.equal(s.submitReviewFromKeyboard(key({}),target),true);
  assert.equal(submitted,1,'a separate ordinary Enter still submits');
  assert.equal(s.submitReviewFromKeyboard(key({shiftKey:true}),target),false);
  s.window.matchMedia=()=>({matches:true});
  assert.equal(s.submitReviewFromKeyboard(key({}),target),false,'phone Enter remains a newline');
}
async function refreshProtection() {
  const s=context();
  vm.runInContext(source('review-form.js'),s);
  let reads=0, paints=0, selects=0, resolve;
  const input={matches(){return true;}};
  const pane={contains(node){return node===input;}};
  s.$=()=>pane;
  s.state={selectedCase:{issue_id:'cn1',media_status:'loading'},pendingReviewImages:[]};
  s.selectCase=()=>{selects++;};
  s.document.activeElement=input;
  await s.refreshReviewCorePreservingMedia();
  assert.equal(selects,0,'loading media must not cause focused form replacement');
  s.state.selectedCase.media_status='ready';
  s.capturePageContext=()=>({});s.isPageContextCurrent=()=>true;s.caseCorePath=()=>'/case';
  s.caseRationaleUploadTask=()=>null;s.renderDetail=()=>{paints++;};s.renderReview=()=>{paints++;};
  s.api=()=>{reads++;return new Promise(r=>{resolve=r;});};
  await s.refreshReviewCorePreservingMedia();
  assert.equal(reads,0,'focused clean input blocks refresh before any text commits');
  s.document.activeElement=null;
  const original=s.state.selectedCase;
  const pending=s.refreshReviewCorePreservingMedia();
  s.document.activeElement=input;
  resolve({issue_id:'cn1'});await pending;
  assert.equal(s.state.selectedCase,original,'focus acquired during fetch preserves the original case/form');
  assert.equal(paints,0);
  s.document.activeElement=null;
  const resumed=s.refreshReviewCorePreservingMedia();
  resolve({issue_id:'cn1'});await resumed;
  assert.equal(paints,2,'ordinary refresh resumes after leaving the input');
  let resumedReads=0;
  s.refreshReviewCorePreservingMedia=async()=>{resumedReads++;};
  s.state.activePage='review';s.state.deferredDetailRefresh=true;
  s.document.activeElement=input;s.resumeDeferredReviewRefresh(s.state.selectedCase);
  assert.equal(resumedReads,0,'moving to another form field must keep refresh deferred');
  s.document.activeElement=null;s.state.reviewFormDirty=true;
  s.resumeDeferredReviewRefresh(s.state.selectedCase);
  assert.equal(resumedReads,0,'leaving an unsaved draft does not replace it');
  s.state.reviewFormDirty=false;s.resumeDeferredReviewRefresh(s.state.selectedCase);
  assert.equal(resumedReads,1,'leaving a clean input resumes the deferred update');
  s.state.activePage='labeling';s.resumeDeferredReviewRefresh(s.state.selectedCase);
  assert.equal(resumedReads,1,'a late focusout cannot refresh another page');
}
refreshProtection().then(()=>console.log('IME keys, mention lifecycle, desktop/mobile Enter and refresh focus races passed')).catch(e=>{console.error(e);process.exitCode=1;});
