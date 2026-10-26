const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const elements=new Map();
const element=()=>({hidden:false,disabled:false,textContent:'',innerHTML:'',dataset:{},querySelector(){return null;},focus(){}});
const dialog={querySelector(selector){if(!elements.has(selector))elements.set(selector,element());return elements.get(selector);}};
const s={console,Intl,Date,JSON,state:{uiLanguage:'zh'},uiText:(zh,en)=>s.state.uiLanguage==='en'?en:zh,
 escapeHtml:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
 $:sel=>sel==='#trailHistoryDialog'?dialog:dialog.querySelector(sel),document:{activeElement:null},api:()=>{throw Error('Unexpected remote write');}};
vm.createContext(s);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/trail-history.js'),'utf8'),s);
const h=vm.runInContext('trailHistory',s);
h.detail={source:'exclusion_summary',restorable:true,outcomes:{cn1:'succeeded'}};h.data={can_restore:true};
const item={issue_id:'cn1',before:{should_exclude:true,should_exclude_comment:'old'},after:{should_exclude:true,should_exclude_comment:'<new>'}};
let html=s.trailHistoryDiff(item);
assert(html.includes('排除状态未变'));assert(!html.includes('trail-history-transition'));
assert(html.includes('reason-after-cn1" open'));assert(html.includes('&lt;new>'));assert(!html.includes('data-restore-issue'));
item.before.should_exclude=false;html=s.trailHistoryDiff(item,'before','after',true);
assert(html.includes('trail-history-transition'));assert(html.includes('data-restore-issue="cn1"'));assert(!html.includes('checked'));
html=s.trailHistoryDiff({issue_id:'cn1',current:{},restore:{should_exclude:null}},'current','restore');
assert(html.includes('字段不存在'));assert(html.includes('null'));assert(html.includes('当前值'));assert(html.includes('恢复为'));
s.renderTrailHistoryActions();
assert(!dialog.querySelector('[data-action="start-restore"]').hidden);assert(dialog.querySelector('[data-action="commit"]').hidden);
h.restoring=true;s.renderTrailHistoryActions();assert(dialog.querySelector('[data-action="preview"]').disabled);
h.selected=['cn1'];h.reason='why';s.renderTrailHistoryActions();assert(!dialog.querySelector('[data-action="preview"]').disabled);
h.preview={ready:true,items:[item],conflicts:[]};s.renderTrailHistoryActions();assert(!dialog.querySelector('[data-action="commit"]').hidden);assert(!dialog.querySelector('[data-action="commit"]').disabled);
h.preview={ready:false,conflicts:['cn1']};s.renderTrailHistoryActions();assert(dialog.querySelector('[data-action="commit"]').hidden);
h.busy=true;s.renderTrailHistoryActions();assert(dialog.querySelector('[data-action="cancel-restore"]').disabled);
h.busy=false;h.restoring=false;h.detail.source='legacy';s.renderTrailHistoryActions();assert(dialog.querySelector('[data-action="start-restore"]').hidden);
h.detail.source='exclusion_summary';h.data.can_restore=false;s.renderTrailHistoryActions();assert(dialog.querySelector('[data-action="start-restore"]').hidden);
s.state.uiLanguage='en';html=s.trailHistoryDiff(item);assert(html.includes('Exclusion reason'));assert(html.includes('Changed'));
(async()=>{h.restoring=false;h.preview={ready:true};await s.previewTrailRestore();await s.commitTrailRestore();console.log('Trail history detail UI contracts passed');})().catch(e=>{console.error(e);process.exit(1);});
