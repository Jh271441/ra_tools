/* Version-scoped review worksets; original Campaign identities remain in links. */
const versionDatasetState={active:false,seq:0,controller:null,timer:null,page:1,dataset:'',mode:'targets'};
function setVersionDatasetsActive(active){
  const s=versionDatasetState;s.active=active;s.seq++;s.controller?.abort();clearTimeout(s.timer);
  if(active)void loadVersionDatasets();
}
async function loadVersionDatasets(){
  const s=versionDatasetState;if(!s.active)return;
  const seq=++s.seq;s.controller?.abort();s.controller=new AbortController();
  const context=capturePageContext();
  try{
    const data=await api('/api/version-datasets',{signal:s.controller.signal});
    if(seq!==s.seq||!isPageContextCurrent(context))return;
    if(!data.items.some(x=>x.id===s.dataset))s.dataset=data.items[0]?.id||'';
    const picker=$('#versionDatasetPicker');picker.innerHTML=data.items.map(x=>`<option value="${escapeHtml(x.id)}">${escapeHtml(x.name)}</option>`).join('');picker.value=s.dataset;
    const current=data.items.find(x=>x.id===s.dataset);
    $('#versionDatasetSummary').textContent=current?`${current.targets} ${uiText('复核案例','review cases')} · ${current.samples} ${uiText('版本抽样','probability samples')} · ${current.low} ${uiText('低置信','low confidence')} · ${current.states.waiting_metadata||0} ${uiText('待齐备','pending source')}`:uiText('等待首次导入','Awaiting first import');
    if(!current){$('#versionDatasetGrid').replaceChildren();return;}
    const [members,batches]=await Promise.all([api(`/api/version-datasets/${encodeURIComponent(s.dataset)}/items?page=${s.page}&mode=${s.mode}`,{signal:s.controller.signal}),api(`/api/version-datasets/${encodeURIComponent(s.dataset)}/batches`,{signal:s.controller.signal})]);
    if(seq!==s.seq||!isPageContextCurrent(context))return;
    $('#versionDatasetGrid').innerHTML=members.items.map(row=>{
      const binding=row.binding||{};
      const url=binding.run_id?pageUrl('review',{issue:row.issue_id,runId:binding.run_id,workSplitId:binding.campaign_id||'',workflowMode:'model_review_and_case_label',comparisonStatus:'all',baselines:['version-'+current.release_family]}):'';
      return `<article class="issue-card"><div class="issue-thumbnail"><img src="${escapeHtml(withBase('/api/case-thumbnails/'+encodeURIComponent(row.issue_id)+'?kind=bev'))}" loading="lazy" decoding="async" alt="${escapeHtml(row.issue_id)} BEV" /></div><div class="issue-card-body"><div class="issue-card-heading">${url?`<a class="issue-id" href="${escapeHtml(url)}">${escapeHtml(row.issue_id)}</a>`:`<span>${escapeHtml(row.issue_id)}</span>`}<span>${row.is_sample?uiText('抽样','Sample'):row.is_low?uiText('低置信','Low'):escapeHtml(row.state)}</span></div><small>${escapeHtml(binding.assignee||'')} · ${escapeHtml(row.trigger||'')}</small></div></article>`;
    }).join('')||`<p class="muted">${uiText('该筛选暂无案例','No cases in this view')}</p>`;
    $('#versionDatasetGrid').querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.hidden=true;},{once:true}));
    $('#versionDatasetPageLabel').textContent=`${members.page} / ${Math.max(1,Math.ceil(members.total/members.page_size))} · ${members.total}`;
    $('#versionDatasetPrev').disabled=members.page<=1;$('#versionDatasetNext').disabled=members.page*members.page_size>=members.total;
    $('#versionDatasetBatches').innerHTML=batches.items.map(b=>`<div><time>${escapeHtml(b.created_at)}</time> · ${uiText('目标纳入','Targets added')} ${b.target_added||0} · ${uiText('候选入库','Candidates')} +${b.added} · ${uiText('更新','Updated')} ${b.changed}</div>`).join('');
    $('#versionDatasetError').textContent='';
  }catch(error){if(seq===s.seq&&!s.controller.signal.aborted)$('#versionDatasetError').textContent=uiText('读取失败，请稍后重试','Read failed; retry shortly');}
  finally{if(s.active&&seq===s.seq)s.timer=setTimeout(loadVersionDatasets,30000);}
}
function bindVersionDatasets(){
  $('#versionDatasetPicker')?.addEventListener('change',event=>{versionDatasetState.dataset=event.target.value;versionDatasetState.page=1;void loadVersionDatasets();});
  $('#versionDatasetMode')?.addEventListener('change',event=>{versionDatasetState.mode=event.target.value;versionDatasetState.page=1;void loadVersionDatasets();});
  $('#versionDatasetPrev')?.addEventListener('click',()=>{versionDatasetState.page--;void loadVersionDatasets();});
  $('#versionDatasetNext')?.addEventListener('click',()=>{versionDatasetState.page++;void loadVersionDatasets();});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bindVersionDatasets,{once:true});else bindVersionDatasets();
