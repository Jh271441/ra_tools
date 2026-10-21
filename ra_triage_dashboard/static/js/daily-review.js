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
    $('#dailyReviewProgress').textContent='TE — / —';$('#dailyReviewRate').textContent='—';
    $('#dailyReviewCounts').textContent='';$('#dailyReviewBar').value=0;$('#dailyReviewExport').hidden=true;
  }
  dailyReviewState.key=key;
  $('#dailyReviewSource').textContent=uiText('读取快照…','Reading snapshot…');
  try {
    const data=await api(`/api/daily-review/cases?${dailyReviewParams(scope)}`,{signal:controller.signal});
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
  if(!data)return;
  date.innerHTML=data.date_options.map(d=>`<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('');date.value=data.scope.date || '';
  const n=data.summary;
  $('#dailyReviewProgress').textContent=n ? `TE ${n.filled} / ${n.total}` : 'TE — / —';
  $('#dailyReviewRate').textContent=n ? (n.total ? `${(n.rate*100).toFixed(1)}%` : uiText('无目标','No targets')) : '—';
  $('#dailyReviewBar').value=n?.rate || 0;
  $('#dailyReviewCounts').textContent=n ? uiText(`低置信 ${n.reasons.low||0} · 抽样 ${n.reasons.sample||0} · 未知 ${n.unknown}`,`Low ${n.reasons.low||0} · Sample ${n.reasons.sample||0} · Unknown ${n.unknown}`) : '';
  const at=data.last_success_at ? new Intl.DateTimeFormat(i18nLocale()==='en'?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(data.last_success_at)) : '—';
  const status={ready:uiText('观测于','Observed'),stale:uiText('数据过期','Stale'),error:uiText('同步异常','Sync error'),unavailable:uiText('等待首次同步','Awaiting first sync')}[data.source_status] || '';
  $('#dailyReviewSource').textContent=`${status} ${at} · CST`;
  $('#dailyReviewSource').classList.toggle('te-warning',data.source_status!=='ready');
  $('#dailyReviewDistribution').textContent=data.result_distribution.map(r=>`${r.value}: ${r.count}`).join(' · ') || '—';
  $('#dailyReviewCoverage').textContent=n ? uiText(`读取覆盖率 ${n.total ? (n.coverage*100).toFixed(1)+'%' : '—'}；状态筛选不改变进度分母。`,`Read coverage ${n.total ? (n.coverage*100).toFixed(1)+'%' : '—'}; status filters do not change the denominator.`) : '';
  const exp=$('#dailyReviewExport');exp.hidden=!data.snapshot_revision;
  exp.href=withBase(`/api/daily-review/export?${dailyReviewParams({...s,date:data.scope.date||''})}&revision=${encodeURIComponent(data.snapshot_revision)}`);
  const count=Math.max(1,Math.ceil(data.total/data.size));
  $('#dailyReviewPageLabel').textContent=`${data.page} / ${count} · ${data.total}`;
  $('#dailyReviewPrev').disabled=data.page<=1;$('#dailyReviewNext').disabled=data.page>=count;
  if(keepImages) return;
  stopDailyReviewImages();
  const grid=$('#dailyReviewGrid');
  grid.innerHTML=data.items.map(row=>`<article class="te-card" data-te-id="${escapeHtml(row.issue_id)}"><button type="button" class="te-picture" data-te-open="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(row.issue_id)} ${escapeHtml(uiText('查看媒体','View media'))}"><img alt="${escapeHtml(row.issue_id)} ${escapeHtml(s.media)}" hidden /><span class="te-placeholder">${uiText('图片待就绪','Image pending')}</span><span class="te-tag">${row.reason==='low'?uiText('低置信','Low'):uiText('抽样','Sample')}</span><span class="te-result" data-status="${escapeHtml(row.te_status)}">${escapeHtml(dailyReviewBadge(row))}</span></button><footer><a href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(row.issue_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.issue_id)} ↗</a><button type="button" class="te-retry" data-te-retry="${escapeHtml(row.issue_id)}" hidden>${uiText('重试图片','Retry image')}</button></footer></article>`).join('') || `<p class="muted">${uiText(n ? '此筛选下暂无图片卡片' : '等待 TE 数据同步',n ? 'No cases in this filter' : 'Awaiting TE observations')}</p>`;
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
