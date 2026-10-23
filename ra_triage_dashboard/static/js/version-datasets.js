/* Version worksets own their requests; global Review/GT bootstrap is independent. */
const versionDatasetState = {active:false,seq:0,controller:null,timer:null,page:1,dataset:'',mode:'targets',sort:'added',query:'',date:'',assignee:'',reviewStatus:'all',teStatus:'all',media:'bev',mediaSeq:0,data:null,members:null,gridKey:'',bound:false,observer:null,imageEpoch:0};
function versionDatasetTime(value) {
  if (!value) return '—';
  const n=Number(value),d=new Date(Number.isFinite(n)&&n>0 ? (n<1e11?n*1000:n) : value);
  return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat(i18nLocale()==='en'?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);
}
function versionDatasetStatus(state) {
  return ({ready:uiText('待处理','Queued'),running:uiText('推理中','Inferring'),published:uiText('已回刷','Published'),inferred:uiText('已推理','Inferred'),waiting_metadata:uiText('待齐备','Awaiting source'),retry_wait:uiText('等待重试','Retry pending'),excluded:uiText('已过滤','Excluded'),needs_attention:uiText('需处理','Needs attention'),identity_conflict:uiText('信息冲突','Identity conflict')})[state]||state;
}
function versionDatasetRoute() {
  const p=new URLSearchParams(location.search),s=versionDatasetState;
  s.dataset=p.get('dataset')||s.dataset;s.mode=p.get('mode')||'targets';s.sort=p.get('sort')||'added';s.query=p.get('q')||'';s.page=Math.max(1,Number(p.get('page'))||1);s.date=p.get('date')||'';s.teStatus=p.get('te_status')||'all';s.media=p.get('media')||'bev';s.assignee=p.get('assignee')||'';s.reviewStatus=p.get('review_status')||'all';
}
function versionDatasetRouteOptions(options={}) {
  const p=location.pathname.replace(/\/$/,'').endsWith('/version-datasets')?new URLSearchParams(location.search):new URLSearchParams();
  return Object.fromEntries(['dataset','mode','sort','q','page','date','te_status','media','assignee','review_status'].map(k=>[k,options[k]??p.get(k)??'']));
}
function clearVersionDatasetMembers(){
  const s=versionDatasetState;s.members=null;s.gridKey='';s.observer?.disconnect();s.observer=null;s.imageEpoch++;
  $('#versionDatasetGrid').replaceChildren();$('#versionDatasetPageLabel').textContent='';
  $('#versionDatasetPrev').disabled=true;$('#versionDatasetNext').disabled=true;
  $('#versionDatasetBatches').textContent='';$('#versionDatasetExport').hidden=true;
  $('#versionTERate').textContent='—';$('#versionTESource').textContent=uiText('读取中…','Loading…');
  for(const id of ['versionTEStatusChart','versionTEDistribution','versionTEDailyChart','versionCompositionBar','versionCompositionLegend'])$('#'+id).replaceChildren();
  $('#versionTEDonut').classList.add('is-empty');$('#versionTEDonut').style.setProperty('--te-filled','0%');$('#versionTEDonut').style.setProperty('--te-known','0%');
  $('#versionDatasetDate').disabled=true;
}
function setVersionDatasetsActive(active) {
  const s=versionDatasetState;
  if(active&&s.active){
    const before=JSON.stringify([s.dataset,s.mode,s.sort,s.query,s.page,s.date,s.teStatus,s.media,s.assignee,s.reviewStatus]);versionDatasetRoute();
    if(before===JSON.stringify([s.dataset,s.mode,s.sort,s.query,s.page,s.date,s.teStatus,s.media,s.assignee,s.reviewStatus]))return;
    clearVersionDatasetMembers();
  }
  if(!active)closeVersionTEInfo();
  s.active=active;s.seq++;s.controller?.abort();clearTimeout(s.timer);
  s.observer?.disconnect();s.observer=null;s.imageEpoch++;
  if(active){bindVersionDatasets();versionDatasetRoute();void loadVersionDatasets();}
}
function versionDatasetChange(patch) {
  const s=versionDatasetState;if(patch.dataset&&patch.dataset!==s.dataset)patch.date='';if(patch.dataset==='historical-0821'){patch.assignee='';patch.reviewStatus='all';}Object.assign(s,{page:1},patch);s.page=Math.max(1,Number(s.page)||1);clearVersionDatasetMembers();
  const u=new URL(location.href);
  for(const [key,value] of Object.entries({dataset:s.dataset,mode:s.mode,sort:s.sort,q:s.query,page:s.page,date:s.date,te_status:s.teStatus,media:s.media,assignee:s.assignee,review_status:s.reviewStatus}))value?u.searchParams.set(key,String(value)):u.searchParams.delete(key);
  history.pushState({},'',u);void loadVersionDatasets();
}
function renderVersionDatasets({force=false}={}) {
  const s=versionDatasetState;if(!s.active)return;
  const el=$('#versionDatasetsPage');
  el.querySelectorAll('[data-zh]').forEach(e=>e.textContent=uiText(e.dataset.zh,e.dataset.en));
  el.querySelectorAll('[data-label-zh]').forEach(e=>e.setAttribute('aria-label',uiText(e.dataset.labelZh,e.dataset.labelEn)));
  if(!s.data)return;
  const picker=$('#versionDatasetPicker');
  const options=s.data.items.map(x=>`<option value="${escapeHtml(x.id)}">${escapeHtml(x.release_family.slice(4))} · ${x.targets??'—'} ${uiText('复核案例','review cases')}</option>`).join('');
  if(picker.innerHTML!==options)picker.innerHTML=options;picker.value=s.dataset;
  $('#versionDatasetMode').value=s.mode;$('#versionDatasetSort').value=s.sort;$('#versionDatasetSearch').value=s.query;$('#versionDatasetTEStatus').value=s.teStatus;$('#versionDatasetMedia').value=s.media;$('#versionDatasetReviewStatus').value=s.reviewStatus;
  enhanceDashboardSelects(el);
  const current=s.data.items.find(x=>x.id===s.dataset);
  if(!current){$('#versionDatasetSummary').textContent=uiText('等待首次导入','Awaiting first import');$('#versionDatasetGrid').replaceChildren();return;}
  $('#versionDatasetOwner').disabled=Boolean(current.historical);$('#versionDatasetReviewStatus').disabled=Boolean(current.historical);enhanceNativeUiSelect($('#versionDatasetOwner'));enhanceNativeUiSelect($('#versionDatasetReviewStatus'));
  const states=current.states||{};
  $('#versionDatasetSummary').innerHTML=[
    [uiText('候选案例','Candidates'),current.total],
    [uiText('已回刷','Published'),current.historical?'—':states.published||0],
    [uiText('复核目标','Review targets'),current.targets??'—'],
    [uiText('待齐备','Awaiting source'),current.historical?'—':states.waiting_metadata||0],
  ].map(([label,n])=>`<div><span>${label}</span><strong>${n}</strong></div>`).join('');

  $('#versionDatasetHistory').hidden=Boolean(current.historical);
  const m=s.members;if(!m||m.dataset_id!==s.dataset)return;
  renderVersionComposition(m);renderVersionTE(m);
  const owner=$('#versionDatasetOwner');const ownerOptions=`<option value="">${uiText('全部负责人','All assignees')}</option>`+(m.assignees||[]).map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');
  if(owner.innerHTML!==ownerOptions)owner.innerHTML=ownerOptions;owner.value=s.assignee;enhanceNativeUiSelect(owner);
  const date=$('#versionDatasetDate');date.hidden=Boolean(current.historical);date.disabled=false;
  const dateOptions=`<option value="">${uiText('全部发生日 · CST','All occurrence dates · CST')}</option>`+(m.date_options||[]).map(d=>`<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('');
  if(date.innerHTML!==dateOptions)date.innerHTML=dateOptions;date.value=s.date;enhanceNativeUiSelect(date);
  const gridKey=JSON.stringify([s.dataset,s.mode,s.sort,s.query,s.media,s.date,s.teStatus,s.assignee,s.reviewStatus,m.items,state.uiLanguage]);
  if(force||gridKey!==s.gridKey){
    s.gridKey=gridKey;s.observer?.disconnect();s.observer=null;s.imageEpoch++;
    $('#versionDatasetGrid').innerHTML=m.items.map(row=>{
      const binding=row.binding||{},pred=row.prediction;
      const url=binding.run_id?pageUrl('review',{issue:row.issue_id,runId:binding.run_id,workSplitId:binding.campaign_id||'',workflowMode:'model_review_and_case_label',comparisonStatus:'all',baselines:['version-'+current.release_family]}):'';
      const confidence=pred?.model_confidence;
      return `<article class="issue-card version-card"><button type="button" class="issue-card-open" data-version-open="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(row.issue_id)} ${uiText('查看媒体','View media')}"></button><div class="issue-thumbnail"><div class="issue-thumbnail-placeholder"><span>${s.media.toUpperCase()}</span><small>${uiText('媒体待就绪','Media pending')}</small></div>${row.is_target?`<img data-src="${escapeHtml(withBase('/api/case-thumbnails/'+encodeURIComponent(row.issue_id)+'?kind='+s.media))}" loading="lazy" decoding="async" alt="${escapeHtml(row.issue_id)} ${s.media.toUpperCase()}" class="is-loading" />`:''}</div><div class="issue-card-body"><div class="issue-card-heading">${url?`<a class="issue-id" href="${escapeHtml(url)}">${escapeHtml(row.issue_id)} ↗</a>`:`<a class="issue-id" href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(row.issue_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.issue_id)} ↗</a>`}<span class="muted">${row.is_sample?uiText('抽样','Sample'):row.is_low?uiText('低置信','Low'):''}</span></div><div class="version-card-line"><span>${escapeHtml(pred?.model_label||(current.historical?uiText('历史固定集','Frozen set'):versionDatasetStatus(row.state)))}</span><span class="muted">${confidence==null?'':(confidence*100).toFixed(1)+'%'}</span></div><div class="version-card-line muted"><span>${escapeHtml(binding.assignee||(current.historical?'—':uiText('未分配','Unassigned')))}</span><span>${escapeHtml(row.trigger||'—')}</span></div><div class="version-joint-result muted">${row.is_target&&!current.historical?row.review_submitted?uiText('联合复核已完成','Combined review completed'):uiText('联合复核待处理','Combined review pending'):''}</div><div class="version-te-result" data-status="${escapeHtml(row.te_status)}">${escapeHtml(versionTEBadge(row))}</div><div class="version-card-time muted">${uiText('入库','Added')} ${versionDatasetTime(row.first_seen)} · ${uiText('发生','Occurred')} ${(row.issue_time||row.ra_start_timestamp?versionDatasetTime(row.issue_time||row.ra_start_timestamp):escapeHtml(row.date||'—'))} CST</div></div></article>`;
    }).join('')||`<div class="no-asset issue-grid-empty">${uiText('该筛选暂无案例','No cases in this view')}</div>`;

  }
  observeVersionDatasetImages();
  $('#versionDatasetPageLabel').textContent=`${m.page} / ${Math.max(1,Math.ceil(m.total/m.page_size))} · ${m.total}`;
  $('#versionDatasetPrev').disabled=m.page<=1;$('#versionDatasetNext').disabled=m.page*m.page_size>=m.total;
}
function observeVersionDatasetImages(){
  const s=versionDatasetState;if(s.observer)return;
  let queue=[],running=0;const epoch=s.imageEpoch;
  const drain=()=>{
    if(!s.active||epoch!==s.imageEpoch)return;
    while(queue.length&&running<4){
      const img=queue.shift();if(!img.isConnected||img.getAttribute('src'))continue;
      running++;
      const done=()=>{running--;delete img.dataset.src;drain();};
      img.addEventListener('load',()=>{img.classList.remove('is-loading');img.hidden=false;img.previousElementSibling.hidden=true;done();},{once:true});
      img.addEventListener('error',()=>{img.hidden=true;done();},{once:true});img.src=img.dataset.src;
    }
  };
  s.observer=new IntersectionObserver(entries=>{if(!s.active||epoch!==s.imageEpoch)return;for(const e of entries)if(e.isIntersecting){s.observer.unobserve(e.target);queue.push(e.target);}drain();},{rootMargin:'120px'});
  $('#versionDatasetGrid').querySelectorAll('img[data-src]').forEach(img=>s.observer.observe(img));
}
async function loadVersionDatasetBatches(){
  const s=versionDatasetState,dataset=s.dataset;
  if(!s.active||!dataset||dataset==='historical-0821'||!$('#versionDatasetHistory').open)return;
  try{const b=await api(`/api/version-datasets/${encodeURIComponent(dataset)}/batches`,{signal:s.controller?.signal});
    if(!s.active||dataset!==s.dataset)return;
    $('#versionDatasetBatches').innerHTML=b.items.map(x=>`<div><time>${versionDatasetTime(x.created_at)} CST</time> · ${uiText('新增目标','Targets added')} ${x.target_added||0} · ${uiText('候选','Candidates')} +${x.added} · ${uiText('更新','Updated')} ${x.changed}</div>`).join('')||uiText('暂无记录','No records');
  }catch(e){if(e.name!=='AbortError')$('#versionDatasetBatches').textContent=uiText('记录读取失败','History unavailable');}
}
async function loadVersionDatasets(){
  const s=versionDatasetState;if(!s.active||document.hidden)return;
  clearTimeout(s.timer);const seq=++s.seq;s.controller?.abort();const controller=new AbortController();s.controller=controller;
  const valid=()=>s.active&&seq===s.seq&&!controller.signal.aborted;
  $('#versionDatasetError').textContent=uiText('读取中…','Loading…');$('#versionDatasetGrid').setAttribute('aria-busy','true');
  try{
    const data=await api('/api/version-datasets?include_legacy=true',{signal:controller.signal});if(!valid())return;
    s.data=data;
    if(!data.items.some(x=>x.id===s.dataset))s.dataset=data.items.find(x=>x.targets>0)?.id||data.items[0]?.id||'';
    renderVersionDatasets();
    if(s.dataset){
      const p=new URLSearchParams({page:s.page,page_size:24,mode:s.mode,sort:s.sort,q:s.query,date:s.date,te_status:s.teStatus,assignee:s.assignee,review_status:s.reviewStatus});
      const members=await api(`/api/version-datasets/${encodeURIComponent(s.dataset)}/workbench?${p}`,{signal:controller.signal});
      if(!valid())return;s.members=members;renderVersionDatasets();void loadVersionDatasetBatches();
    }
    $('#versionDatasetError').textContent='';
  }catch(error){if(valid())$('#versionDatasetError').textContent=uiText('读取失败，保留上次结果。可点击刷新重试。','Read failed. Previous results retained; refresh to retry.');}
  finally{if(valid()){$('#versionDatasetGrid').setAttribute('aria-busy','false');if(!document.hidden)s.timer=setTimeout(loadVersionDatasets,30000);}}
}
function bindVersionDatasets(){
  const s=versionDatasetState;if(s.bound)return;s.bound=true;bindVersionTEInfo();
  for(const [id,key] of [['versionDatasetPicker','dataset'],['versionDatasetMode','mode'],['versionDatasetSort','sort'],['versionDatasetDate','date'],['versionDatasetTEStatus','teStatus'],['versionDatasetMedia','media'],['versionDatasetOwner','assignee'],['versionDatasetReviewStatus','reviewStatus']])$('#'+id).addEventListener('change',e=>versionDatasetChange({[key]:e.target.value}));
  $('#versionDatasetsPage').addEventListener('click',e=>{const status=e.target.closest('[data-version-te-status]');if(status){versionDatasetChange({teStatus:s.teStatus===status.dataset.versionTeStatus?'all':status.dataset.versionTeStatus});return;}const day=e.target.closest('[data-version-date]');if(day){versionDatasetChange({date:day.dataset.versionDate});return;}const open=e.target.closest('[data-version-open]');if(open)void openVersionDatasetMedia(open.dataset.versionOpen);});
  $('#versionDatasetSearchForm').addEventListener('submit',e=>{e.preventDefault();versionDatasetChange({query:$('#versionDatasetSearch').value.trim()});});
  $('#versionDatasetRefresh').addEventListener('click',()=>loadVersionDatasets());
  $('#versionDatasetPrev').addEventListener('click',()=>versionDatasetChange({page:s.page-1}));$('#versionDatasetNext').addEventListener('click',()=>versionDatasetChange({page:s.page+1}));
  $('#versionDatasetHistory').addEventListener('toggle',()=>{void loadVersionDatasetBatches();});
  document.addEventListener('visibilitychange',()=>{if(!s.active)return;clearTimeout(s.timer);if(document.hidden){s.seq++;s.controller?.abort();s.observer?.disconnect();s.observer=null;s.imageEpoch++;}else void loadVersionDatasets();});
}

function versionTEBadge(row){
  return row.te_status==='filled'?`TE ${row.te_value}`:row.te_status==='unfilled'?uiText('TE 待标','TE pending'):row.te_status==='not_target'?uiText('未纳入复核','Outside review set'):uiText('TE 未知','TE unknown');
}
function renderVersionComposition(m){
  const c=m.composition;if(!c)return;
  const labels={low:uiText('低置信','Low confidence'),sample:uiText('抽样','Sample'),other:uiText('其他','Other')};
  $('#versionDatasetCounts').textContent=m.dataset.historical?uiText(`固定目标集 ${c.total}`,`Frozen targets ${c.total}`):uiText(`已推理准入 ${c.total} · 待处理 ${c.pending} · 已过滤 ${c.excluded}`,`Inferred and admitted ${c.total} · Pending ${c.pending} · Excluded ${c.excluded}`);
  const bar=$('#versionCompositionBar');bar.classList.toggle('is-empty',!c.total);
  bar.setAttribute('aria-label',c.groups.map(g=>`${labels[g.key]} ${g.count} (${(100*g.ratio).toFixed(1)}%)`).join(', '));
  bar.innerHTML=c.groups.map(g=>`<i class="version-reason-${g.key}" style="width:${100*g.ratio}%"></i>`).join('');
  $('#versionCompositionLegend').innerHTML=c.groups.map(g=>`<div><i class="te-swatch version-reason-${g.key}"></i><span>${labels[g.key]}</span><strong>${g.count}</strong><small>${c.total?(100*g.ratio).toFixed(1)+'%':'—'}</small></div>`).join('');
}

function renderVersionTE(m){
  const s=versionDatasetState,te=m.te,n=te.summary;
  const filled=n.total?100*n.filled/n.total:0,known=n.total?100*(n.filled+n.unfilled)/n.total:0;
  const donut=$('#versionTEDonut');donut.style.setProperty('--te-filled',`${filled}%`);donut.style.setProperty('--te-known',`${known}%`);donut.classList.toggle('is-empty',!n.total);
  donut.setAttribute('aria-label',uiText(`TE 已标 ${n.filled}，共 ${n.total}`,`TE filled ${n.filled} of ${n.total}`));
  $('#versionTERate').textContent=n.total?`${filled.toFixed(1)}%`:'—';
  $('#versionTEStatusChart').innerHTML=dailyReviewStatusRows(n).map(([key,label,count])=>`<button type="button" class="te-legend-item" data-version-te-status="${key}" aria-pressed="${s.teStatus===key}"><i class="te-swatch te-${key}"></i><span>${label}</span><strong>${count} / ${n.total}</strong></button>`).join('');
  $('#versionTESource').textContent=`${te.source_status==='ready'?uiText('最近核对','Last checked'):te.source_status==='stale'?uiText('观测过期','Stale observation'):uiText('同步异常 · 未知单列','Sync unavailable · Unknown shown separately')} ${versionDatasetTime(te.last_success_at)} CST${te.observed_changes?uiText(` · 本轮标注变化 ${te.observed_changes.te}`,` · Label changes this check ${te.observed_changes.te}`):''}`;
  $('#versionTESource').classList.toggle('te-warning',te.source_status!=='ready');
  $('#versionTEDistribution').innerHTML=[...te.distribution].sort((a,b)=>b.count-a.count).map(r=>`<div class="te-result-row"><div><span>${escapeHtml(String(r.value))}</span><strong>${r.count}</strong></div><div class="te-result-track"><i style="width:${n.filled?100*r.count/n.filled:0}%"></i></div></div>`).join('')||`<p class="te-chart-empty">${uiText('该范围暂无已标结果','No filled TE results in this scope')}</p>`;
  $('#versionTEDays').hidden=m.dataset.historical;
  const dailyMarkup=te.daily.map(day=>{const d=day.summary;return `<button type="button" class="te-day" data-version-date="${escapeHtml(day.date)}" aria-pressed="${day.date===s.date}" aria-label="${escapeHtml(day.date)} · ${d.filled}/${d.total}"><strong>${d.total?(100*d.rate).toFixed(1)+'%':'—'}</strong><span class="te-day-stack">${dailyReviewStatusRows(d).map(([k,,count])=>`<i class="te-${k}" style="height:${100*count/d.total}%"></i>`).join('')}</span><span>${escapeHtml(day.date.slice(5).replace('-','/'))}</span><small>${d.filled}/${d.total}</small></button>`;}).join('');
  const dailyChart=$('#versionTEDailyChart');if(dailyChart.innerHTML!==dailyMarkup)dailyChart.innerHTML=dailyMarkup||`<p class="te-chart-empty">${uiText('暂无可用发生日','No occurrence dates available')}</p>`;
  const params=new URLSearchParams({mode:s.mode,q:s.query,sort:s.sort,date:s.date,te_status:s.teStatus,revision:m.snapshot_revision,assignee:s.assignee,review_status:s.reviewStatus});
  const exp=$('#versionDatasetExport');exp.hidden=false;exp.href=withBase(`/api/version-datasets/${encodeURIComponent(s.dataset)}/workbench.csv?${params}`);
}
async function openVersionDatasetMedia(iid,preferredKind=''){
  const s=versionDatasetState,seq=++s.mediaSeq,dataset=s.dataset,kind=preferredKind||s.media,context=capturePageContext();
  const request=++state.media.requestSeq;
  try{
    const data=await api(`/api/cases/${encodeURIComponent(iid)}/media`,{signal:s.controller?.signal});
    if(!s.active||seq!==s.mediaSeq||dataset!==s.dataset||request!==state.media.requestSeq||!isPageContextCurrent(context))return;
    const frames=kind==='camera'?data.camera?.frames:data.assets?.frames;
    if(!frames?.length&&!preferredMediaKind(data)){showToast(uiText('媒体待就绪','Media pending'));return;}
    openMedia(kind,heroFrameIndex(frames||[]),{caseData:{...data,gt_label:'',reference_media:true,te_observation:s.members?.items.find(r=>r.issue_id===iid)}});
  }catch(e){if(s.active&&seq===s.mediaSeq)showToast(uiText('媒体暂不可用，请稍后重试','Media unavailable; try again'),true);}
}

function closeVersionTEInfo(){
  const help=$('#versionTEInfo');if(!help)return;
  help.classList.remove('is-open');help.classList.add('is-dismissed');$('#versionTEInfoButton').setAttribute('aria-expanded','false');
}
function bindVersionTEInfo(){
  const help=$('#versionTEInfo'),button=$('#versionTEInfoButton'),tip=$('#versionTEInfoTooltip');
  const show=()=>{
    help.classList.remove('is-dismissed');help.classList.add('is-open');button.setAttribute('aria-expanded','true');
    const r=button.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;
    tip.style.left=`${Math.max(12,Math.min(r.left,innerWidth-w-12))}px`;
    tip.style.top=`${Math.max(12,r.bottom+h+8<=innerHeight?r.bottom+6:r.top-h-6)}px`;
  };
  help.addEventListener('mouseenter',show);
  help.addEventListener('mouseleave',()=>{if(!help.contains(document.activeElement))closeVersionTEInfo();});
  help.addEventListener('focusin',show);
  help.addEventListener('focusout',e=>{if(!help.contains(e.relatedTarget))closeVersionTEInfo();});
  button.addEventListener('click',show);
  document.addEventListener('pointerdown',e=>{if(!help.contains(e.target))closeVersionTEInfo();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&help.classList.contains('is-open')){e.preventDefault();closeVersionTEInfo();}});
  window.addEventListener('resize',closeVersionTEInfo);
  window.addEventListener('scroll',closeVersionTEInfo,{capture:true,passive:true});
}
