/* Exclusion uses an explicit full task adjudication, never a Trail write. */
const caseExclusionUi = { context: null, drafts: new Map(), saving: false };

function caseExclusionVotes(data) {
  return (data.label_cases || []).flatMap(item => {
    const r = item.resolution || {};
    const votes = r.state === "resolved" && r.method === "adjudication" ? [r.result_revision || {}] : r.heads || [];
    return votes.filter(vote => vote.id).map(vote => ({...vote, caseId:item.id, taskName:item.task_name || (item.task_id ? uiText("任务标注", "Task labels") : uiText("任务外标注", "Independent label")), adjudicated:r.state === "resolved" && r.method === "adjudication"}));
  });
}
function caseExclusionText(value) {
  return value === true ? uiText("排除", "Exclude") : value === false ? uiText("不排除", "Do not exclude") : uiText("未提交意见", "No opinion submitted");
}
function caseExclusionTrailText(data) {
  if (data.trail_metadata_status === "pending") return uiText("查询中", "Checking");
  if (data.trail_metadata_status !== "ready") return uiText("无法确认", "Unconfirmed");
  return typeof data.dashboard_should_exclude === "boolean" ? caseExclusionText(data.dashboard_should_exclude) : uiText("未设置", "Unset");
}
function caseExclusionSummaryMarkup(data) {
  const votes = caseExclusionVotes(data);
  const excluded = data.exclusion_summary?.is_excluded ?? (votes.length ? votes.some(v => v.is_excluded) : null);
  const username = String(state.session?.username || "").toLowerCase();
  const own = (data.label_cases || []).flatMap(c => c.resolution?.heads || []).filter(v => String(v.author || "").toLowerCase() === username);
  const myFlags = new Set(own.map(v => Boolean(v.is_excluded)));
  const mineText = myFlags.size > 1 ? uiText("不同来源意见不一致", "Opinions differ by source") : caseExclusionText(own.length ? Boolean(own[0].is_excluded) : null);
  const decisions = votes.filter(v => v.adjudicated);
  const maintainers = votes.filter(v => v.is_excluded);
  const allowed = hasDashboardWriteRole() && (data.label_cases || []).some(c => c.can_adjudicate_exclusion);
  return `<section id="caseExclusionSummary" class="case-exclusion-summary" aria-label="${uiText("排除状态", "Exclusion status")}"><dl><div><dt>${uiText("我的排除意见（已保存）", "My saved opinion")}</dt><dd>${escapeHtml(mineText)}</dd></div><div><dt>${uiText("当前本地汇总", "Current local result")}</dt><dd>${escapeHtml(caseExclusionText(excluded))}</dd></div><div><dt>${uiText("Trail 状态", "Trail state")}</dt><dd>${escapeHtml(caseExclusionTrailText(data))}</dd></div></dl><p>${uiText("上方复选框仅保存你的意见；其他有效排除意见仍会维持本地排除。", "The checkbox saves your opinion. Other effective exclusion votes can keep the Issue excluded locally.")}</p>${excluded === false && data.trail_metadata_status === "ready" && data.dashboard_should_exclude === true ? `<p class="case-exclusion-warning">${uiText("本地不排除，Trail 仍排除；本地裁决不会撤销 Trail 排除。", "Not excluded locally; still excluded in Trail. A local decision does not undo Trail exclusion.")}</p>` : ""}${maintainers.length ? `<details><summary>${uiText(`维持排除的有效意见 · ${maintainers.length}`, `Effective exclusion votes · ${maintainers.length}`)}</summary>${maintainers.map(v => `<p><strong>${escapeHtml(v.author || "")}</strong> · #${v.id} · ${escapeHtml(formatTime(v.created_at))}<br>${escapeHtml(v.adjudicated ? uiText("任务裁决", "Task decision") : v.taskName)}${v.rationale ? `<br>${escapeHtml(v.rationale)}` : ""}</p>`).join("")}</details>` : ""}${decisions.length ? `<details><summary>${uiText("当前任务裁决与依据", "Current task decisions and rationales")}</summary>${decisions.map(v => `<p><strong>${escapeHtml(v.author || "")} · ${escapeHtml(caseExclusionText(Boolean(v.is_excluded)))}</strong><br>${escapeHtml(formatTime(v.created_at))} · #${v.id}<br>${escapeHtml(v.rationale || uiText("未填写", "Empty"))}</p>`).join("")}</details>` : ""}${allowed ? `<button type="button" class="button button-quiet" id="caseExclusionOpen" aria-haspopup="dialog">${uiText("排除裁决", "Exclusion decision")}</button>` : maintainers.length ? `<small>${uiText("当前来源没有可用的任务裁决入口；保留原意见，不能用普通保存覆盖他人。", "No writable task decision is available for these sources. An ordinary save cannot override other authors.")}</small>` : ""}</section>`;
}
function refreshCaseExclusionSummary() {
  const data = state.caseLabeling.caseData;
  const node = $("#caseExclusionSummary");
  if (!data || !node) return;
  const expanded = node.querySelector("details")?.open;
  node.outerHTML = caseExclusionSummaryMarkup(data);
  if (expanded && $("#caseExclusionSummary details")) $("#caseExclusionSummary details").open = true;
  $("#caseExclusionOpen")?.addEventListener("click", () => openCaseExclusionDecision(data));
}
function rememberCaseExclusionDraft() {
  const c = caseExclusionUi.context;
  if (!c || c.saved || !$("#caseExclusionChoice")) return;
  c.draft = {caseId:$("#caseExclusionTask").value, referenceId:$("#caseExclusionReference").value,
    choice:$("#caseExclusionChoice").value, rationale:$("#caseExclusionRationale").value,
    confirmed:$("#caseExclusionConfirm").checked};
  caseExclusionUi.drafts.set(c.key, c.draft);
  while (caseExclusionUi.drafts.size > 16) caseExclusionUi.drafts.delete(caseExclusionUi.drafts.keys().next().value);
}
function caseExclusionReference(caseItem, id) {
  const r = caseItem?.resolution || {};
  const rows = [...(r.heads || []), ...(r.method === "adjudication" && r.result_revision ? [r.result_revision] : [])];
  return {rows, selected:rows.find(v => String(v.id) === String(id)) || null};
}
function renderCaseExclusionDialog() {
  const c = caseExclusionUi.context;
  if (!c) return;
  const draft = c.draft;
  const tasks = c.caseData.label_cases.filter(v => v.can_adjudicate_exclusion);
  const task = tasks.find(v => v.id === draft.caseId);
  const ref = caseExclusionReference(task, draft.referenceId);
  const selected = ref.selected;
  const option = (value, label, current) => `<option value="${escapeHtml(String(value))}" ${String(value) === String(current) ? "selected" : ""}>${escapeHtml(label)}</option>`;
  const dialog = $("#caseExclusionDialog");
  dialog.innerHTML = `<form class="dialog-card" id="caseExclusionForm"><div class="dialog-heading"><div><small>${escapeHtml(c.caseData.issue_id)}</small><h2 id="caseExclusionTitle">${uiText("排除裁决", "Exclusion decision")}</h2></div><button type="button" class="icon-button" data-close-exclusion aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body"><p class="case-exclusion-warning">${uiText("本次会同时确认该任务的标签结论和排除意见。原记录保留，GT 和 Trail 不变。", "This decision confirms both the task’s label and exclusion. Original records are retained; GT and Trail stay unchanged.")}</p><label>${uiText("裁决哪份任务来源", "Task source to decide")}<select id="caseExclusionTask">${tasks.map((t,i) => option(t.id,t.task_name || uiText(`任务来源 ${i+1}`,`Task source ${i+1}`),draft.caseId)).join("")}</select></label><label>${uiText("采用哪份标签结论", "Label conclusion to adopt")}<select id="caseExclusionReference">${option("",uiText("请选择有效的标签意见", "Choose a valid label opinion"),draft.referenceId)}${ref.rows.filter(v=>EXPECTED_OUTPUT_OPTIONS.some(o=>o.value && o.value===v.expected_output)).map(v => option(v.id,`${v.author} · ${expectedOutputDisplayText(v.expected_output)} · #${v.id}`,draft.referenceId)).join("")}</select></label><div class="case-exclusion-preview">${selected ? `<strong>${uiText("将同时保存的标签结论", "Label conclusion saved together")}</strong><p>${uiText("期望输出", "Expected output")}: ${escapeHtml(expectedOutputDisplayText(selected.expected_output))}</p><p>${uiText("标签", "Tags")}: ${escapeHtml((selected.tags || []).map(tagLabel).join(" · ") || uiText("无", "None"))}</p><p>${uiText("证据缺口", "Evidence gaps")}: ${escapeHtml((selected.evidence_gaps || []).map(evidenceLabel).join(" · ") || uiText("无", "None"))}</p><p>${uiText("原依据", "Original rationale")}: ${escapeHtml(selected.rationale || uiText("未填写", "Empty"))}</p>` : uiText("选择意见后预览完整标签内容。", "Select an opinion to preview its complete label.")}</div><label>${uiText("本次排除结论", "Exclusion decision")}<select id="caseExclusionChoice">${option("",uiText("请选择", "Choose"),draft.choice)}${option("false",uiText("不排除", "Do not exclude"),draft.choice)}${option("true",uiText("排除", "Exclude"),draft.choice)}</select></label><label>${uiText("裁决依据", "Decision rationale")}<textarea id="caseExclusionRationale" rows="3" maxlength="8000">${escapeHtml(draft.rationale)}</textarea></label><p>${uiText("仅替代所选任务的汇总意见。若其他来源仍排除，本地汇总仍会排除。", "Only this task result is replaced. Other excluded sources can keep the local result excluded.")}</p><label class="case-exclusion-confirm"><input type="checkbox" id="caseExclusionConfirm" ${draft.confirmed ? "checked" : ""}/><span>${uiText("确认同时采用以上标签结论和本次排除意见", "Confirm the label conclusion above and this exclusion decision")}</span></label><button type="button" class="button button-quiet" id="caseExclusionRefresh">${uiText("刷新来源意见", "Refresh source opinions")}</button><p class="case-label-decision-error" role="alert" ${c.error ? "" : "hidden"}>${escapeHtml(c.error || "")}</p></div><div class="dialog-actions"><button type="button" class="button button-quiet" data-close-exclusion>${uiText("取消", "Cancel")}</button><button type="submit" class="button button-primary" id="caseExclusionSubmit">${uiText("确认并保存裁决", "Confirm and save decision")}</button></div></form>`;
  dialog.querySelectorAll("[data-close-exclusion]").forEach(b => b.addEventListener("click",()=>dialog.close()));
  $("#caseExclusionForm").addEventListener("input",rememberCaseExclusionDraft);
  $("#caseExclusionForm").addEventListener("change",e=>{
    rememberCaseExclusionDraft();
    if (["caseExclusionTask","caseExclusionReference","caseExclusionChoice"].includes(e.target.id)) {
      if (e.target.id === "caseExclusionTask") { c.draft.referenceId=""; c.draft.choice=""; }
      c.draft.confirmed=false; renderCaseExclusionDialog(); document.getElementById(e.target.id)?.closest(".ui-select")?.querySelector("button")?.focus();
    }
  });
  $("#caseExclusionForm").addEventListener("submit",e=>{e.preventDefault();void saveCaseExclusionDecision();});
  $("#caseExclusionRefresh").addEventListener("click", () => { void refreshCaseExclusionSources(); });
  syncCaseExclusionSaving();
}
function expectedOutputDisplayText(value) {
  const option = EXPECTED_OUTPUT_OPTIONS.find(item=>item.value===value);
  return option ? (i18nLocale()==="en" ? option.labelEn : option.labelZh) : value;
}
function syncCaseExclusionSaving() {
  const dialog = $("#caseExclusionDialog");
  if (!dialog) return;
  dialog.querySelectorAll("select,textarea,input,button[type=submit],#caseExclusionRefresh").forEach(node=>{node.disabled=caseExclusionUi.saving;});
  dialog.querySelectorAll("select").forEach(select => enhanceNativeUiSelect(select));
  const save=$("#caseExclusionSubmit");
  if (save) save.textContent=caseExclusionUi.saving ? uiText("保存中…", "Saving…") : uiText("确认并保存裁决", "Confirm and save decision");
}
function openCaseExclusionDecision(data) {
  if (caseExclusionUi.saving || !hasDashboardWriteRole()) return;
  const tasks=(data.label_cases || []).filter(t=>t.can_adjudicate_exclusion);
  if (!tasks.length) return;
  const key=JSON.stringify([data.issue_id,selectedBaselineQueryValue(),tasks.map(t=>[t.id,(t.resolution.heads||[]).map(v=>v.id),t.resolution.adjudication?.id])]);
  let dialog=$("#caseExclusionDialog");
  if (!dialog) {
    dialog=document.createElement("dialog");dialog.id="caseExclusionDialog";dialog.className="dialog case-label-decision-dialog";
    dialog.setAttribute("aria-labelledby","caseExclusionTitle");document.body.appendChild(dialog);
    dialog.addEventListener("click",e=>{if(e.target===dialog)dialog.close();});
    dialog.addEventListener("close",()=>{rememberCaseExclusionDraft();if(state.caseLabeling.issueId===caseExclusionUi.context?.caseData.issue_id)$("#caseExclusionOpen")?.focus();});
  }
  caseExclusionUi.context={caseData:JSON.parse(JSON.stringify(data)),key,pageContext:capturePageContext(),baselines:selectedBaselineQueryValue(),error:"",draft:caseExclusionUi.drafts.get(key)||{caseId:tasks[0].id,referenceId:"",choice:"",rationale:"",confirmed:false}};
  renderCaseExclusionDialog();dialog.showModal();
}
function refreshCaseExclusionLanguage() {
  refreshCaseExclusionSummary();
  if (!$("#caseExclusionDialog")?.open) return;
  const focus=document.activeElement?.id;
  const start=$("#caseExclusionRationale")?.selectionStart,end=$("#caseExclusionRationale")?.selectionEnd;
  rememberCaseExclusionDraft();renderCaseExclusionDialog();document.getElementById(focus)?.focus();
  if(focus==="caseExclusionRationale")$("#caseExclusionRationale").setSelectionRange(start,end);
}
function caseExclusionErrorMessage(error) {
  const message=String(error?.message || "");
  const known=[
    ["裁决范围不合法。", "Invalid decision scope."],
    ["请确认完整标签结论并填写裁决依据。", "Confirm the full label and enter a decision rationale."],
    ["该任务当前只读，不能提交标注裁决。", "This task is read-only; decisions cannot be saved."],
    ["参与裁决的标注版本已变化，请刷新后重新裁决。", "Source opinions changed. Refresh sources and confirm again."],
    ["该 Case 已有更新的裁决，请刷新后重试。", "A newer decision exists. Refresh sources and confirm again."],
    ["当前任务标注没有需要裁决的冲突。", "No reviewable exclusion or label conflict remains in this task."],
    ["裁决必须选择有效的期望输出。", "Choose a valid expected output for this decision."],
    ["裁决依据不能超过 8000 个字符。", "Decision rationale must not exceed 8,000 characters."],
  ];
  const found=known.find(([zh])=>message.includes(zh));
  return found ? uiText(...found) : message;
}
async function refreshCaseExclusionSources() {
  const c=caseExclusionUi.context;
  if(!c || caseExclusionUi.saving) return;
  rememberCaseExclusionDraft();caseExclusionUi.saving=true;syncCaseExclusionSaving();
  try {
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
    if(!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId!==c.caseData.issue_id || selectedBaselineQueryValue()!==c.baselines) return;
    const tasks=(fresh.label_cases || []).filter(t=>t.can_adjudicate_exclusion);
    caseExclusionUi.drafts.delete(c.key);
    c.caseData=fresh;
    c.key=JSON.stringify([fresh.issue_id,c.baselines,tasks.map(t=>[t.id,(t.resolution.heads||[]).map(v=>v.id),t.resolution.adjudication?.id])]);
    if(!tasks.some(t=>t.id===c.draft.caseId))c.draft.caseId=tasks[0]?.id || "";
    c.draft.referenceId="";c.draft.confirmed=false;
    c.error=tasks.length ? "" : uiText("当前没有可裁决的任务来源。", "No writable task source remains.");
    caseExclusionUi.drafts.set(c.key,c.draft);
    renderCaseExclusionDialog();
  } catch(error) {c.error=caseExclusionErrorMessage(error);renderCaseExclusionDialog();}
  finally {caseExclusionUi.saving=false;syncCaseExclusionSaving();}
}
async function saveCaseExclusionDecision() {
  const c=caseExclusionUi.context;
  if (!c || caseExclusionUi.saving || !hasDashboardWriteRole()) return;
  if (!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId!==c.caseData.issue_id || selectedBaselineQueryValue()!==c.baselines) return;
  rememberCaseExclusionDraft();
  const d=c.draft,task=c.caseData.label_cases.find(t=>t.id===d.caseId && t.can_adjudicate_exclusion);
  const ref=caseExclusionReference(task,d.referenceId).selected;
  if (!task || !ref?.expected_output || !["false","true"].includes(d.choice) || !d.rationale.trim() || !d.confirmed) {
    showToast(uiText("请选择标签结论和排除意见，填写依据并确认完整裁决。", "Choose a label and exclusion decision, enter a rationale and confirm the full decision."),true);return;
  }
  const payload={expected_output:ref.expected_output,tags:ref.tags||[],evidence_gaps:ref.evidence_gaps||[],is_excluded:d.choice==="true",rationale:d.rationale.trim(),source_revision_ids:task.resolution.heads.map(v=>v.id),expected_previous_resolution_id:task.resolution.adjudication?.id||null,adjudication_scope:"exclusion",confirm_full_label:true};
  caseExclusionUi.saving=true;syncCaseExclusionSaving();
  try {
    const result=await api(`/api/labeling/label-cases/${encodeURIComponent(task.id)}/adjudications`,{method:"POST",body:JSON.stringify(payload)});
    acknowledgeLocalChange(result);c.saved=true;caseExclusionUi.drafts.delete(c.key);$("#caseExclusionDialog")?.close();
    showToast(uiText("本地裁决已保存，Trail 未修改。", "Local decision saved; Trail unchanged."));
    try {
      const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
      if(isPageContextCurrent(c.pageContext) && state.caseLabeling.issueId===c.caseData.issue_id && selectedBaselineQueryValue()===c.baselines) {
        const data=state.caseLabeling.caseData;
        for(const key of ["label_cases","label_state","label_source_contexts","decision_history","exclusion_summary"])data[key]=fresh[key];
        refreshCaseExclusionSummary();refreshCaseLabelDecisionLanguage();
        // Do not rerender ordinary labels, clear images, or navigate after this save.
      }
    } catch (_) {showToast(uiText("裁决已保存，汇总刷新失败，请刷新查看。", "Decision saved; summary refresh failed. Refresh to view it."),true);}
  } catch(error) {
    c.error=caseExclusionErrorMessage(error);const node=$("#caseExclusionDialog .case-label-decision-error");if(node){node.textContent=c.error;node.hidden=false;}
    if(!$("#caseExclusionDialog")?.open)showToast(c.error,true);
  } finally {caseExclusionUi.saving=false;syncCaseExclusionSaving();}
}
