const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(); const el=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',classList:{toggle(){}}});return nodes.get(id)};
const ctx=vm.createContext({state:{uiLanguage:'zh'},$:el,formatTime:x=>x||'—',escapeHtml:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')});
for(const file of process.argv.slice(2))vm.runInContext(fs.readFileSync(file,'utf8'),ctx);
vm.runInContext(`state.systemStatus={overall:{status:'healthy'},database:{ok:true},model_gateway:{configured:true},legacy_cutover:{policies:[]},
 baselines:[{id:'0508',scope:'private_scope',label:'0508 <name>',registration_status:'registered',count:10,media_status:'partial',
 membership:{registered_count:10,expected_count:10},media_ready:{bev_indexed_issues:10,video_indexed_issues:9,camera_indexed_issues:8},missing_media:{video:1,camera:2}}]};renderSystemStatus()`,ctx);
let html=el('#systemStatusGrid').innerHTML;
assert(html.includes('<table'));assert(html.includes('0508 &lt;name>'));assert(html.includes('9 / 10'));assert(html.includes('Camera 缺少 2'));
assert(!html.includes('Legacy Cutover'));assert(!html.includes('CAS epoch'));assert(!html.includes('private_scope'));
let history=html.split('历史复核数据')[1].split('</article>')[0];assert(history.includes('status-chip neutral'));assert(!history.includes('status-chip warn'));
vm.runInContext(`state.systemStatus.legacy_cutover.policies=[{baseline_scope:'private_scope',policy:'canonical'}];renderSystemStatus()`,ctx);
html=el('#systemStatusGrid').innerHTML;assert(html.includes('新版记录'));assert(!html.includes('private_scope'));
vm.runInContext(`state.uiLanguage='en';renderSystemStatus()`,ctx);html=el('#systemStatusGrid').innerHTML;
assert(html.includes('Historical reviews'));assert(html.includes('Camera missing 2'));assert(html.includes('Dashboard publication'));
console.log('Status UI: scoped fractions, missing-media warning, escaped names, neutral empty policy, named policy and English rendering passed');

// Loading/error values must never appear as synthetic zero coverage.
vm.runInContext(`state.uiLanguage='zh';Object.assign(state.systemStatus.baselines[0],{media_status:'checking',media_ready:{coverage_status:'pending'},missing_media:{}});renderSystemStatus()`,ctx);
html=el('#systemStatusGrid').innerHTML;assert(html.includes('统计更新中'));assert(html.includes('— / 10'));assert(!html.includes('<td>0 / 10</td>'));
// A pending refresh owns its URL/page and cannot navigate or poll after leave.
(async()=>{
 let callback,reads=0,current=true;
 ctx.window={clearTimeout(){},setTimeout(fn){callback=fn;return 1}};
 ctx.capturePageContext=()=>({url:'/system-status'});ctx.isPageContextCurrent=()=>current;
 ctx.renderConfig=()=>{};ctx.api=async()=>{reads++;return {baselines:[{media_ready:{coverage_status:'pending'}}]}};
 vm.runInContext('state.activePage="status"',ctx);await vm.runInContext('loadStatus()',ctx);
 assert.equal(reads,1);assert.equal(typeof callback,'function');
 current=false;vm.runInContext('state.activePage="labeling"',ctx);callback();assert.equal(reads,1);
 console.log('Status UI: pending counts and stale-page polling guard passed');
})().catch(error=>{console.error(error);process.exitCode=1});
