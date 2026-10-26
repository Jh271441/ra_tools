/* Local audit UI; writes require an explicit, actor-bound restore preview. */
const trailHistory = { filters: {}, page: 1, operation: "", data: null, detail: null,
  preview: null, selected: [], reason: "", restoring: false, error: "", busy: false, seq: 0, detailSeq: 0 };

function trailHistorySource(value) {
  const labels = {exclusion_summary:["问题排除 · 汇总","Issue exclusion · Summary"],
    exclusion_direct:["问题排除 · Issue ID","Issue exclusion · Issue ID"],
    rollback:["恢复操作","Restore"],legacy:["旧版历史","Legacy history"]};
  return labels[value] ? uiText(...labels[value]) : value;
}
function trailHistoryStatus(value,source="") {
  if(source==="legacy"&&value==="succeeded")return uiText("旧记录成功","Legacy success");
  const labels = {pending:["待核验","Pending verification"],succeeded:["已回读成功","Readback verified"],
    partial:["部分成功","Partial"],unknown:["结果待核验","Outcome unknown"],conflict:["存在冲突","Conflict"]};
  return labels[value] ? uiText(...labels[value]) : uiText("未知","Unknown");
}
function trailHistoryTime(value) {
  const date = new Date(value);
  return !value || Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(state.uiLanguage === "en" ? "en-GB" : "zh-CN",
    {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(date);
}
function restoreTrailHistoryRoute() {
  const params = new URLSearchParams(location.search);
  const unchanged=trailHistory.data&&trailHistory.operation===(params.get("operation")||"")&&trailHistory.page===Math.max(1,Number(params.get("page"))||1)
    &&["issue_id","actor","source","status","since","until"].every(key=>(trailHistory.filters[key]||"")===(params.get(key)||""));
  if(unchanged)return;
  trailHistory.filters = Object.fromEntries(["issue_id","actor","source","status","since","until"].map(k=>[k,params.get(k)||""]));
  trailHistory.page=Math.max(1,Number(params.get("page"))||1);
  trailHistory.operation=params.get("operation")||"";
  if(!trailHistory.operation&&$("#trailHistoryDialog")?.open){$("#trailHistoryDialog").onclose=null;$("#trailHistoryDialog").close();}
  trailHistory.detail=null;trailHistory.preview=null;trailHistory.reason="";trailHistory.restoring=false;trailHistory.selected=[];trailHistory.detailSeq++;
}
function trailHistoryRouteOptions() {
  return {...trailHistory.filters,page:trailHistory.page>1?trailHistory.page:"",operation:trailHistory.operation};
}
function trailHistoryUrl() {
  history.replaceState({...history.state,page:"trail-history"},"",pageUrl("trail-history"));
}
function trailHistoryText(value) {return escapeHtml(value==null?"—":String(value));}
function trailHistoryBadge(status,source="") {
  const symbols={succeeded:"✓",partial:"◐",pending:"○",unknown:"?",conflict:"!"};
  return `<span class="trail-history-status" data-status="${trailHistoryText(status)}"><span aria-hidden="true">${symbols[status]||"?"}</span> ${trailHistoryStatus(status,source)}</span>`;
}
function trailHistoryMeter(success,total,legacy=false) {
  const percent=total?Math.max(0,Math.min(100,success/total*100)):0;
  const label=legacy?uiText("记录成功 / 总数","Recorded success / total"):uiText("已核验 / 总数","Verified / total");
  return `<div class="trail-history-meter" aria-label="${label}: ${success} / ${total}"><span>${success} / ${total}</span><div class="review-assignment-progress-track" aria-hidden="true"><span style="width:${percent}%"></span></div></div>`;
}
function renderTrailHistoryFilters() {
  const host=$("#trailHistoryFilters");if(!host)return;
  host.innerHTML=`<label>Issue ID<input name="issue_id" autocomplete="off"></label><label>${uiText("操作人 LDAP","Operator LDAP")}<input name="actor" autocomplete="off"></label>
    <label>${uiText("来源","Source")}<select name="source"><option value="">${uiText("全部来源","All sources")}</option>${["exclusion_summary","exclusion_direct","rollback","legacy"].map(v=>`<option value="${v}">${trailHistorySource(v)}</option>`).join("")}</select></label>
    <label>${uiText("执行结果","Outcome")}<select name="status"><option value="">${uiText("全部结果","All outcomes")}</option>${["pending","succeeded","partial","unknown","conflict"].map(v=>`<option value="${v}">${trailHistoryStatus(v)}</option>`).join("")}</select></label>
    <label>${uiText("开始时间（CST）","From (CST)")}<input type="datetime-local" name="since"></label><label>${uiText("结束时间（CST）","Until (CST)")}<input type="datetime-local" name="until"></label>
    <div class="trail-history-filter-actions"><button class="button button-primary" type="submit">${uiText("查询","Search")}</button><button class="button button-secondary" type="button" data-action="reset">${uiText("重置","Reset")}</button></div>`;
  for(const key of ["issue_id","actor","source","status"])host.elements[key].value=trailHistory.filters[key]||"";
  for(const key of ["since","until"]) {
    const value=trailHistory.filters[key];
    if(value&&!Number.isNaN(Date.parse(value)))host.elements[key].value=new Date(Date.parse(value)+8*3600000).toISOString().slice(0,16);
  }
  enhanceDashboardSelects(host);
  host.onsubmit=event=>{
    event.preventDefault();const form=new FormData(host);
    trailHistory.filters=Object.fromEntries(["issue_id","actor","source","status"].map(k=>[k,String(form.get(k)||"").trim()]));
    for(const key of ["since","until"])trailHistory.filters[key]=form.get(key)?new Date(`${form.get(key)}:00+08:00`).toISOString():"";
    trailHistory.page=1;trailHistory.operation="";trailHistoryUrl();void loadTrailHistory();
  };
  host.querySelector('[data-action="reset"]').onclick=()=>{trailHistory.filters={};trailHistory.page=1;trailHistory.operation="";trailHistoryUrl();renderTrailHistoryFilters();void loadTrailHistory();};
}
function renderTrailHistory() {
  const host=$("#trailHistoryResults");if(!host)return;
  const data=trailHistory.data;
  const coverage=$("#trailHistoryCoverage"),coverageOpen=coverage.querySelector("details")?.open;
  coverage.innerHTML=`<details ${coverageOpen?"open":""}><summary>${uiText("问题排除 · 恢复","Exclusion · Restore")} <span class="trail-history-muted">${uiText("覆盖范围","Coverage")}</span></summary><ul class="trail-history-coverage-list"><li>✓ ${uiText("汇总提交、按 Issue ID 提交、恢复","Summary, direct Issue IDs, restores")}</li><li>— ${uiText("未接入：自动回刷、抽样、RD 同步、外部 AutoTriage、Trail 原站","Not connected: daily publication, sampling, RD sync, external AutoTriage, native Trail")}</li><li>— ${uiText("旧版记录无完整快照，不可恢复","Legacy records have no complete snapshots and cannot be restored")}</li></ul>${data?.started_at?`<p>${uiText("新版记录始于","New records since")} ${trailHistoryTime(data.started_at)} CST</p>`:""}</details>`;
  $("#trailHistoryRefresh").textContent=uiText("刷新","Refresh");$("#trailHistoryRefresh").onclick=()=>void loadTrailHistory();
  if(trailHistory.error){host.innerHTML=`<p role="alert">${trailHistoryText(trailHistory.error)}</p>`;return;}
  if(!data){host.innerHTML=`<p role="status">${uiText("正在加载更新记录…","Loading update history…")}</p>`;return;}
  const columns=[uiText("时间（CST）","Time (CST)"),uiText("操作人","Operator"),uiText("来源","Source"),uiText("成功 / 总数","Success / total"),uiText("执行结果","Outcome"),uiText("操作","Actions")];
  host.innerHTML=`<div class="trail-history-table-wrap"><table class="trail-history-table"><thead><tr>${columns.map(c=>`<th>${c}</th>`).join("")}</tr></thead><tbody>${data.items.map(row=>`<tr>
    <td data-label="${columns[0]}">${trailHistoryTime(row.created_at)}</td><td data-label="${columns[1]}">${trailHistoryText(row.actor||uiText("未知","Unknown"))}<small>${row.actor_verified?uiText("已验证身份","Verified identity"):uiText("身份未验证","Unverified identity")}</small></td>
    <td data-label="${columns[2]}">${trailHistorySource(row.source)}</td><td data-label="${columns[3]}">${trailHistoryMeter(row.succeeded_count,row.item_count,row.source==="legacy")}</td>
    <td data-label="${columns[4]}">${trailHistoryBadge(row.status,row.source)}</td>
    <td data-label="${columns[5]}"><button type="button" class="button button-secondary" data-operation="${trailHistoryText(row.id)}">${uiText("详情／回溯","Details / Restore")}</button></td></tr>`).join("")||`<tr><td colspan="6">${uiText("没有匹配的更新记录。","No matching updates.")}</td></tr>`}</tbody></table></div>
    <div class="trail-history-pagination"><span>${uiText(`共 ${data.total} 条 · 第 ${data.page} 页`,`${data.total} records · Page ${data.page}`)}</span><button class="button button-secondary" data-page-step="-1" ${data.page<=1?"disabled":""}>${uiText("上一页","Previous")}</button><button class="button button-secondary" data-page-step="1" ${data.page*data.page_size>=data.total?"disabled":""}>${uiText("下一页","Next")}</button></div>`;
  host.querySelectorAll('[data-operation]').forEach(button=>button.onclick=()=>void openTrailHistoryDetail(button.dataset.operation));
  host.querySelectorAll('[data-page-step]').forEach(button=>button.onclick=()=>{trailHistory.page+=Number(button.dataset.pageStep);trailHistoryUrl();void loadTrailHistory();});
}
async function loadTrailHistory() {
  if(trailHistory.busy)return;
  const context=capturePageContext(),seq=++trailHistory.seq;trailHistory.error="";
  trailHistory.data=null;
  renderTrailHistoryFilters();renderTrailHistory();
  try {
    const data=await api(`/api/trail-history?${new URLSearchParams({...trailHistory.filters,page:String(trailHistory.page)})}`);
    if(seq!==trailHistory.seq||!isPageContextCurrent(context))return;
    trailHistory.data=data;renderTrailHistory();
    if(trailHistory.operation)await openTrailHistoryDetail(trailHistory.operation,{updateUrl:false});
  }catch(error){if(seq!==trailHistory.seq||!isPageContextCurrent(context))return;trailHistory.error=error.message;renderTrailHistory();}
}
function trailHistoryDiff(item,beforeKey="before",afterKey="after",selectable=false) {
  const before=item[beforeKey]||{},after=item[afterKey]||{};
  const display=(obj,key)=>Object.prototype.hasOwnProperty.call(obj,key)?(obj[key]===null?"null":typeof obj[key]==="string"?(obj[key]||uiText("空字符串","Empty string")):JSON.stringify(obj[key])):uiText("字段不存在","Field absent");
  const flag=obj=>typeof obj.should_exclude==="boolean"?`<span class="trail-history-value" data-excluded="${obj.should_exclude}">${obj.should_exclude?uiText("已排除","Excluded"):uiText("未排除","Not excluded")}</span>`:`<span class="trail-history-value">${trailHistoryText(display(obj,"should_exclude"))}</span>`;
  const preview=afterKey==="restore",legacy=trailHistory.detail?.source==="legacy";
  const from=preview?uiText("当前值","Current"):uiText("修改前","Before"),to=preview?uiText("恢复为","Restore to"):uiText("修改后","After");
  const comparison=key=>`<div class="trail-history-diff"><div><small>${from}</small><pre>${trailHistoryText(display(before,key))}</pre></div><span class="trail-history-arrow" aria-hidden="true">→</span><div><small>${to}</small><pre>${trailHistoryText(display(after,key))}</pre></div></div>`;
  const eligible=trailHistory.detail?.outcomes[item.issue_id]==="succeeded";
  const reasonChanged=JSON.stringify(before.should_exclude_comment)!==JSON.stringify(after.should_exclude_comment);
  const flagChanged=JSON.stringify(before.should_exclude)!==JSON.stringify(after.should_exclude);
  return `<section class="trail-history-issue"><div class="trail-history-issue-heading">${selectable?`<label class="trail-history-select"><input type="checkbox" data-restore-issue="${trailHistoryText(item.issue_id)}" aria-label="${trailHistoryText(uiText(`恢复 ${item.issue_id}`,`Restore ${item.issue_id}`))}" ${trailHistory.selected.includes(item.issue_id)?"checked":""} ${!eligible||trailHistory.busy?"disabled":""}><strong>${trailHistoryText(item.issue_id)}</strong></label>`:`<h3>${trailHistoryText(item.issue_id)}</h3>`}${selectable&&!eligible?trailHistoryBadge("unknown"):""}</div>
    ${legacy?`<details data-disclosure="legacy-${trailHistoryText(item.issue_id)}"><summary>${uiText("原记录说明","Recorded note")}</summary><pre class="trail-history-note">${trailHistoryText(display(after,"should_exclude_comment"))}</pre></details>`:`${flagChanged?`<div class="trail-history-transition"><span class="trail-history-muted">${uiText('排除状态','Exclusion')}</span><span><small>${from}</small> ${flag(before)}</span><span class="trail-history-arrow" aria-hidden="true">→</span><span><small>${to}</small> ${flag(after)}</span></div>`:`<div class="trail-history-unchanged"><span>${uiText('排除状态未变','Exclusion unchanged')}</span>${flag(after)}</div>`}
    <details data-disclosure="reason-${afterKey}-${trailHistoryText(item.issue_id)}" ${reasonChanged?"open":""}><summary>${uiText("排除理由","Exclusion reason")} <span class="trail-history-muted">${reasonChanged?uiText("已变化","Changed"):uiText("未变化","Unchanged")}</span></summary>${reasonChanged?comparison("should_exclude_comment"):`<pre class="trail-history-note">${trailHistoryText(display(after,"should_exclude_comment"))}</pre>`}</details>
    <details data-disclosure="marker-${afterKey}-${trailHistoryText(item.issue_id)}"><summary>${uiText("操作标识","Operation markers")}</summary>${comparison("operation_id")}</details>`}</section>`;
}
function trailHistoryTimeline(detail) {
  return `<details data-disclosure="events"><summary>${uiText("执行时间线","Execution timeline")} · ${detail.events.length}</summary><ol class="trail-history-timeline">${detail.events.map(event=>`<li><div>${trailHistoryBadge(event.status,detail.source)}<time>${trailHistoryTime(event.created_at)}</time><span>${trailHistoryText(event.actor)}</span></div><details><summary>${uiText("Issue 结果","Issue outcomes")} · ${Object.keys(event.outcomes).length}</summary><ul>${Object.entries(event.outcomes).map(([issue,status])=>`<li>${trailHistoryText(issue)} ${trailHistoryBadge(status,detail.source)}</li>`).join("")}</ul></details></li>`).join("")}</ol></details>`;
}
function renderTrailRestoreSteps() {
  const host=$("#trailHistoryRestoreSteps");if(!host)return;
  const active=trailHistory.preview?.ready?2:trailHistory.selected.length?1:0;
  host.innerHTML=[uiText("选择 Issue","Select Issues"),uiText("预览差异","Preview changes"),uiText("确认恢复","Confirm restore")].map((label,index)=>`<li ${index===active?'aria-current="step"':""} data-complete="${index<active}"><span aria-hidden="true">${index<active?"✓":index+1}</span>${label}</li>`).join("");
}
function renderTrailHistoryDetail() {
  const dialog=$("#trailHistoryDialog"),detail=trailHistory.detail;if(!dialog||!detail)return;
  const body=dialog.querySelector(".trail-history-dialog-body");
  const scrollTop=body.dataset.operation===detail.id?body.scrollTop:0;
  const active=document.activeElement;
  const focusId=body.contains(active)?active.id:'';
  const focusIssue=body.contains(active)?active.dataset.restoreIssue:'';
  const selection=focusId==='trailHistoryReason'?[active.selectionStart,active.selectionEnd]:null;
  const restoring=trailHistory.restoring&&detail.source!=="legacy"&&trailHistory.data?.can_restore;
  const ready=restoring&&trailHistory.preview?.ready;
  const expanded=body.dataset.operation===detail.id?Array.from(body.querySelectorAll("details[data-disclosure]")).map(el=>[el.dataset.disclosure,el.open]):[];
  body.dataset.operation=detail.id;
  dialog.querySelector("h2").textContent=restoring?uiText("恢复 Trail 更新","Restore Trail update"):uiText("Trail 更新详情","Trail update details");
  dialog.querySelector('[data-action="close"]').textContent=uiText("关闭","Close");
  body.innerHTML=`${restoring?`<section class="trail-history-restore-intro"><ol id="trailHistoryRestoreSteps" class="trail-history-steps" aria-label="${uiText("恢复步骤","Restore steps")}"></ol><p>${uiText("仅恢复所选 Issue 的 Trail 排除状态和理由；本地标注不变。","Restore only the selected Issues’ Trail exclusion state and reason; local labels stay unchanged.")}</p></section>`:''}<div class="trail-history-meta">${trailHistoryBadge(detail.status,detail.source)}<span>${trailHistoryText(detail.actor)}</span><time>${trailHistoryTime(detail.created_at)} CST</time></div><details data-disclosure="operation"><summary>${trailHistorySource(detail.source)} · ${uiText('操作信息','Operation info')}</summary><code class="trail-history-id">${trailHistoryText(detail.id)}</code></details>
    ${detail.source==="legacy"?`<p role="note" class="trail-history-muted">${uiText("旧版记录 · 无完整快照 · 不可恢复","Legacy · No complete snapshots · Restore unavailable")}</p>`:""}
    ${detail.reason?`<p>${trailHistoryText(detail.reason)}</p>`:""}
    ${detail.parent_id?`<p>${uiText("恢复自","Restores")} <button class="button button-secondary" data-related="${trailHistoryText(detail.parent_id)}">${trailHistoryText(detail.parent_id)}</button></p>`:""}
    ${!ready?detail.items.map(item=>trailHistoryDiff(item,"before","after",restoring&&detail.restorable)).join(""):''}
    ${!restoring?trailHistoryTimeline(detail):''}
    ${detail.children.length?`<div>${uiText("后续恢复","Subsequent restores")}: ${detail.children.map(row=>`<button class="button button-secondary" data-related="${trailHistoryText(row.id)}">${trailHistoryTime(row.created_at)} · ${trailHistoryText(row.actor)}</button>`).join(" ")}</div>`:""}
    <section class="trail-history-restore" ${!restoring?'hidden':''}><details data-disclosure="safety"><summary>${uiText("恢复范围与风险","Restore scope and risks")}</summary><p>${uiText("不撤销本地裁决或通知。提交前重新检查冲突并回读；Trail 不支持原子条件写入，仍可能存在外部并发。","Local decisions and notifications stay unchanged. Conflicts are checked before writing and results are read back; Trail has no atomic conditional writes, so external concurrency remains possible.")}</p></details>
    ${!ready?`<button class="button button-secondary" data-action="verify" ${trailHistory.busy?"disabled":""}>${uiText("重新核验 Trail","Verify Trail again")}</button>`:""}
    ${detail.current_conflicts?.length?`<p role="alert">${uiText("当前值已变化：","Current values changed: ")}${detail.current_conflicts.map(trailHistoryText).join(", ")}</p>`:""}
    ${restoring&&detail.restorable?ready?`<p>${uiText('恢复原因：','Restore reason: ')}${trailHistoryText(trailHistory.reason)}</p>`:`<label for="trailHistoryReason">${uiText("恢复原因","Restore reason")}<textarea id="trailHistoryReason" rows="2" maxlength="1000" ${trailHistory.busy?"disabled":""}>${trailHistoryText(trailHistory.reason)}</textarea></label>`:restoring?`<p>${uiText("核验成功后可恢复。","Restore is available after verification.")}</p>`:''}
    <div id="trailHistoryRestoreResult" aria-live="polite">${trailHistory.preview?trailHistory.preview.conflicts.length?`<p role="alert">${uiText("这些 Issue 已发生变化，未写入：","These Issues changed; nothing written: ")}${trailHistory.preview.conflicts.map(trailHistoryText).join(", ")}</p>`:trailHistory.preview.items.map(item=>trailHistoryDiff(item,"current","restore")).join(""):""}</div></section>`;
  for(const [key,open] of expanded)body.querySelectorAll("details[data-disclosure]").forEach(el=>{if(el.dataset.disclosure===key)el.open=open;});
  renderTrailRestoreSteps();
  body.querySelectorAll('[data-related]').forEach(button=>button.onclick=()=>void openTrailHistoryDetail(button.dataset.related));
  body.querySelectorAll('[data-restore-issue]').forEach(input=>input.onchange=()=>{
    trailHistory.selected=Array.from(body.querySelectorAll('[data-restore-issue]:checked')).map(el=>el.dataset.restoreIssue);
    trailHistory.preview=null;$("#trailHistoryRestoreResult").replaceChildren();
    renderTrailRestoreSteps();renderTrailHistoryActions();
  });
  const reason=body.querySelector("textarea");
  if(reason)reason.oninput=()=>{trailHistory.reason=reason.value;trailHistory.preview=null;$("#trailHistoryRestoreResult").replaceChildren();renderTrailRestoreSteps();renderTrailHistoryActions();};
  body.querySelector('[data-action="verify"]')?.addEventListener("click",()=>void verifyTrailHistory());
  renderTrailHistoryActions();
  if(focusId)body.querySelector(`#${focusId}`)?.focus({preventScroll:true});
  if(focusIssue)Array.from(body.querySelectorAll('[data-restore-issue]')).find(el=>el.dataset.restoreIssue===focusIssue)?.focus({preventScroll:true});
  if(selection)body.querySelector('#trailHistoryReason')?.setSelectionRange(...selection);
  body.scrollTop=scrollTop;
}
function renderTrailHistoryActions() {
  const dialog=$('#trailHistoryDialog'),d=trailHistory.detail;if(!dialog||!d)return;
  const allowed=d.source!=='legacy'&&trailHistory.data?.can_restore,editing=allowed&&trailHistory.restoring,ready=editing&&trailHistory.preview?.ready;
  const bind=(action,label,visible,disabled,handler)=>{const b=dialog.querySelector(`[data-action="${action}"]`);b.textContent=label;b.hidden=!visible;b.disabled=trailHistory.busy||disabled;b.onclick=handler;};
  bind('start-restore',uiText('恢复…','Restore…'),allowed&&!editing,false,()=>{trailHistory.restoring=true;trailHistory.selected=[];trailHistory.preview=null;renderTrailHistoryDetail();dialog.querySelector('.trail-history-dialog-body').scrollTop=0;dialog.querySelector('[data-restore-issue]:not(:disabled)')?.focus();});
  bind('cancel-restore',uiText('取消恢复','Cancel restore'),editing,false,()=>{trailHistory.restoring=false;trailHistory.preview=null;trailHistory.selected=[];trailHistory.reason='';renderTrailHistoryDetail();dialog.querySelector('[data-action="start-restore"]').focus();});
  bind('edit-preview',uiText('返回选择','Edit selection'),ready,false,()=>{trailHistory.preview=null;renderTrailHistoryDetail();$('#trailHistoryReason')?.focus();});
  bind('preview',uiText('预览恢复','Preview restore'),editing&&!ready,!d.restorable||!trailHistory.selected.length||!trailHistory.reason.trim(),()=>void previewTrailRestore());
  bind('commit',uiText('确认恢复','Confirm restore'),ready,!ready,()=>void commitTrailRestore());
  const hint=$('#trailHistoryActionHint');
  hint.textContent=!editing?'':trailHistory.busy?uiText('正在处理，请稍候…','Processing, please wait…'):ready?uiText(`将恢复 ${trailHistory.preview.items.length} 个 Issue`,`${trailHistory.preview.items.length} ${trailHistory.preview.items.length===1?'Issue':'Issues'} will be restored`):!d.restorable?uiText('请先重新核验 Trail。','Verify Trail before restoring.'):!trailHistory.selected.length?uiText('请选择要恢复的 Issue。','Select Issues to restore.'):!trailHistory.reason.trim()?uiText('填写恢复原因后预览差异。','Enter a reason to preview changes.'):uiText(`已选 ${trailHistory.selected.length} 个 Issue · 尚未写入`,`${trailHistory.selected.length} selected · Nothing written`);
  hint.hidden=!editing;
  dialog.querySelector('[data-action="close"]').hidden=editing;
  dialog.querySelector('[data-action="close"]').disabled=trailHistory.busy;
}
async function openTrailHistoryDetail(id,{updateUrl=true}={}) {
  if(trailHistory.busy)return;
  const seq=++trailHistory.detailSeq;trailHistory.operation=id;trailHistory.detail=null;trailHistory.preview=null;trailHistory.reason="";trailHistory.restoring=false;trailHistory.selected=[];
  if(updateUrl)trailHistoryUrl();const context=capturePageContext();
  try {
    const detail=await api(`/api/trail-history/${encodeURIComponent(id)}`);
    if(seq!==trailHistory.detailSeq||!isPageContextCurrent(context))return;
    trailHistory.detail=detail;renderTrailHistoryDetail();const dialog=$("#trailHistoryDialog");
    if(!dialog.open){dialog.showModal();dialog.querySelector('[data-action="close"]').focus({preventScroll:true});}
    dialog.oncancel=event=>{if(trailHistory.busy)event.preventDefault();};
    dialog.onclose=()=>{trailHistory.detailSeq++;trailHistory.operation="";trailHistory.preview=null;if(state.activePage==="trail-history")trailHistoryUrl();};
    dialog.querySelector('[data-action="close"]').onclick=()=>dialog.close();
  }catch(error){if(seq===trailHistory.detailSeq&&isPageContextCurrent(context))showToast(error.message,true);}
}
async function previewTrailRestore() {
  if(trailHistory.busy||!trailHistory.restoring)return;
  if(!trailHistory.reason.trim()){showToast(uiText("请填写恢复原因。","Enter a restore reason."),true);$("#trailHistoryReason")?.focus();return;}
  if(!trailHistory.selected.length){showToast(uiText("请选择已核验成功的 Issue。","Select at least one verified Issue."),true);return;}
  const id=trailHistory.operation,context=capturePageContext();trailHistory.preview=null;trailHistory.busy=true;renderTrailHistoryDetail();
  try {
    const preview=await api(`/api/trail-history/${encodeURIComponent(id)}/restore-preview`,{method:"POST",body:JSON.stringify({reason:trailHistory.reason,issue_ids:trailHistory.selected})});
    if(isPageContextCurrent(context)&&trailHistory.operation===id)trailHistory.preview=preview;
  }catch(error){showToast(error.message,true);}finally{
    trailHistory.busy=false;renderTrailHistoryDetail();
    if(trailHistory.preview)$("#trailHistoryRestoreResult")?.scrollIntoView({block:"start"});
  }
}
async function commitTrailRestore() {
  if(trailHistory.busy||!trailHistory.restoring||!trailHistory.preview?.ready)return;
  const id=trailHistory.operation,preview=trailHistory.preview;trailHistory.busy=true;renderTrailHistoryDetail();
  try {
    const result=await api(`/api/trail-history/${encodeURIComponent(id)}/restore-commit`,{method:"POST",body:JSON.stringify({preview_id:preview.preview_id,confirm:true})});
    trailHistory.preview=null;
    showToast(result.ok?uiText("恢复已回读验证。","Restore verified by readback."):uiText("恢复尚未全部验证，请查看执行事件。","Restore is not fully verified; inspect execution events."),!result.ok);
    trailHistory.busy=false;await openTrailHistoryDetail(result.operation_id);
  }catch(error){showToast(error.message,true);}finally{trailHistory.busy=false;renderTrailHistoryDetail();}
}
function refreshTrailHistoryLanguage() {
  if(state.activePage!=="trail-history")return;
  const focused=document.activeElement?.name||"";
  const reasonFocused=document.activeElement?.id==="trailHistoryReason";
  const form=$("#trailHistoryFilters"),values=form?Array.from(form.querySelectorAll("input,select")).map(el=>[el.name,el.value]):[];
  renderTrailHistoryFilters();for(const [name,value] of values)if(form.elements[name])form.elements[name].value=value;
  enhanceDashboardSelects(form);renderTrailHistory();renderTrailHistoryDetail();
  if(reasonFocused)$("#trailHistoryReason")?.focus({preventScroll:true});else if(focused)form.elements[focused]?.focus();
}
async function verifyTrailHistory() {
  if(trailHistory.busy)return;
  const id=trailHistory.operation,seq=trailHistory.detailSeq,context=capturePageContext();trailHistory.busy=true;trailHistory.preview=null;renderTrailHistoryDetail();
  try {
    const detail=await api(`/api/trail-history/${encodeURIComponent(id)}/verify`,{method:"POST",body:"{}"});
    if(seq!==trailHistory.detailSeq||id!==trailHistory.operation||!isPageContextCurrent(context))return;
    trailHistory.detail=detail;
    trailHistory.selected=trailHistory.selected.filter(id=>trailHistory.detail.outcomes[id]==="succeeded");
  }catch(error){showToast(error.message,true);}finally{trailHistory.busy=false;renderTrailHistoryDetail();}
}
