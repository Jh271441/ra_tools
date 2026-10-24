/* Local audit UI; writes require an explicit, actor-bound restore preview. */
const trailHistory = { filters: {}, page: 1, operation: "", data: null, detail: null,
  preview: null, selected: [], reason: "", error: "", busy: false, seq: 0, detailSeq: 0 };

function trailHistorySource(value) {
  const labels = {exclusion_summary:["问题排除 · 汇总","Issue exclusion · Summary"],
    exclusion_direct:["问题排除 · Issue ID","Issue exclusion · Issue ID"],
    rollback:["恢复操作","Restore"],legacy:["旧版历史","Legacy history"]};
  return labels[value] ? uiText(...labels[value]) : value;
}
function trailHistoryStatus(value) {
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
  trailHistory.detail=null;trailHistory.preview=null;trailHistory.reason="";trailHistory.detailSeq++;
}
function trailHistoryRouteOptions() {
  return {...trailHistory.filters,page:trailHistory.page>1?trailHistory.page:"",operation:trailHistory.operation};
}
function trailHistoryUrl() {
  history.replaceState({...history.state,page:"trail-history"},"",pageUrl("trail-history"));
}
function trailHistoryText(value) {return escapeHtml(value==null?"—":String(value));}
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
  $("#trailHistoryCoverage").textContent=uiText(
    "覆盖：问题排除汇总、按 Issue ID 排除及恢复操作。自动回刷、抽样、RD 同步、外部 AutoTriage 和 Trail 原站尚未接入。旧版历史缺少完整快照，不可恢复。",
    "Coverage: exclusion summary, direct Issue ID exclusion and restores. Daily publication, sampling, RD sync, external AutoTriage and native Trail edits are not connected. Legacy history lacks complete snapshots and cannot be restored.")+(data?.started_at?uiText(` 新版记录始于 ${trailHistoryTime(data.started_at)} CST。`,` New records start at ${trailHistoryTime(data.started_at)} CST.`):"");
  $("#trailHistoryRefresh").textContent=uiText("刷新","Refresh");$("#trailHistoryRefresh").onclick=()=>void loadTrailHistory();
  if(trailHistory.error){host.innerHTML=`<p role="alert">${trailHistoryText(trailHistory.error)}</p>`;return;}
  if(!data){host.innerHTML=`<p role="status">${uiText("正在加载更新记录…","Loading update history…")}</p>`;return;}
  const columns=[uiText("时间（CST）","Time (CST)"),uiText("操作人","Operator"),uiText("来源","Source"),uiText("Issue 数","Issues"),uiText("执行结果","Outcome"),uiText("操作","Actions")];
  host.innerHTML=`<div class="trail-history-table-wrap"><table class="trail-history-table"><thead><tr>${columns.map(c=>`<th>${c}</th>`).join("")}</tr></thead><tbody>${data.items.map(row=>`<tr>
    <td data-label="${columns[0]}">${trailHistoryTime(row.created_at)}</td><td data-label="${columns[1]}">${trailHistoryText(row.actor||uiText("未知","Unknown"))}<small>${row.actor_verified?uiText("已验证身份","Verified identity"):uiText("身份未验证","Unverified identity")}</small></td>
    <td data-label="${columns[2]}">${trailHistorySource(row.source)}</td><td data-label="${columns[3]}">${row.succeeded_count} / ${row.item_count}</td>
    <td data-label="${columns[4]}"><span class="trail-history-status" data-status="${row.status}">${trailHistoryStatus(row.status)}</span></td>
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
  const names={should_exclude:uiText("排除标记","Excluded"),should_exclude_comment:uiText("排除理由","Exclusion reason"),operation_id:uiText("操作 ID","Operation ID")};
  const display=(obj,key)=>Object.prototype.hasOwnProperty.call(obj,key)?(obj[key]===null?"null":typeof obj[key]==="string"?(obj[key]||uiText("空字符串","Empty string")):JSON.stringify(obj[key])):uiText("字段不存在","Field absent");
  const eligible=trailHistory.detail?.outcomes[item.issue_id]==="succeeded";
  return `<section class="trail-history-issue"><h3>${trailHistoryText(item.issue_id)}</h3>${selectable?`<label class="trail-history-select"><input type="checkbox" data-restore-issue="${trailHistoryText(item.issue_id)}" ${trailHistory.selected.includes(item.issue_id)?"checked":""} ${!eligible||trailHistory.busy?"disabled":""}>${eligible?uiText("选择恢复此 Issue","Select this Issue to restore"):uiText("结果未核验，不能恢复","Unverified outcome; restore unavailable")}</label>`:""}${Object.keys(names).map(key=>`<div class="trail-history-diff"><strong>${names[key]}</strong><div><small>${uiText("修改前","Before")}</small><pre>${trailHistoryText(display(before,key))}</pre></div><div><small>${uiText("修改后","After")}</small><pre>${trailHistoryText(display(after,key))}</pre></div></div>`).join("")}</section>`;
}
function renderTrailHistoryDetail() {
  const dialog=$("#trailHistoryDialog"),detail=trailHistory.detail;if(!dialog||!detail)return;
  const body=dialog.querySelector(".trail-history-dialog-body");
  dialog.querySelector("h2").textContent=uiText("Trail 更新详情","Trail update details");
  dialog.querySelector('[data-action="close"]').textContent=uiText("关闭","Close");
  body.innerHTML=`<p>${trailHistoryTime(detail.created_at)} CST · ${trailHistoryText(detail.actor)} · ${trailHistorySource(detail.source)} · ${trailHistoryStatus(detail.status)}</p><code class="trail-history-id">${trailHistoryText(detail.id)}</code>
    ${detail.source==="legacy"?`<p role="note">${uiText("旧版记录只保留说明和结果，以下不是完整的远端前后快照；不能恢复。","Legacy records retain notes and outcomes only. Values below are not complete remote snapshots; restore is unavailable.")}</p>`:""}
    ${detail.reason?`<p>${trailHistoryText(detail.reason)}</p>`:""}
    ${detail.parent_id?`<p>${uiText("恢复自","Restores")} <button class="button button-secondary" data-related="${trailHistoryText(detail.parent_id)}">${trailHistoryText(detail.parent_id)}</button></p>`:""}
    ${detail.items.map(item=>trailHistoryDiff(item,"before","after",detail.source!=="legacy"&&trailHistory.data?.can_restore)).join("")}
    <details><summary>${uiText("执行事件","Execution events")} (${detail.events.length})</summary>${detail.events.map(event=>`<p>${trailHistoryTime(event.created_at)} · ${trailHistoryText(event.actor)} · ${trailHistoryStatus(event.status)} · ${Object.entries(event.outcomes).map(([issue,status])=>`${trailHistoryText(issue)}: ${trailHistoryStatus(status)}`).join("; ")}</p>`).join("")}</details>
    ${detail.children.length?`<div>${uiText("后续恢复","Subsequent restores")}: ${detail.children.map(row=>`<button class="button button-secondary" data-related="${trailHistoryText(row.id)}">${trailHistoryTime(row.created_at)} · ${trailHistoryText(row.actor)}</button>`).join(" ")}</div>`:""}
    <section class="trail-history-restore"><p>${uiText("恢复仅撤销本次 Trail 字段变更，不撤销本地标注、裁决或通知。执行前会重新检查；Trail 不支持原子条件写入，仍存在外部并发风险。","Restore only reverses this Trail change, not local labels, decisions or notifications. State is checked again before writing; Trail has no atomic conditional writes, so external concurrency remains a risk.")}</p>
    ${detail.source!=="legacy"&&trailHistory.data?.can_restore?`<button class="button button-secondary" data-action="verify" ${trailHistory.busy?"disabled":""}>${uiText("重新核验 Trail","Verify Trail again")}</button>`:""}
    ${detail.current_conflicts?.length?`<p role="alert">${uiText("当前值已变化：","Current values changed: ")}${detail.current_conflicts.map(trailHistoryText).join(", ")}</p>`:""}
    ${detail.restorable&&trailHistory.data?.can_restore?`<label>${uiText("恢复原因","Restore reason")}<textarea id="trailHistoryReason" maxlength="1000" ${trailHistory.busy?"disabled":""}>${trailHistoryText(trailHistory.reason)}</textarea></label><button class="button button-secondary" data-action="preview" ${trailHistory.busy?"disabled":""}>${uiText("预览恢复","Preview restore")}</button>`:`<p>${uiText("恢复不可用：所选 Issue 需有成功回执，且需要管理员权限和已开启的恢复开关。","Selected Issues need verified receipts; restore also requires administrator access and an enabled restore gate.")}</p>`}
    <div id="trailHistoryRestoreResult" aria-live="polite">${trailHistory.preview?trailHistory.preview.conflicts.length?`<p>${uiText("这些 Issue 已发生变化，未写入：","These Issues changed; nothing written: ")}${trailHistory.preview.conflicts.map(trailHistoryText).join(", ")}</p>`:`${trailHistory.preview.items.map(item=>trailHistoryDiff(item,"current","restore")).join("")}<p>${uiText("确认后将恢复以上全部 Issue。","Confirmation restores all Issues shown above.")}</p>`:""}</div></section>`;
  body.querySelectorAll('[data-related]').forEach(button=>button.onclick=()=>void openTrailHistoryDetail(button.dataset.related));
  body.querySelectorAll('[data-restore-issue]').forEach(input=>input.onchange=()=>{
    trailHistory.selected=Array.from(body.querySelectorAll('[data-restore-issue]:checked')).map(el=>el.dataset.restoreIssue);
    trailHistory.preview=null;dialog.querySelector('[data-action="commit"]').disabled=true;$("#trailHistoryRestoreResult").replaceChildren();
  });
  const reason=body.querySelector("textarea");
  if(reason)reason.oninput=()=>{trailHistory.reason=reason.value;trailHistory.preview=null;dialog.querySelector('[data-action="commit"]').disabled=true;$("#trailHistoryRestoreResult").replaceChildren();};
  body.querySelector('[data-action="preview"]')?.addEventListener("click",()=>void previewTrailRestore());
  body.querySelector('[data-action="verify"]')?.addEventListener("click",()=>void verifyTrailHistory());
  const commit=dialog.querySelector('[data-action="commit"]');
  commit.textContent=uiText("确认恢复","Confirm restore");commit.hidden=!detail.restorable||!trailHistory.data?.can_restore;
  commit.disabled=trailHistory.busy||!trailHistory.preview?.ready;commit.onclick=()=>void commitTrailRestore();
  dialog.querySelector('[data-action="close"]').disabled=trailHistory.busy;
}
async function openTrailHistoryDetail(id,{updateUrl=true}={}) {
  if(trailHistory.busy)return;
  const seq=++trailHistory.detailSeq;trailHistory.operation=id;trailHistory.detail=null;trailHistory.preview=null;trailHistory.reason="";
  if(updateUrl)trailHistoryUrl();const context=capturePageContext();
  try {
    const detail=await api(`/api/trail-history/${encodeURIComponent(id)}`);
    if(seq!==trailHistory.detailSeq||!isPageContextCurrent(context))return;
    trailHistory.detail=detail;trailHistory.selected=detail.items.filter(item=>detail.outcomes[item.issue_id]==="succeeded").map(item=>item.issue_id);renderTrailHistoryDetail();const dialog=$("#trailHistoryDialog");
    if(!dialog.open)dialog.showModal();
    dialog.oncancel=event=>{if(trailHistory.busy)event.preventDefault();};
    dialog.onclose=()=>{trailHistory.detailSeq++;trailHistory.operation="";trailHistory.preview=null;if(state.activePage==="trail-history")trailHistoryUrl();};
    dialog.querySelector('[data-action="close"]').onclick=()=>dialog.close();
  }catch(error){if(seq===trailHistory.detailSeq&&isPageContextCurrent(context))showToast(error.message,true);}
}
async function previewTrailRestore() {
  if(trailHistory.busy)return;
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
  if(trailHistory.busy||!trailHistory.preview?.ready)return;
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
  if(reasonFocused)$("#trailHistoryReason")?.focus();else if(focused)form.elements[focused]?.focus();
}
async function verifyTrailHistory() {
  if(trailHistory.busy)return;
  const id=trailHistory.operation;trailHistory.busy=true;trailHistory.preview=null;renderTrailHistoryDetail();
  try {
    trailHistory.detail=await api(`/api/trail-history/${encodeURIComponent(id)}/verify`,{method:"POST",body:"{}"});
    trailHistory.selected=trailHistory.detail.items.filter(item=>trailHistory.detail.outcomes[item.issue_id]==="succeeded").map(item=>item.issue_id);
  }catch(error){showToast(error.message,true);}finally{trailHistory.busy=false;renderTrailHistoryDetail();}
}
