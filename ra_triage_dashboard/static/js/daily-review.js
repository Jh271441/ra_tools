/* Read-only TE observations. Scope owns every request, thumbnail and timer. */
const dailyReviewState = {seq:0, imageEpoch:0, timer:null, controller:null, observer:null, images:new Set(), urls:new Set(), data:null, key:'', active:false, bound:false};
function dailyReviewRouteOptions(options = {}) {
  const p = new URLSearchParams(location.search);
  const here = location.pathname.replace(/\/$/,'').endsWith('/daily-review');
  const get = (k,d) => options[k] ?? (here ? p.get(k) : null) ?? d;
  return {dataset:get('dataset','1009'),date:get('date',''),reason:get('reason','all'),te_status:get('te_status','all'),media:get('media','bev'),page:Math.max(1,Number(get('page',1))||1)};
}
function dailyReviewParams(scope) {
  return new URLSearchParams(Object.entries(scope).filter(([k,v]) => k !== 'media' && v !== ''));
}
function dailyReviewBadge(row) {
  return row.te_status === 'filled' ? `TE ${row.te_value}` : row.te_status === 'unfilled' ? uiText('TE 待标','TE pending') : uiText('TE 未知','TE unknown');
}
function dailyReviewStatusRows(n) {
  return [['filled',uiText('已标','Filled'),n?.filled],['unfilled',uiText('待标','Pending'),n?.unfilled],['unknown',uiText('未知','Unknown'),n?.unknown]];
}
function renderDailyReviewCharts(data) {
  const n=data.summary,scope=dailyReviewRouteOptions();
  const donut=$('#dailyReviewDonut'),filled=n?.total ? 100*n.filled/n.total : 0, pending=n?.total ? 100*n.unfilled/n.total : 0;
  donut.style.setProperty('--te-filled',`${filled}%`);donut.style.setProperty('--te-known',`${filled+pending}%`);
  donut.classList.toggle('is-empty',!n?.total);
  donut.setAttribute('aria-label',n ? uiText(`已标 ${n.filled}，待标 ${n.unfilled}，未知 ${n.unknown}，共 ${n.total}`,`Filled ${n.filled}, pending ${n.unfilled}, unknown ${n.unknown}, total ${n.total}`) : uiText('等待数据','Awaiting data'));
  $('#dailyReviewStatusChart').innerHTML=dailyReviewStatusRows(n).map(([key,label,value])=>`<button type="button" class="te-legend-item" data-te-status="${key}" aria-pressed="${scope.te_status===key}"><i class="te-swatch te-${key}"></i><span>${label}</span><strong>${value??'—'}</strong></button>`).join('');
  const daily=$('#dailyReviewDailyPanel');daily.hidden=data.scope.dataset!=='1009';
  const days=data.daily_overview || [];
  $('#dailyReviewDailyChart').innerHTML=days.map(day=>{
    const n=day.summary,selected=day.date===data.scope.date;
    const status=day.source_status==='ready'?'':day.source_status==='stale'?uiText('过期','Stale'):uiText('同步异常','Sync error');
    const label=`${day.date} · ${n ? `${n.filled}/${n.total}` : uiText('暂无观测','Unavailable')}${status ? ` · ${status}` : ''}`;
    const bars=n?.total ? dailyReviewStatusRows(n).map(([key,,count])=>`<i class="te-${key}" style="height:${100*count/n.total}%"></i>`).join('') : '<i class="te-no-data"></i>';
    return `<button type="button" class="te-day" data-te-date="${escapeHtml(day.date)}" aria-pressed="${selected}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"><strong>${n?.total ? (n.rate*100).toFixed(0)+'%' : '—'}</strong><span class="te-day-stack" aria-hidden="true">${bars}</span><span>${escapeHtml(day.date.slice(5).replace('-','/'))}</span><small>${n ? `${n.filled}/${n.total}` : '—'}</small>${status ? `<small class="te-warning">${status}</small>` : ''}</button>`;
  }).join('') || `<p class="muted">${uiText('等待每日观测','Awaiting daily observations')}</p>`;
  const results=[...data.result_distribution].sort((a,b)=>b.count-a.count);
  $('#dailyReviewDistribution').innerHTML=results.map(row=>`<div class="te-result-row"><div><span title="${escapeHtml(String(row.value))}">${escapeHtml(String(row.value))}</span><strong>${row.count}<small> · ${n?.filled ? (row.count/n.filled*100).toFixed(0) : 0}%</small></strong></div><div class="te-result-track"><i style="width:${n?.filled ? row.count/n.filled*100 : 0}%"></i></div></div>`).join('') || `<p class="te-chart-empty">${uiText(n ? '该范围暂无已标结果' : '等待首次同步',n ? 'No filled results in this scope' : 'Awaiting first sync')}</p>`;
  $('#dailyReviewGalleryCount').textContent=uiText(`${data.total} 个案例 · 状态筛选仅影响 Gallery`,`${data.total} cases · Status filters affect Gallery only`);
}
function stopDailyReviewImages() {
  dailyReviewState.imageEpoch++;
  dailyReviewState.observer?.disconnect();
  dailyReviewState.images.forEach(c=>c.abort());dailyReviewState.images.clear();
  dailyReviewState.urls.forEach(u=>URL.revokeObjectURL(u));dailyReviewState.urls.clear();
}
function setDailyReviewActive(active) {
  dailyReviewState.active=active;dailyReviewState.seq++;
  dailyReviewState.controller?.abort();clearTimeout(dailyReviewState.timer);stopDailyReviewImages();
  if (!active) return;
  dailyReviewState.data=null;
  bindDailyReview();scheduleDailyReview();
}
function scheduleDailyReview() {
  clearTimeout(dailyReviewState.timer);
  if (dailyReviewState.active && !document.hidden) dailyReviewState.timer=setTimeout(()=>loadDailyReview(),30000);
}
function dailyReviewChange(patch) {
  const scope={...dailyReviewRouteOptions(),page:1,...patch};
  if (patch.dataset) scope.date='';
  const url=pageUrl('daily-review',scope);
  history.pushState({},'',url);
  void loadDailyReview();
}
async function loadDailyReview() {
  if (!dailyReviewState.active || document.hidden) return;
  const scope=dailyReviewRouteOptions(),key=JSON.stringify(scope),seq=++dailyReviewState.seq;
  const context=capturePageContext();
  dailyReviewState.controller?.abort();
  const controller=new AbortController();dailyReviewState.controller=controller;
  if (dailyReviewState.key!==key) {
    dailyReviewState.data=null;stopDailyReviewImages();$('#dailyReviewGrid').replaceChildren();
    $('#dailyReviewScope').textContent='';$('#dailyReviewProgress').textContent='TE — / —';$('#dailyReviewRate').textContent='—';
    $('#dailyReviewCounts').textContent='';$('#dailyReviewBar').value=0;$('#dailyReviewExport').hidden=true;
    for(const id of ['dailyReviewStatusChart','dailyReviewDailyChart','dailyReviewDistribution','dailyReviewGalleryCount']) $('#'+id).replaceChildren();
    $('#dailyReviewDonut').classList.toggle('is-empty',true);
  }
  dailyReviewState.key=key;
  $('#dailyReviewSource').textContent=uiText('读取快照…','Reading snapshot…');
  try {
    const data=await api(`/api/daily-review/cases?${dailyReviewParams(scope)}&include_overview=true`,{signal:controller.signal});
    if (seq!==dailyReviewState.seq || !isPageContextCurrent(context)) return;
    const previous=dailyReviewState.data;dailyReviewState.data=data;
    renderDailyReview({keepImages:previous?.snapshot_revision===data.snapshot_revision});
  } catch(error) {
    if (seq!==dailyReviewState.seq || controller.signal.aborted || !isPageContextCurrent(context)) return;
    $('#dailyReviewSource').textContent=uiText('同步异常 · 保留上次观测','Sync unavailable · Previous observation retained');
    if (!dailyReviewState.data) $('#dailyReviewProgress').textContent=uiText('TE — / —','TE — / —');
  } finally {if(seq===dailyReviewState.seq) scheduleDailyReview();}
}
function renderDailyReview({keepImages=false}={}) {
  if (!dailyReviewState.active) return;
  const s=dailyReviewRouteOptions(),data=dailyReviewState.data;
  $('#dailyReviewPage').querySelectorAll('[data-zh]').forEach(el=>{el.textContent=uiText(el.dataset.zh,el.dataset.en);});
  for (const [id,key] of [['dailyReviewReason','reason'],['dailyReviewStatus','te_status'],['dailyReviewMedia','media']]) $('#'+id).value=s[key];
  document.querySelectorAll('[data-te-dataset]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.teDataset===s.dataset)));
  const date=$('#dailyReviewDate');date.hidden=s.dataset==='0821';
  $('#dailyReviewDateLabel').hidden=date.hidden;
  if(!data)return;
  date.innerHTML=data.date_options.map(d=>`<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('');date.value=data.scope.date || '';
  $('#dailyReviewScope').textContent=data.scope.dataset==='0821' ? uiText('0821 · 历史固定集','0821 · Frozen set') : `1009 · ${data.scope.date || '—'} · CST`;
  const n=data.summary;
  $('#dailyReviewProgress').textContent=n ? `TE ${n.filled} / ${n.total}` : 'TE — / —';
  $('#dailyReviewRate').textContent=n ? (n.total ? `${(n.rate*100).toFixed(1)}%` : uiText('无目标','No targets')) : '—';
  $('#dailyReviewBar').value=n?.rate || 0;
  $('#dailyReviewCounts').textContent=n ? uiText(`低置信 ${n.reasons.low||0} · 抽样 ${n.reasons.sample||0} · 未知 ${n.unknown}`,`Low ${n.reasons.low||0} · Sample ${n.reasons.sample||0} · Unknown ${n.unknown}`) : '';
  const at=data.last_success_at ? new Intl.DateTimeFormat(i18nLocale()==='en'?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(data.last_success_at)) : '—';
  const status={ready:uiText('观测于','Observed'),stale:uiText('数据过期','Stale'),error:uiText('同步异常','Sync error'),unavailable:uiText('等待首次同步','Awaiting first sync')}[data.source_status] || '';
  $('#dailyReviewSource').textContent=`${status} ${at} · CST`;
  $('#dailyReviewSource').classList.toggle('te-warning',data.source_status!=='ready');
  renderDailyReviewCharts(data);
  $('#dailyReviewCoverage').textContent=n ? uiText(`读取覆盖率 ${n.total ? (n.coverage*100).toFixed(1)+'%' : '—'}；状态筛选不改变进度分母。`,`Read coverage ${n.total ? (n.coverage*100).toFixed(1)+'%' : '—'}; status filters do not change the denominator.`) : '';
  const exp=$('#dailyReviewExport');exp.hidden=!data.snapshot_revision;
  exp.href=withBase(`/api/daily-review/export?${dailyReviewParams({...s,date:data.scope.date||''})}&revision=${encodeURIComponent(data.snapshot_revision)}`);
  const count=Math.max(1,Math.ceil(data.total/data.size));
  $('#dailyReviewPageLabel').textContent=`${data.page} / ${count} · ${data.total}`;
  $('#dailyReviewPrev').disabled=data.page<=1;$('#dailyReviewNext').disabled=data.page>=count;
  if(keepImages) return;
  stopDailyReviewImages();
  const grid=$('#dailyReviewGrid');
  grid.innerHTML=data.items.map(row=>`<article class="issue-card te-card" data-te-id="${escapeHtml(row.issue_id)}">
    <button type="button" class="issue-card-open" data-te-open="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(row.issue_id)} ${escapeHtml(uiText('查看媒体','View media'))}"></button>
    <div class="issue-thumbnail"><img alt="${escapeHtml(row.issue_id)} ${escapeHtml(s.media)}" hidden /><div class="issue-thumbnail-placeholder te-placeholder"><span>${escapeHtml(s.media.toUpperCase())}</span><small>${uiText('图片待就绪','Image pending')}</small></div></div>
    <div class="issue-card-body"><div class="issue-card-heading"><a class="issue-id" href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(row.issue_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.issue_id)} ↗</a><span class="te-reason">${row.reason==='low'?uiText('低置信','Low'):uiText('抽样','Sample')}</span></div>
    <div class="issue-card-labels"><span class="te-result" data-status="${escapeHtml(row.te_status)}" title="${escapeHtml(dailyReviewBadge(row))}">${escapeHtml(dailyReviewBadge(row))}</span><button type="button" class="te-retry" data-te-retry="${escapeHtml(row.issue_id)}" hidden>${uiText('重试图片','Retry image')}</button></div></div>
    </article>`).join('') || `<div class="no-asset issue-grid-empty">${uiText(n ? '此筛选下暂无案例' : '等待 TE 数据同步',n ? 'No cases in this filter' : 'Awaiting TE observations')}</div>`;
  let queue=[],running=0;const seq=dailyReviewState.imageEpoch;
  const drain=()=>{while(queue.length && running<4){const card=queue.shift();running++;loadDailyReviewImage(card,s.media,seq).finally(()=>{running--;if(seq===dailyReviewState.imageEpoch)drain();});}};
  dailyReviewState.observer=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting){dailyReviewState.observer?.unobserve(e.target);queue.push(e.target);}}drain();},{rootMargin:'0px'});
  grid.querySelectorAll('.te-card').forEach(c=>dailyReviewState.observer.observe(c));
}
async function loadDailyReviewImage(card,kind,seq) {
  const controller=new AbortController();dailyReviewState.images.add(controller);
  try {
    const url=withBase(`/api/case-thumbnails/${encodeURIComponent(card.dataset.teId)}?kind=${kind}`);
    const response=await fetch(url,{signal:controller.signal,credentials:'same-origin'});
    if(!response.ok)throw new Error('image_unavailable');
    const blob=await response.blob();
    if(seq!==dailyReviewState.imageEpoch || !card.isConnected)return;
    const src=URL.createObjectURL(blob);dailyReviewState.urls.add(src);
    const img=card.querySelector('img');img.src=src;img.hidden=false;
    card.querySelector('.te-placeholder').hidden=true;card.querySelector('.te-retry').hidden=true;
  } catch(error) {if(!controller.signal.aborted && seq===dailyReviewState.imageEpoch && card.isConnected)card.querySelector('.te-retry').hidden=false;}
  finally{dailyReviewState.images.delete(controller);}
}
async function openDailyReviewMedia(iid,preferredKind='') {
  const context=capturePageContext(),seq=dailyReviewState.seq,kind=preferredKind || dailyReviewRouteOptions().media;
  const controller=dailyReviewState.controller;
  const mediaRequest=++state.media.requestSeq;
  try {
    const data=await api(`/api/cases/${encodeURIComponent(iid)}/media`,{signal:controller?.signal});
    if(seq!==dailyReviewState.seq || mediaRequest!==state.media.requestSeq || !isPageContextCurrent(context))return;
    const frames=kind==='camera'?data.camera?.frames:data.assets?.frames;
    if(!frames?.length && !preferredMediaKind(data)){showToast(uiText('图片待就绪','Image pending'));return;}
    openMedia(kind,heroFrameIndex(frames||[]),{caseData:{...data,gt_label:'',reference_media:true,te_observation:dailyReviewState.data?.items.find(r=>r.issue_id===iid)}});
  }catch(error){if(seq===dailyReviewState.seq && isPageContextCurrent(context))showToast(uiText('媒体暂不可用，请稍后重试','Media unavailable; try again'),true);}
}
function bindDailyReview() {
  if(dailyReviewState.bound)return;dailyReviewState.bound=true;
  $('#dailyReviewPage').addEventListener('click',event=>{
    const day=event.target.closest('[data-te-date]');if(day){dailyReviewChange({date:day.dataset.teDate});return;}
    const status=event.target.closest('[data-te-status]');if(status){dailyReviewChange({te_status:dailyReviewRouteOptions().te_status===status.dataset.teStatus?'all':status.dataset.teStatus});return;}
    const dataset=event.target.closest('[data-te-dataset]');if(dataset){dailyReviewChange({dataset:dataset.dataset.teDataset});return;}
    const retry=event.target.closest('[data-te-retry]');if(retry){void loadDailyReviewImage(retry.closest('.te-card'),dailyReviewRouteOptions().media,dailyReviewState.imageEpoch);return;}
    const open=event.target.closest('[data-te-open]');if(open)void openDailyReviewMedia(open.dataset.teOpen);
  });
  for(const [id,key] of [['dailyReviewDate','date'],['dailyReviewReason','reason'],['dailyReviewStatus','te_status'],['dailyReviewMedia','media']])$('#'+id).addEventListener('change',e=>dailyReviewChange({[key]:e.target.value}));
  $('#dailyReviewRefresh').addEventListener('click',()=>loadDailyReview());
  $('#dailyReviewPrev').addEventListener('click',()=>dailyReviewChange({page:dailyReviewRouteOptions().page-1}));
  $('#dailyReviewNext').addEventListener('click',()=>dailyReviewChange({page:dailyReviewRouteOptions().page+1}));
  document.addEventListener('visibilitychange',()=>{
    if(!dailyReviewState.active)return;
    clearTimeout(dailyReviewState.timer);
    if(document.hidden){dailyReviewState.seq++;dailyReviewState.controller?.abort();stopDailyReviewImages();}
    else {dailyReviewState.data=null;void loadDailyReview();}
  });
}
