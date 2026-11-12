/* Role conclusions and synchronization are deliberately separate from task delivery. */
const humanPublication = { lane:'rd',data:null,loading:false,busy:false,error:'',notice:'',epoch:0,selected:new Set(),preview:null,
  filters:{q:'',status:'all',page:1,page_size:DEFAULT_CASE_PAGE_SIZE},draft:{q:'',status:'all'},infoOpen:false,history:null,historyIssue:'',historyPage:1,historySize:DEFAULT_CASE_PAGE_SIZE,timer:null };
function humanPublicationPageActive() {
  return state.selectedBaselineIds.length>0 && state.selectedBaselineIds.every(id=>/^version-20\d{6}$/.test(id) && id.slice(8)>='20261106')
    && new URLSearchParams(location.search).get('mode')!=='te-correction';
}
function humanStatus(value) {
  const names={resolved:['已完成','Completed'],pending:['待标注','Pending labels'],conflict:['标注冲突','Conflicting labels'],
    unassigned:['未分配该角色','Role not assigned'],unclassified:['身份待确认','Role needs confirmation'],inactive:['来源已停用','Source inactive'],
    none:['未裁决','No adjudication'],stale:['裁决已失效','Adjudication stale'],objection:['有任务外异议','Advisory objection'],
    awaiting_activation:['历史结果待启用','Historical publishing not activated'],
    synced:['已同步','Synced'],same:['已一致','Already matches'],not_ready:['待结论','Awaiting result'],
    retry_wait:['等待重试','Retry scheduled'],unverified:['上传结果未确认','Upload outcome unverified'],needs_recheck:['需人工核对','Needs reconciliation'],
    verified:['读回一致','Readback verified'],not_applied:['未写入','Not applied'],external_conflict:['远端值已变化','Remote value changed'],
    pre_read_failed:['上传前读取失败','Pre-upload read failed'],readback_failed:['读回核验失败','Readback failed'],
    intent:['写入待核验','Write awaiting verification'],set:['同步结论','Synchronize result'],clear:['撤回旧结论','Retract previous result'],
    recheck:['核对未确认结果','Recheck uncertain outcome'],blocked:['暂无可上传结论','No publishable result']};
  return names[value]?uiText(...names[value]):rdStatus(value);
}
function humanLaneName(lane) { return lane==='arbitrated'?uiText('裁决标注','Adjudication'):lane==='te'?uiText('TE′ 标注','TE′ labels'):uiText('RD 标注','RD labels'); }
function humanBadge(value) { return `<span class="run-source-badge rd-status ${['conflict','stale','unverified','needs_recheck'].includes(value)?'rd-status-warn':['synced','same','verified'].includes(value)?'rd-status-ok':'rd-status-neutral'}">${escapeHtml(humanStatus(value))}</span>`; }
function hpMetricsMarkup(data, disabled) {
  const h=humanPublication,decision=h.lane==='arbitrated';
  const counts=data?{...data.counts,total:Object.entries(data.counts).reduce((sum,[key,n])=>sum+(key==='objection'?0:n),0)}:null;
  return rdMetricsMarkup(data?{counts}:null,{status:h.filters.status,disabled,metrics:[
    ['all','total','范围内 Issues','Issues in scope','M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z'],
    ['resolved','resolved',decision?'已裁决':'已完成',decision?'Adjudicated':'Completed','m5 12 4 4L19 6'],
    [decision?'none':'pending',decision?'none':'pending',decision?'待裁决':'待标注',decision?'Pending decision':'Pending labels','M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'],
    [decision?'stale':'conflict',decision?'stale':'conflict','需复核','Needs review','m12 3 10 18H2L12 3zm0 6v5m0 3v1'],
  ]});
}
function humanRoleSummary(human) {
  if (!human)return '';
  return `<div class="human-role-summary" role="status">${['rd','te','arbitrated'].map(lane=>{
    const result=human.lanes[lane],sync=human.sync[lane];
    return `<span><strong>${escapeHtml(humanLaneName(lane))}</strong> ${escapeHtml(humanStatus(result.state))}${result.label?' · '+escapeHtml(rdLabel(result.label)):''}${sync?' · '+escapeHtml(humanStatus(human.scope?.publication_armed===0?'awaiting_activation':sync.sync_state)):''}${result.objections?.length?' · '+escapeHtml(uiText(`${result.objections.length} 条任务外异议`,`${result.objections.length} advisory objections`)):''}</span>`;
  }).join('')}</div>`;
}
function renderHumanReviewStatus(human) {
  const root=$('#humanReviewStatus');if(!root)return;
  root._humanPublication=human;root.innerHTML=humanRoleSummary(human);
}
function hpPersist() {
  const h=humanPublication,url=new URL(pageUrl('rd-results',{baselines:state.selectedBaselineIds}),location.origin);
  Object.entries({...h.filters,lane:h.lane}).forEach(([k,v])=>url.searchParams.set(k,v));
  if(h.historyIssue){url.searchParams.set('history_issue',h.historyIssue);url.searchParams.set('history_page',h.historyPage);url.searchParams.set('history_size',h.historySize);}
  history.replaceState(history.state,'',url);
}
async function loadHumanPublications({poll=false}={}) {
  const h=humanPublication;if(poll&&(h.busy||h.loading||h.preview||state.activePage!=='rd-results'||!humanPublicationPageActive()))return;
  const params=new URLSearchParams(location.search),scope=state.selectedBaselineIds.join(','),epoch=++h.epoch;
  if(!poll){
    h.lane=['rd','te','arbitrated'].includes(params.get('lane'))?params.get('lane'):'rd';
    h.filters={q:params.get('q')||'',status:params.get('status')||'all',page:Math.max(1,Number(params.get('page'))||1),page_size:CASE_PAGE_SIZES.includes(Number(params.get('page_size')))?Number(params.get('page_size')):DEFAULT_CASE_PAGE_SIZE};
    if(!['all','resolved','pending','conflict','stale','none','unassigned','inactive','unclassified','objection'].includes(h.filters.status))h.filters.status='all';
    h.draft={...h.filters};h.selected.clear();h.preview=null;h.data=null;h.loading=true;h.error='';
    h.historyIssue=/^cn\d+$/.test(params.get('history_issue')||'')?params.get('history_issue'):'';
    h.historyPage=Math.max(1,Number(params.get('history_page'))||1);h.historySize=CASE_PAGE_SIZES.includes(Number(params.get('history_size')))?Number(params.get('history_size')):DEFAULT_CASE_PAGE_SIZE;
    h.history=null;renderHumanPublications();
  }
  try {
    const data=await api(`/api/human-publications?${new URLSearchParams({baselines:scope,lane:h.lane,...h.filters})}`);
    if(epoch!==h.epoch||scope!==state.selectedBaselineIds.join(',')||!humanPublicationPageActive())return;
    const old=new Map((h.data?.items||[]).map(r=>[r.issue_id,r.generation]));
    if(poll)h.selected=new Set([...h.selected].filter(id=>data.items.some(r=>r.issue_id===id&&r.generation===old.get(id))));
    h.data=data;h.filters.page=data.page;h.error='';
    if(h.historyIssue&&!poll)await hpLoadHistory();
  } catch(error) { if(epoch===h.epoch){h.data=null;h.selected.clear();h.error=uiText('暂时无法加载，请刷新重试。','Unable to load results. Refresh to retry.');} }
  finally {if(epoch===h.epoch){h.loading=false;hpPersist();renderHumanPublications();}}
  clearTimeout(h.timer);h.timer=setTimeout(()=>loadHumanPublications({poll:true}),15000);
}
async function hpLoadHistory() {
  const h=humanPublication,issue=h.historyIssue,lane=h.lane;
  const data=await api(`/api/human-publications/history?${new URLSearchParams({issue_id:issue,lane,page:h.historyPage,page_size:h.historySize})}`);
  if(h.historyIssue===issue&&h.lane===lane){h.history=data;h.historyPage=data.page;}
}
function renderHumanPublications() {
  if(state.activePage!=='rd-results')return;
  const h=humanPublication,d=h.data,root=$('#rdResultsPage'),disabled=h.loading||h.busy;
  const focus=document.activeElement?.id,caret=document.activeElement?.selectionStart;
  const button=(action,zh,en,off=false,primary=false,quiet=false)=>`<button type="button" class="button ${primary?'button-primary':quiet?'button-quiet':'button-secondary'}" data-hp-action="${action}" ${disabled||off?'disabled':''}>${uiText(zh,en)}</button>`;
  const historyUrl=new URL(pageUrl('rd-results',{baselines:state.selectedBaselineIds}),location.origin);historyUrl.searchParams.set('mode','te-correction');
  const historyRow=d?.items.find(row=>row.issue_id===h.historyIssue);
  root.classList.remove('is-te-correction');root.classList.add('human-publications-page');
  root.innerHTML=`<section class="page-card runs-source-card rd-overview" aria-label="${uiText('标注上传概览','Label publication overview')}"><div class="runs-source-heading rd-mode-header"><div><div class="rd-mode-tabs" role="tablist" aria-label="${uiText('标注上传类型','Publication type')}">${['rd','te','arbitrated'].map(lane=>`<button id="hpTab-${lane}" type="button" role="tab" class="button button-secondary rd-mode-tab" data-hp-lane="${lane}" aria-label="${escapeHtml(humanLaneName(lane))}" aria-selected="${h.lane===lane}" aria-controls="hpPanel" tabindex="${h.lane===lane?0:-1}" ${disabled?'disabled':''}><span class="rd-mode-label-full">${escapeHtml(humanLaneName(lane))}</span><span class="rd-mode-label-compact" aria-hidden="true">${lane==='arbitrated'?uiText('裁决','Decision'):lane==='te'?'TE′':'RD'}</span></button>`).join('')}</div></div><div class="run-manager-actions">${button('refresh','刷新','Refresh',false,false,true)}</div></div>
    <div class="rd-mode-panel">${hpMetricsMarkup(d,disabled)}
    <details id="hpInfo" class="rd-preview-info" ${h.infoOpen?'open':''}><summary>${uiText('上传说明','About uploads')}</summary><div>
    <p class="rd-description">${uiText('正式标注形成结论后自动同步；任务外异议仅留作参考。可选择标注预览并重试上传。','Formal results sync automatically. Out-of-task objections remain advisory. Select labels to preview or retry an upload.')}</p>
    <dl class="rd-upload-target"><div><dt>${uiText('目标字段','Target field')}</dt><dd><code>${escapeHtml(d?.field||({rd:'ra_rd_review_result',te:'ra_review_result_sampling',arbitrated:'ra_review_result_arbitrated'})[h.lane])}</code></dd></div></dl>
    <a href="${escapeHtml(historyUrl.pathname+historyUrl.search)}">${uiText('原 TE 修正与历史记录','Original TE correction and history')}</a></div></details></div></section>
    <section id="hpPanel" class="page-card runs-page-card rd-workspace" role="tabpanel" aria-labelledby="hpTab-${h.lane}"><div class="rd-detail-toolbar"><div class="rd-detail-heading"><h3>${uiText('标注明细','Label details')}</h3></div>
    <form id="hpFilters" class="run-filter-bar rd-filters"><input id="hpSearch" maxlength="128" value="${escapeHtml(h.draft.q)}" placeholder="${uiText('搜索 Issue ID','Find Issue ID')}" aria-label="${uiText('搜索 Issue ID','Find Issue ID')}" ${disabled?'disabled':''}>
    <select id="hpStatus" aria-label="${uiText('结论筛选','Conclusion filter')}" ${disabled?'disabled':''}>${['all','resolved','pending','conflict','objection','stale','none','unassigned','inactive','unclassified'].map(value=>`<option value="${value}" ${h.draft.status===value?'selected':''}>${value==='all'?uiText('全部状态','All statuses'):escapeHtml(humanStatus(value))}</option>`).join('')}</select><button class="button button-secondary" type="submit" ${disabled?'disabled':''}>${uiText('筛选','Apply')}</button></form></div>
    ${h.loading||h.error||h.notice?`<p class="rd-notice ${h.error?'is-error':''}" role="status">${escapeHtml(h.error||(h.loading?uiText('正在加载…','Loading…'):h.notice))}</p>`:''}
    <div class="rd-selection-bar ${h.selected.size?'has-selection':''}"><div class="rd-selection-tools"><div class="run-manager-actions"><select id="hpSelectionAction" aria-label="${uiText('选中操作','Selection actions')}" ${disabled?'disabled':''}><option value="" selected disabled>${uiText('选中操作','Selection actions')}</option><option value="page" ${!d?.items.length?'disabled':''}>${uiText('选择本页','Select this page')}</option><option value="clear" ${!h.selected.size?'disabled':''}>${uiText('清空选择','Clear selection')}</option></select><span class="rd-selection-count" role="status">${h.selected.size?uiText('已选','Selected')+` <strong>${h.selected.size}</strong> `+uiText('条','labels'):uiText('请选择标注','Select labels to preview')}</span></div></div><div class="run-manager-actions">${d&&!d.write_enabled?`<span class="rd-notice" title="${uiText('真实写入开关关闭，预览可用','Publishing is disabled; preview is available')}">${uiText('写入未启用','Publishing disabled')}</span>`:''}${state.session.is_admin?button('preview','预览上传','Preview upload',!h.selected.size,true):''}</div></div>
    <div class="rd-table-wrap"><table class="rd-table human-publication-table"><thead><tr>${['','Issue',uiText('人工结论','Human label'),uiText('标注人','Contributors'),uiText('同步状态','Sync status'),uiText('记录','History')].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${(d?.items||[]).map(row=>`<tr class="${h.selected.has(row.issue_id)?'is-selected':''}"><td><label class="rd-checkbox"><input id="hpSelect-${row.issue_id}" type="checkbox" class="ui-checkbox" data-hp-id="${row.issue_id}" aria-label="${uiText('选择 ','Select ')+row.issue_id}" ${h.selected.has(row.issue_id)?'checked':''} ${disabled?'disabled':''}></label></td><td><a class="rd-issue-link" href="${escapeHtml(pageUrl('labeling',{issue:row.issue_id,baselines:state.selectedBaselineIds}))}">${escapeHtml(row.issue_id)}</a></td><td>${row.conclusion==='resolved'&&row.label?labelBadge(row.label,'—',rdLabel(row.label)):humanBadge(row.conclusion)}</td><td>${escapeHtml(row.authors.join(', ')||'—')}${row.required>1?` <span class="muted">(${row.submitted}/${row.required})</span>`:''}</td><td>${humanBadge(row.publication_armed===0?'awaiting_activation':row.sync_state)}</td><td>${button('history:'+row.issue_id,row.objections.length?`异议 ${row.objections.length}`:'查看',row.objections.length?`${row.objections.length} objection${row.objections.length===1?'':'s'}`:'View',false,false,true)}</td></tr>`).join('')}</tbody></table></div>
    ${!h.loading&&!d?.items.length?`<div class="rd-empty">${h.error?uiText('加载失败，可刷新重试。','Loading failed. Refresh to retry.'):uiText('当前范围暂无正式标注记录。','No formal label records in this scope.')}</div>`:''}
    ${rdPaginationMarkup(d,false,{prefix:'hp',size:h.filters.page_size,disabled:disabled||Boolean(h.error)})}</section>
    ${h.preview?`<section id="hpPreview" class="page-card rd-workspace" aria-label="${uiText('上传预览','Publication preview')}"><h3>${uiText('本次将排队处理','Queue preview')}</h3><p>${uiText('执行时会再次核对当前结论和远端值。冲突来源不能强制上传。','The worker will recheck the current conclusion and remote value. Conflicted sources cannot be forced through.')}</p><ul>${h.preview.items.map(i=>`<li>${escapeHtml(i.issue_id)} · ${escapeHtml(humanStatus(i.action))} · ${i.desired===null?uiText('无有效结果','No valid result'):escapeHtml(rdLabel(i.desired))}</li>`).join('')}</ul><div class="run-manager-actions">${button('commit','确认加入队列','Confirm queue',!d?.write_enabled||!h.preview.items.some(i=>i.eligible),true)}${button('close-preview','关闭预览','Close preview')}</div></section>`:''}
    ${h.historyIssue?`<section id="hpHistory" class="page-card rd-workspace rd-preview-details"><div class="runs-toolbar"><h3>${escapeHtml(h.historyIssue)} · ${uiText('上传记录','Publication history')}</h3>${button('close-history','关闭记录','Close history',false,false,true)}</div>
    ${historyRow?`<div class="rd-preview-summary">${h.lane==='arbitrated'?'':`<span>${uiText('必需标注','Required votes')} ${historyRow.submitted}/${historyRow.required}</span>`}${historyRow.checked_at?`<span>${uiText('最近核对','Last checked')} ${escapeHtml(rdObservationTime(historyRow.checked_at))} CST</span>`:''}</div>${historyRow.error_code?`<p class="rd-notice is-error">${escapeHtml(rdReason(historyRow.error_code)||humanStatus(historyRow.error_code))}</p>`:''}${historyRow.objections.length?`<div><h3>${uiText('任务外异议','Advisory objections')}</h3>${historyRow.objections.map(v=>`<p class="rd-description">${escapeHtml(v.author)} · ${escapeHtml(rdLabel(v.label))}</p>`).join('')}</div>`:''}`:''}
    ${h.history?.items.length?`<div class="rd-table-wrap"><table class="rd-table"><tbody>${h.history.items.map(i=>`<tr><td>${escapeHtml(rdObservationTime(i.created_at))} CST</td><td>${escapeHtml(humanStatus(i.action))}</td><td>${i.desired===null?'NULL':escapeHtml(rdLabel(i.desired))}</td><td>${humanBadge(i.state)}</td></tr>`).join('')}</tbody></table></div>`:`<p class="rd-description">${uiText('暂无上传尝试。','No publication attempts yet.')}</p>`}${rdPaginationMarkup(h.history,false,{prefix:'hpHistory',actionPrefix:'history-',size:h.historySize,disabled})}</section>`:''}`;
  enhanceDashboardSelects(root);
  root.querySelector('#hpInfo').ontoggle=e=>{h.infoOpen=e.target.open;};
  root.oninput=e=>{if(e.target.id==='hpSearch')h.draft.q=e.target.value;};
  root.onchange=e=>{
    if(e.target.id==='hpStatus')h.draft.status=e.target.value;
    if(e.target.id==='hpSelectionAction'&&!disabled){
      h.selected=e.target.value==='page'?new Set((d?.items||[]).map(row=>row.issue_id)):new Set();h.preview=null;renderHumanPublications();
      $('#hpSelectionAction')?.closest('.ui-select')?.querySelector('.ui-select-trigger')?.focus();
    }
    if(e.target.dataset.hpId){e.target.checked?h.selected.add(e.target.dataset.hpId):h.selected.delete(e.target.dataset.hpId);h.preview=null;renderHumanPublications();}
    if(e.target.id==='hpPageSize'){h.filters.page_size=Number(e.target.value);hpNavigate(1);}
    if(e.target.id==='hpHistoryPageSize'){h.historySize=Number(e.target.value);hpHistoryNavigate(1);}
  };
  root.onsubmit=e=>{if(e.target.id==='hpFilters'){e.preventDefault();h.filters={...h.filters,...h.draft};hpNavigate(1);}};
  root.onclick=e=>hpClick(e).catch(error=>{h.error=error.message;renderHumanPublications();});
  root.onkeydown=e=>{
    if(e.key==='Enter'&&e.target.id==='hpPageJump'){e.preventDefault();hpJump(false);}
    if(e.key==='Enter'&&e.target.id==='hpHistoryPageJump'){e.preventDefault();hpJump(true);}
    const lane=e.target.dataset.hpLane;if(lane&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){
      e.preventDefault();const lanes=['rd','te','arbitrated'],index=lanes.indexOf(lane);
      const next=e.key==='Home'?0:e.key==='End'?2:(index+(e.key==='ArrowRight'?1:2))%3;root.querySelector(`#hpTab-${lanes[next]}`)?.focus();
    }
  };
  if(focus){const element=document.getElementById(focus);element?.focus({preventScroll:true});if(caret!==null&&caret!==undefined&&element?.setSelectionRange&&element.type==='text')element.setSelectionRange(caret,caret);}
}
function hpNavigate(page) {humanPublication.filters.page=page;humanPublication.notice='';hpPersist();return loadHumanPublications();}
async function hpHistoryNavigate(page) {const h=humanPublication;h.historyPage=page;h.busy=true;h.history=null;renderHumanPublications();try{await hpLoadHistory();hpPersist();}finally{h.busy=false;renderHumanPublications();}}
function hpJump(inHistory) {
  const h=humanPublication,input=$(inHistory?'#hpHistoryPageJump':'#hpPageJump'),n=Number(input?.value),d=inHistory?h.history:h.data;
  if(!d||!input?.value.trim()||!Number.isSafeInteger(n))return;
  const page=Math.max(1,Math.min(d.pages,n));return inHistory?hpHistoryNavigate(page):hpNavigate(page);
}
async function hpClick(event) {
  const h=humanPublication;if(h.loading||h.busy)return;
  const tab=event.target.closest('[data-hp-lane]');if(tab){h.lane=tab.dataset.hpLane;h.historyIssue='';return hpNavigate(1);}
  const filter=event.target.closest('[data-rd-filter]');if(filter){h.filters.status=filter.dataset.rdFilter;return hpNavigate(1);}
  const action=event.target.closest('[data-hp-action]')?.dataset.hpAction||event.target.closest('[data-rd-action]')?.dataset.rdAction;
  if(!action)return;
  if(action==='refresh')return loadHumanPublications();
  if(action==='previous'||action==='next')return hpNavigate(h.filters.page+(action==='next'?1:-1));
  if(action==='jump')return hpJump(false);
  if(action==='history-previous'||action==='history-next')return hpHistoryNavigate(h.historyPage+(action==='history-next'?1:-1));
  if(action==='history-jump')return hpJump(true);
  if(action==='close-preview')h.preview=null;
  if(action==='close-history'){h.historyIssue='';h.history=null;hpPersist();}
  if(action==='preview'||action==='commit'||action.startsWith('history:')){
    h.busy=true;h.error='';renderHumanPublications();
    try {
      if(action==='preview')h.preview=await api('/api/human-publications/preview',{method:'POST',body:JSON.stringify({lane:h.lane,baselines:state.selectedBaselineIds.join(','),issue_ids:[...h.selected]})});
      else if(action==='commit'){
        await api('/api/human-publications/commit',{method:'POST',body:JSON.stringify({request_id:h.preview.id,confirmed:true})});
        h.preview=null;h.selected.clear();h.notice=uiText('已加入队列，稍后自动更新同步状态。','Queued. Synchronization status will update shortly.');
      } else {h.historyIssue=action.slice(8);h.historyPage=1;h.history=null;await hpLoadHistory();hpPersist();}
    } finally {h.busy=false;renderHumanPublications();}
  }
  renderHumanPublications();
  if(action==='preview')$('#hpPreview')?.scrollIntoView({behavior:'smooth',block:'nearest'});
  if(action.startsWith('history:'))$('#hpHistory')?.scrollIntoView({behavior:'smooth',block:'nearest'});
}
