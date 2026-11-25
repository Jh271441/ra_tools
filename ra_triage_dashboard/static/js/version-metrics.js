/* One cross-version chart, shared Manual controls, immutable metric receipts. */
const VM_DEFAULT_SCHEMES=['chain','chain_post_human_sim'];
const versionMetrics={active:false,bound:false,seq:0,controller:null,timer:null,observer:null,data:null,catalog:[],loading:false,error:'',families:'',reference:'release',exclusion:'all',threshold:.9,metric:'accuracy',schemes:[...VM_DEFAULT_SCHEMES],thresholdFamily:'',thresholdExpanded:false};
const VM_SCHEMES=['model','chain','model_human_sim','chain_human_sim','chain_post_human_sim'];
const VM_COLORS={model:'var(--chart-blue)',chain:'var(--chart-teal)',model_human_sim:'var(--chart-slate)',chain_human_sim:'var(--chart-indigo)',chain_post_human_sim:'var(--accent)'};
function vmScheme(key){return ({model:uiText('纯模型','Model'),chain:uiText('模型＋规则','Model + rules'),model_human_sim:uiText('模型＋人工（模拟）','Model + review (simulated)'),chain_human_sim:uiText('模型＋规则＋人工（模拟）','Model + rules + review (simulated)'),chain_post_human_sim:uiText('模型＋规则＋规则后人工（模拟）','Model + rules + post-rule review (simulated)')})[key]||key;}
function vmSchemeShort(key){return ({model:uiText('纯模型','Model'),chain:uiText('模型＋规则','Model + rules'),model_human_sim:uiText('模型＋人工','Model + review'),chain_human_sim:uiText('模型＋规则＋人工','Model + rules + review'),chain_post_human_sim:uiText('规则后人工','Post-rule review')})[key]||key;}
function vmMetric(key){return ({accuracy:uiText('准确率 ACC','Accuracy ACC'),macro_f1:'Macro-F1',recall_correct:uiText('正确触发召回率','Correct-trigger recall'),recall_false:uiText('误触发召回率','False-trigger recall'),recall_no_assist:uiText('无需协助召回率','No-assistance recall'),human_share:uiText('人工介入比例（模拟）','Human intervention (simulated)')})[key]||key;}
function vmPct(value,digits=2){return value==null?'—':new Intl.NumberFormat(i18nLocale(),{style:'percent',minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value);}
function vmTime(value){const date=new Date(value);return !value||Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat(i18nLocale(),{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date);}
function versionMetricRouteOptions(options={}){const p=stripBasePath(location.pathname)==='/version-metrics'?new URLSearchParams(location.search):new URLSearchParams();return Object.fromEntries(['families','metric','schemes','reference','exclusion','threshold','threshold_family','threshold_open'].map(k=>[k,options[k]??p.get(k)??'']));}
function vmReadRoute(){
  const s=versionMetrics,p=new URLSearchParams(location.search);s.families=p.get('families')||'';
  s.metric=['accuracy','macro_f1','recall_correct','recall_false','recall_no_assist','human_share'].includes(p.get('metric'))?p.get('metric'):'accuracy';s.reference=['release','te','rd','te_prime','arbitrated'].includes(p.get('reference'))?p.get('reference'):'release';s.exclusion=p.get('exclusion')==='exclude'?'exclude':'all';
  const threshold=Number(p.get('threshold')||.9);s.threshold=[.9,.85,.8,.76,.75,.65].includes(threshold)?threshold:.9;
  s.schemes=p.has('schemes')?VM_SCHEMES.filter(k=>p.get('schemes').split(',').includes(k)):p.get('expanded')==='1'?[...VM_SCHEMES]:[...VM_DEFAULT_SCHEMES];
  s.thresholdFamily=p.get('threshold_family')||'';s.thresholdExpanded=p.get('threshold_open')==='1';
}
function vmWriteRoute(mode='replace'){const s=versionMetrics,u=new URL(withBase('/version-metrics'),location.origin);for(const [key,value] of Object.entries({families:s.families,metric:s.metric,schemes:s.schemes.join(',')||'none',reference:s.reference,exclusion:s.exclusion,threshold:s.threshold,threshold_family:s.thresholdFamily,threshold_open:s.thresholdExpanded?'1':''}))if(value!=='')u.searchParams.set(key,String(value));history[mode==='push'?'pushState':'replaceState']({page:'version-metrics'},'',u);}
function vmChange(patch,{local=false}={}){const s=versionMetrics;Object.assign(s,patch);s.error='';vmHideTooltip();if(local){vmReconcileReports();vmWriteRoute('push');renderVersionMetrics();return;}s.data=null;vmWriteRoute('push');void loadVersionMetrics({restore:false});}
function vmToggleScheme(key){if(!VM_SCHEMES.includes(key))return;const selected=new Set(versionMetrics.schemes);if(selected.has(key))selected.delete(key);else selected.add(key);vmChange({schemes:VM_SCHEMES.filter(value=>selected.has(value))},{local:true});}
function vmThresholdText(){return 'conf < '+versionMetrics.threshold.toFixed(2);}
function vmRenderLegend(){
  const legend=$('#vmLegend'),keys=VM_SCHEMES;
  const focused=legend.contains(document.activeElement)?document.activeElement.dataset.vmScheme:null;
  legend.setAttribute('aria-label',uiText('显示方案','Visible schemes'));
  const markup=keys.map(key=>`<button type="button" class="button button-secondary vm-scheme-button" data-vm-scheme="${key}" style="--vm-color:${VM_COLORS[key]}" aria-pressed="${versionMetrics.schemes.includes(key)}" aria-label="${escapeHtml(vmScheme(key))}" title="${escapeHtml(vmScheme(key))}"><i class="vm-swatch" aria-hidden="true"></i>${escapeHtml(vmSchemeShort(key))}</button>`).join('');
  if(legend.innerHTML!==markup){legend.innerHTML=markup;if(focused)(legend.querySelector(`[data-vm-scheme="${focused}"]`)||legend.querySelector('button'))?.focus({preventScroll:true});}
}
function setVersionMetricsActive(active){const s=versionMetrics;s.active=active;if(!active){s.seq++;s.controller?.abort();clearTimeout(s.timer);s.observer?.disconnect();s.observer=null;vmHideTooltip();return;}bindVersionMetrics();}
function vmScopeKey(){const s=versionMetrics;return JSON.stringify([s.families,s.reference,s.exclusion,s.threshold]);}
async function loadVersionMetrics({restore=true,background=false}={}){
  const s=versionMetrics;if(!s.active)return;if(restore)vmReadRoute();const seq=++s.seq,scope=vmScopeKey();
  s.controller?.abort();
  clearTimeout(s.timer);
  s.controller=new AbortController();
  s.loading=!background;
  let redraw=!background||Boolean(s.error);
  if(!background){s.error='';vmHideTooltip();renderVersionMetrics();}
  try{
    const query=new URLSearchParams({families:s.families,reference:s.reference,exclusion:s.exclusion,threshold:s.threshold});
    const data=await api('/api/version-metrics?'+query,{signal:s.controller.signal});
    if(!s.active||seq!==s.seq||scope!==vmScopeKey())return;
    redraw=redraw||JSON.stringify(data)!==JSON.stringify(s.data);
    s.error='';
    s.data=data;
    s.catalog=data.catalog;
    if(redraw){vmReconcileReports();vmWriteRoute();}
  }catch(error){
    if(s.active&&seq===s.seq&&error.name!=='AbortError'){s.error='load_failed';redraw=true;}
  }finally{
    if(s.active&&seq===s.seq){
      s.loading=false;
      if(redraw)renderVersionMetrics();
      const delay=s.data?.refresh?.status==='running'?5000:60000;
      s.timer=setTimeout(()=>loadVersionMetrics({restore:false,background:true}),delay);
    }
  }
}
function vmSelect(id,options,value){const el=$('#'+id),html=options.map(([v,label])=>`<option value="${escapeHtml(String(v))}">${escapeHtml(label)}</option>`).join('');if(el.innerHTML!==html)el.innerHTML=html;el.value=String(value);enhanceNativeUiSelect(el);}
function vmMulti(root,options,selected,onChange){const fingerprint=JSON.stringify(options);if(root.dataset.fingerprint!==fingerprint){if(root.classList.contains('is-open')&&relabelMultiFilter(root,options)){root.dataset.fingerprint=fingerprint;setMultiFilterValues(root,selected);return;}renderMultiFilter(root,{options,selected,onlyThis:true,onChange});root.dataset.fingerprint=fingerprint;}else setMultiFilterValues(root,selected);}
function vmClass(metric){return {recall_correct:'正确触发',recall_false:'误触发',recall_no_assist:'无需协助'}[metric];}
function vmValue(row,key){const m=row.metrics?.[key],metric=versionMetrics.metric;if(!m)return null;if(metric==='human_share')return m.total?m.human_count/m.total:null;const label=vmClass(metric);return label?m.per_class.find(c=>c.label===label)?.recall??null:m[metric]??null;}
function vmPercentageScale(rows,keys){
  // Same four-interval percentage scale as /sim PrComparison.
  const values=rows.flatMap(row=>keys.map(key=>vmValue(row,key))).filter(Number.isFinite).map(value=>value*100);
  if(!values.length)return {domain:[0,100],ticks:[0,25,50,75,100]};
  const min=Math.max(0,Math.floor(Math.min(...values)+1e-9)),max=Math.min(100,Math.ceil(Math.max(...values)-1e-9));
  const step=Math.max(1,Math.ceil((max-min)/4)),lower=Math.max(0,Math.min(min,100-step*4));
  return {domain:[lower,lower+step*4],ticks:Array.from({length:5},(_,i)=>lower+i*step)};
}
function vmPointLabels(row,keys,y){
  // Like /sim, keep every value above its point and lift nearby labels.
  const labels=[];for(const key of keys){const value=vmValue(row,key);if(!Number.isFinite(value))continue;const same=labels.find(p=>p.value===value);if(same)same.keys.push(key);else labels.push({key,keys:[key],value});}labels.sort((a,b)=>a.value-b.value);
  let previous=Infinity;return labels.map(point=>{const baseline=Math.min(y(point.value)-12,previous-18);previous=baseline;return {...point,y:baseline};});
}
function vmChartGeometry(rows,keys,containerWidth){
  const scale=vmPercentageScale(rows,keys),width=Math.max(containerWidth||0,680,rows.length*70+128),height=288,left=52,right=76,bottom=34,plotW=width-left-right;
  let top=28;
  const x=i=>left+(i+.5)*plotW/Math.max(1,rows.length),y=value=>top+(scale.domain[1]-value*100)/(scale.domain[1]-scale.domain[0])*(height-top-bottom);
  // Preserve /sim's 28px margin, adding headroom only if stacked labels need it.
  for(let pass=0;pass<3;pass++){const minY=Math.min(...rows.flatMap(row=>vmPointLabels(row,keys,y).map(p=>p.y)));if(minY>=14)break;top+=14-minY+4;}
  return {width,height,left,right,top,bottom,plotW,plotH:height-top-bottom,scale,x,y};
}
function vmChart(){
  const s=versionMetrics,host=$('#vmChart'),rows=s.data?.items||[],keys=s.schemes;
  vmHideTooltip();
  if(s.error||!rows.length||!keys.length){host.innerHTML=`<div class="vm-chart-empty">${s.error?uiText('暂时无法显示指标','Metrics are unavailable'):s.loading?uiText('正在读取指标…','Loading metrics…'):!keys.length?uiText('请选择要比较的方案','Select schemes to compare'):uiText('暂无版本快照，请更新指标','No version snapshots. Update metrics to begin.')}</div>`;return;}
  if(!rows.some(row=>keys.some(key=>vmValue(row,key)!=null))){host.innerHTML=`<div class="vm-chart-empty">${rows.some(row=>row.status==='ready')?uiText('当前筛选暂无有效指标','No valid metrics for the current filters'):uiText('暂无 Trail 快照，请更新指标','No Trail snapshot. Update metrics.')}</div>`;return;}
  const {width,height,left,right,top,plotW,plotH,scale,x,y}=vmChartGeometry(rows,keys,host.clientWidth);
  let svg=`<svg class="vm-trend-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="${escapeHtml(uiText('跨版本','Cross-version')+' '+vmMetric(s.metric))}">`;
  for(const tick of scale.ticks)svg+=`<line x1="${left}" y1="${y(tick/100)}" x2="${width-right}" y2="${y(tick/100)}" class="vm-grid-line"/><text x="${left-10}" y="${y(tick/100)+4}" text-anchor="end" class="vm-axis vm-y-axis">${tick}%</text>`;
  for(const key of keys){let path='',open=false;for(let i=0;i<rows.length;i++){const v=vmValue(rows[i],key);if(v==null){open=false;continue;}path+=`${open?'L':'M'}${x(i)},${y(v)} `;open=true;}svg+=`<path class="vm-series-line" d="${path}" fill="none" stroke="${VM_COLORS[key]}" stroke-width="2.5"/>`;rows.forEach((row,i)=>{const v=vmValue(row,key);if(v!=null)svg+=`<circle class="vm-point" data-vm-dot="${row.family}" cx="${x(i)}" cy="${y(v)}" r="3" fill="var(--raised)" stroke="${VM_COLORS[key]}" stroke-width="2"/>`;});}
  svg+=`<line class="vm-cursor" x1="0" x2="0" y1="${top}" y2="${top+plotH}" aria-hidden="true"/>`;
  rows.forEach((row,i)=>{for(const point of vmPointLabels(row,keys,y))svg+=`<text class="vm-value-label" data-vm-label="${point.key}" data-vm-point="${row.family}" x="${x(i)}" y="${point.y}" text-anchor="middle" aria-hidden="true">${escapeHtml(vmPct(point.value,1))}</text>`;});
  const years=new Set(rows.map(r=>r.family.slice(0,4))),interval=Math.max(1,Math.ceil(rows.length/12));
  rows.forEach((row,i)=>{const date=row.family.slice(4,6)+'-'+row.family.slice(6),label=years.size>1?row.family.slice(0,4)+'/'+date:date,hint=keys.map(k=>`${vmScheme(k)} ${vmPct(vmValue(row,k))}`).join('; ');svg+=`<g data-vm-family="${row.family}" data-vm-x="${x(i)}" role="button" tabindex="0" aria-label="${escapeHtml(row.family+'; '+hint)}"><rect x="${left+i*plotW/rows.length}" y="0" width="${plotW/rows.length}" height="${height}" fill="transparent"/>${i%interval===0?`<text class="vm-axis" x="${x(i)}" y="${height-12}" text-anchor="middle">${label}</text>`:''}</g>`;});host.innerHTML=svg+'</svg>';
}
function vmHideTooltip(){const tip=$('#vmTooltip');if(tip)tip.hidden=true;$('#vmChart')?.querySelectorAll('.is-active').forEach(el=>el.classList.remove('is-active'));}
function vmShowTooltip(family,event,anchor){
  const s=versionMetrics,row=s.data?.items.find(r=>r.family===family),tip=$('#vmTooltip');if(!row||!tip)return;
  tip.innerHTML=`<strong>release-${escapeHtml(family)}</strong>`+(row.status==='ready'?s.schemes.map(key=>{const m=row.metrics?.[key];if(!m)return '';const label=vmClass(s.metric),c=label?m.per_class.find(v=>v.label===label):null;const counts=c?`${c.tp}/${c.support}`:s.metric==='human_share'?`${m.human_count}/${m.total}`:s.metric==='accuracy'?`${m.correct}/${m.total}`:`n=${m.total}`;return `<span style="color:${VM_COLORS[key]}"><i class="vm-swatch" style="--vm-color:${VM_COLORS[key]}" aria-hidden="true"></i>${escapeHtml(vmScheme(key))}<b>${vmPct(vmValue(row,key))}</b><small>${counts}</small></span>`;}).join('')+`<small>${uiText('快照有效／抽样','Snapshot valid / sample')} ${row.valid_total}/${row.sample_total} · ${vmTime(row.observed_at)} CST</small>`:`<span>${uiText('暂无有效快照','No valid snapshot')}</span>`);
  if(row.status==='ready'){
    tip.insertAdjacentHTML('beforeend',`<small>GT · ${escapeHtml(vmReferenceCounts(row))}</small>`);
    if(row.last_checked_at)tip.insertAdjacentHTML('beforeend',`<small>${uiText('自动核对','Auto-checked')} · ${vmTime(row.last_checked_at)} CST</small>`);
  }
  const sampleChange=vmSampleChange(row);
  if(sampleChange)tip.insertAdjacentHTML('beforeend',`<small>${escapeHtml(sampleChange)}</small>`);
  const host=$('#vmChart'),cursor=host.querySelector('.vm-cursor');if(cursor){cursor.setAttribute('x1',anchor.dataset.vmX);cursor.setAttribute('x2',anchor.dataset.vmX);cursor.classList.add('is-active');}
  host.querySelectorAll('.vm-point').forEach(point=>point.classList.toggle('is-active',point.dataset.vmDot===family));
  tip.hidden=false;const box=tip.getBoundingClientRect(),rect=anchor.getBoundingClientRect(),bounds=host.getBoundingClientRect(),px=rect.x+rect.width/2,py=event?.clientY??bounds.top+28;
  const rightBound=Math.min(window.innerWidth-8,bounds.right);let tipX=px+40,tipY=Math.max(8,Math.min(Math.max(bounds.top,py+12),bounds.bottom-box.height,window.innerHeight-box.height-8));if(tipX+box.width>rightBound)tipX=px-40-box.width;
  if(tipX<8){tipX=Math.max(8,Math.min(px-box.width/2,window.innerWidth-box.width-8));tipY=Math.max(8,bounds.top-box.height-8);}
  tip.style.left=Math.max(8,Math.min(tipX,window.innerWidth-box.width-8))+'px';tip.style.top=tipY+'px';
}
function renderVersionMetrics(){
  const s=versionMetrics;if(!s.active)return;const root=$('#versionMetricsPage');root.querySelectorAll('[data-vm-zh]').forEach(e=>e.textContent=uiText(e.dataset.vmZh,e.dataset.vmEn));
  $('#vmVersionPicker').setAttribute('aria-label',uiText('评测版本','Evaluation versions'));
  vmMulti($('#vmVersionPicker'),s.catalog.map(d=>({value:d.family,label:d.family.slice(4)})),s.families==='all'?[]:s.families?s.families.split(',').filter(Boolean):s.data?.selected||[],values=>vmChange({families:values.length?values.join(','):'all'}));
  vmSelect('vmMetric',['accuracy','macro_f1','recall_correct','recall_false','recall_no_assist','human_share'].map(k=>[k,vmMetric(k)]),s.metric);
  vmSelect('vmReference',[['release',vmReferenceLabel('release')],['te',uiText('TE 原始标注','Original TE')],['rd',uiText('RD 标注','RD labels')],['te_prime',uiText('TE′ 人工标注','Manual TE′')],['arbitrated',uiText('裁决结果','Adjudication')]],s.reference);
  vmSelect('vmExclusion',[['all',uiText('全部三分类有效','All valid samples')],['exclude',uiText('剔除人工排除项','Remove manual exclusions')]],s.exclusion);vmSelect('vmThreshold',[.9,.85,.8,.76,.75,.65].map(t=>[t.toFixed(2),t.toFixed(2)]),s.threshold.toFixed(2));
  $('#vmThresholdNote').textContent=vmThresholdText();$('#vmThresholdNote').title=uiText('仅人工模拟方案使用的低置信阈值','Low-confidence threshold used by simulated review schemes');$('#vmError').hidden=!s.error;$('#vmErrorText').textContent=!s.error?'':s.error==='refresh_not_started'?uiText('更新未启动，请稍后重试。','Refresh did not start. Retry later.'):uiText('指标读取失败，请重试。','Metrics could not be loaded. Please retry.');
  const job=s.data?.refresh,updating=job?.status==='running';$('#vmRefresh').disabled=s.loading||!s.data?.selected?.length||!hasDashboardWriteRole()||updating;$('#vmRefresh').title=hasDashboardWriteRole()?uiText('只读更新数据并保留历史快照','Read sources and retain snapshot history'):uiText('更新指标需要writer或管理员权限','Writer or admin access is required to refresh');
  $('#vmStatus').textContent=updating?uiText(`正在更新 ${job.completed}/${job.total} 个版本`,`Updating ${job.completed}/${job.total} versions`):['failed','interrupted'].includes(job?.status)?uiText('更新未完成，保留上次快照','Refresh incomplete; previous snapshots retained'):s.loading?uiText('读取中…','Loading…'):'';$('#vmStatus').hidden=!$('#vmStatus').textContent;
  vmRenderLegend();vmRenderReports();vmChart();enhanceDashboardSelects(root);
}
async function vmRefresh(){const s=versionMetrics;if(!s.data||!hasDashboardWriteRole())return;const context=capturePageContext();$('#vmRefresh').disabled=true;try{await api('/api/version-metrics/refresh',{method:'POST',body:JSON.stringify({families:s.data.selected})});if(s.active&&isPageContextCurrent(context))void loadVersionMetrics({restore:false});}catch(error){if(s.active&&isPageContextCurrent(context)){s.error='refresh_not_started';renderVersionMetrics();}}}
function bindVersionMetrics(){
  const s=versionMetrics,root=$('#versionMetricsPage');if(!s.bound){s.bound=true;bindUiInfoPopovers(root);vmBindReports();
    root.addEventListener('change',event=>{const el=event.target;if(el.id==='vmMetric')vmChange({metric:el.value},{local:true});if(el.id==='vmReference')vmChange({reference:el.value});if(el.id==='vmExclusion')vmChange({exclusion:el.value});if(el.id==='vmThreshold')vmChange({threshold:Number(el.value)});});
    root.addEventListener('click',event=>{const scheme=event.target.closest('[data-vm-scheme]');if(scheme){vmToggleScheme(scheme.dataset.vmScheme);return;}if(event.target.closest('#vmReset')){vmChange({metric:'accuracy',reference:'release',exclusion:'all',threshold:.9,schemes:[...VM_DEFAULT_SCHEMES],thresholdFamily:'',thresholdExpanded:false});return;}if(event.target.closest('#vmRefresh')){void vmRefresh();return;}if(event.target.closest('#vmRetry')){void loadVersionMetrics();return;}const group=event.target.closest('[data-vm-family]');if(group)vmShowTooltip(group.dataset.vmFamily,event,group);else vmHideTooltip();});
    root.addEventListener('pointermove',event=>{const group=event.target.closest('[data-vm-family]');if(group)vmShowTooltip(group.dataset.vmFamily,event,group);});$('#vmChart').addEventListener('pointerleave',vmHideTooltip);$('#vmChart').addEventListener('scroll',vmHideTooltip,{passive:true});
    root.addEventListener('focusin',event=>{const group=event.target.closest('[data-vm-family]');if(group)vmShowTooltip(group.dataset.vmFamily,null,group);});root.addEventListener('focusout',event=>{if(event.target.closest('[data-vm-family]'))vmHideTooltip();});
    root.addEventListener('keydown',event=>{if(event.key==='Escape'){vmHideTooltip();return;}const group=event.target.closest('[data-vm-family]');if(group&&['Enter',' '].includes(event.key)){event.preventDefault();vmShowTooltip(group.dataset.vmFamily,null,group);}});window.addEventListener('scroll',vmHideTooltip,{passive:true});
  }
  if(!s.observer&&typeof ResizeObserver!=='undefined'){let width=0;s.observer=new ResizeObserver(entries=>{const next=Math.round(entries[0].contentRect.width);if(next!==width){width=next;if(s.active){vmHideTooltip();vmChart();}}});s.observer.observe($('#vmChart'));}
}
