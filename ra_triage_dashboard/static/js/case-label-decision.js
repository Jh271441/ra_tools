/* Complete Issue decisions reuse the main labeling form; personal drafts stay separate. */
const caseLabelDecisionUi = {context:null, drafts:new Map(), saving:false, editor:null};
function caseLabelHasIssueDecision(data) { return Boolean(data?.label_state?.sources?.length || data?.label_state?.decision || data?.label_cases?.length); }
function caseDecisionSourceName(data, source, index = 0) {
  const context = data.label_source_contexts?.[source.label_case_id || source.id] || {};
  const linked = (context.combined_reviews || []).map(item => item.task_name).filter(Boolean);
  return linked.length ? [...new Set(linked)].join(" · ") : source.task_name || context.task_name
    || (source.task_id ? uiText(`标注任务 ${index + 1}`, `Labeling task ${index + 1}`) : uiText("Issue 标注", "Issue label"));
}
function caseDecisionStateText(value) {
  return ({resolved:uiText("已确认", "Confirmed"), conflict:uiText("有分歧", "Disagreement"), stale:uiText("待复核", "Needs recheck"), pending:uiText("待补齐", "Incomplete"), none:uiText("待补齐", "Incomplete")})[value] || uiText("待补齐", "Incomplete");
}
function caseDecisionImageMarkup(images) {
  return (images || []).map(a => `<a class="case-decision-image" href="${escapeHtml(a.url || withBase(`/api/labeling/attachments/${encodeURIComponent(a.id)}`))}" target="_blank" rel="noopener"><img loading="lazy" src="${escapeHtml(a.url || withBase(`/api/labeling/attachments/${encodeURIComponent(a.id)}`))}" alt="${escapeHtml(uiText("标注截图", "Label evidence"))}" /></a>`).join("");
}
function caseDecisionRecordMarkup(vote, sourceName, kind = "", adopt = false) {
  const full = vote.full_result;
  const rationale = (full ? vote.label_rationale : vote.rationale) || "";
  const badges = `${vote.expected_output ? labelBadge(vote.expected_output, "—", expectedOutputDisplayText(vote.expected_output)) : `<span class="tag">${uiText("待补齐分类", "Classification missing")}</span>`}<span class="tag ${vote.is_excluded === true ? "exclusion-tag" : ""}">${escapeHtml(caseExclusionText(vote.is_excluded))}</span>`;
  const sourceMeta = [sourceName, `${uiText("版本", "Revision")} ${vote.id}`, kind].filter(Boolean).map(escapeHtml).join(" · ");
  const meta = `<span>${sourceMeta}</span>${vote.tags?.length ? `<span class="tags">${vote.tags.map(tag => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</span>` : ""}${!rationale ? `<span class="history-record-empty">${uiText("未填写标注依据", "No label rationale")}</span>` : ""}`;
  const body = `${rationale ? `<p>${escapeHtml(rationale)}</p>` : ""}
    ${full ? `${vote.rationale ? `<p><strong>${uiText("裁决人补充依据", "Decision review rationale")}</strong> ${escapeHtml(vote.rationale)}</p>` : ""}${full.adopted_revision ? `<small class="history-record-meta">${escapeHtml(uiText(`采纳 ${full.adopted_revision.author} 的版本 ${full.adopted_revision_id}`, `Adopted ${full.adopted_revision.author}'s revision ${full.adopted_revision_id}`))}</small>` : ""}` : ""}
    ${vote.attachments?.length ? `<div class="case-decision-images">${caseDecisionImageMarkup(vote.attachments)}</div>` : ""}`;
  const actions = adopt && hasDashboardWriteRole() ? `<button type="button" class="history-inline-button history-adopt-button" data-adopt-decision="${Number(vote.id)}">${uiText("采用此标注", "Use this label")}</button>` : "";
  return historyRecordMarkup({author:vote.author || vote.created_by || uiText("未记录作者", "Unknown author"),createdAt:vote.created_at,badges,meta,body,actions});
}

function caseDecisionFlowMarkup(data) {
  const explanation = caseLabelExplanation(data), result = data.label_state || {}, decision = result.decision;
  const excluded = data.exclusion_summary?.is_excluded;
  const exclusionState = decision?.stale && decision.full_result ? "stale" : caseExclusionNeedsDecision(data) ? "conflict" : typeof excluded === "boolean" ? "resolved" : "pending";
  const missing = (result.sources || []).flatMap(s => (s.revision_summaries || []).filter(r => !r.expected_output).map(r => r.author));
  const labelMissing = missing.length ? uiText(`缺少分类：${[...new Set(missing)].join("、")}`, `Classification missing: ${[...new Set(missing)].join(", ")}`) : "";
  return `<section class="case-decision-result"><p><strong>${uiText("分类", "Classification")}</strong> ${escapeHtml(caseDecisionStateText(explanation.status))}${explanation.output ? ` · ${escapeHtml(expectedOutputDisplayText(explanation.output))}` : ""}</p><p class="quiet-meta">${escapeHtml(explanation.reason)}${labelMissing ? ` · ${escapeHtml(labelMissing)}` : ""}</p><p><strong>${uiText("是否排除", "Exclusion")}</strong> ${escapeHtml(caseDecisionStateText(exclusionState))} · ${escapeHtml(caseExclusionText(excluded))}</p><p class="quiet-meta">${decision?.full_result && !decision.stale ? uiText("完整 Issue 裁决生效", "Complete Issue decision applies") : uiText("当前来源意见汇总；有分歧时暂按排除生效", "Aggregated source opinions; disagreement provisionally excludes the Issue")} · Trail: ${escapeHtml(caseExclusionTrailText(data))}</p>${decision ? `<p class="quiet-meta">${escapeHtml(decision.created_by)} · ${escapeHtml(formatTime(decision.created_at))}${decision.stale ? ` · ${uiText("来源已有新版本，请对照下方意见复核", "Sources have new revisions; compare the opinions below")}` : ""}</p>` : ""}</section>`;
}
function caseDecisionRevisions(data) {
  const heads = new Set((data.label_state?.sources || []).flatMap(s => s.source_revision_ids || []));
  const rows = (data.label_cases || []).flatMap((c,i) => (c.revisions || c.resolution?.heads || []).map(r => ({...r, sourceName:caseDecisionSourceName(data,c,i), historical:!heads.has(r.id)})));
  return [...new Map(rows.map(r => [r.id,r])).values()].sort((a,b) => b.id-a.id);
}
function caseLabelDecisionMarkup(data) {
  const rows = caseDecisionRevisions(data), current = rows.filter(r => !r.historical), old = rows.filter(r => r.historical);
  const history = data.decision_history || [];
  return `${caseDecisionFlowMarkup(data)}<h3 class="case-decision-section-title">${uiText("每人的当前标注", "Current labels")}</h3><div class="case-decision-records history-dialog-content">${current.map(r => caseDecisionRecordMarkup(r,r.sourceName,"",true)).join("") || `<p>${uiText("暂无标注，请先保存个人标注。", "No labels yet. Save a personal label first.")}</p>`}</div>${old.length ? `<details class="case-decision-history"><summary>${uiText("历史标注", "Earlier labels")} · ${old.length}</summary><div class="case-decision-records history-dialog-content">${old.map(r => caseDecisionRecordMarkup(r,r.sourceName,uiText("旧版本", "Earlier revision"),true)).join("")}</div></details>` : ""}${history.length ? `<details class="case-decision-history"><summary>${uiText("裁决记录", "Decision history")} · ${history.length}</summary><div class="case-decision-records history-dialog-content">${history.map(r => caseDecisionRecordMarkup(r,uiText("Issue 裁决", "Issue decision"))).join("")}</div></details>` : ""}`;
}
function renderCaseLabelDecisionDialog() {
  const c = caseLabelDecisionUi.context, dialog = $("#caseLabelDecisionDialog");
  if (!c || !dialog) return;
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><div><h2 id="caseLabelDecisionTitle">${uiText("标注与裁决", "Labels and decisions")}</h2><small>${escapeHtml(c.caseData.issue_id)}</small></div><button type="button" class="icon-button" data-close-decision aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body" id="caseDecisionEvidence">${caseLabelDecisionMarkup(c.caseData)}</div><div class="dialog-actions"><button type="button" class="button button-quiet" id="caseDecisionRefresh">${uiText("刷新来源", "Refresh sources")}</button><button type="button" class="button button-primary" id="caseDecisionRelabel" ${!hasDashboardWriteRole() || !caseDecisionRevisions(c.caseData).length ? "disabled" : ""}>${uiText("重新标注并裁决", "Relabel and decide")}</button><button type="button" class="button button-quiet" data-close-decision>${uiText("关闭", "Close")}</button></div></div>`;
  dialog.querySelectorAll("[data-close-decision]").forEach(b => b.addEventListener("click", () => dialog.close()));
  dialog.querySelectorAll("[data-adopt-decision]").forEach(b => b.addEventListener("click", () => startCaseDecisionEditor(c.caseData, Number(b.dataset.adoptDecision))));
  $("#caseDecisionRelabel").addEventListener("click", () => startCaseDecisionEditor(c.caseData));
  $("#caseDecisionRefresh").addEventListener("click", () => void refreshUnifiedCaseDecisionSources());
  if (c.compareEditor && c.compareEditor === caseLabelDecisionUi.editor) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "button button-primary";
    button.textContent = uiText("已对照，保留草稿继续裁决", "Reviewed; continue with my draft");
    button.addEventListener("click", () => {
      const editor = c.compareEditor;
      if (caseLabelDecisionUi.saving || editor !== caseLabelDecisionUi.editor || !isPageContextCurrent(editor.pageContext)
          || selectedBaselineQueryValue() !== editor.baselines || (editor.actor && editor.actor !== state.session?.username)) return;
      editor.data = structuredClone(c.caseData);
      $("#caseDecisionConfirmExclusion").checked = false;
      rememberCaseLabelDecisionDraft(); dialog.close();
    });
    dialog.querySelector(".dialog-actions").appendChild(button);
  }
}
function openCaseLabelDecision(data, {compareEditor = null} = {}) {
  if (caseLabelDecisionUi.saving) return;
  let dialog = $("#caseLabelDecisionDialog");
  if (!dialog) {
    dialog = document.createElement("dialog"); dialog.id = "caseLabelDecisionDialog";
    dialog.className = "dialog case-label-decision-dialog history-dialog"; dialog.setAttribute("aria-labelledby","caseLabelDecisionTitle");
    dialog.addEventListener("click", e => {if(e.target === dialog) dialog.close();});
    dialog.addEventListener("close", () => $("#caseLabelGoAdjudication")?.focus()); document.body.appendChild(dialog);
  }
  caseLabelDecisionUi.context = {caseData:structuredClone(data),baselines:selectedBaselineQueryValue(),pageContext:capturePageContext(),mode:"issue",compareEditor};
  renderCaseLabelDecisionDialog(); dialog.showModal();
}
function bindCaseLabelResultActions(data) {
  $("#caseDecisionInfo")?.addEventListener("click", showCaseDecisionInfo);
  $("#caseLabelGoAdjudication")?.addEventListener("click", () => openCaseLabelDecision(data));
}
function caseDecisionDraftKey(data) {
  return JSON.stringify([data.issue_id,selectedBaselineQueryValue(),state.caseLabeling.taskId || "",(state.session?.username || "")]);
}
function startCaseDecisionEditor(data, revisionId = null) {
  if (!hasDashboardWriteRole() || caseLabelDecisionUi.saving || data.issue_id !== state.caseLabeling.issueId) return;
  if (caseLabelDecisionUi.editor) exitCaseDecisionEditor();
  const adopted = revisionId == null ? null : caseDecisionRevisions(data).find(r => r.id === revisionId);
  if (revisionId != null && !adopted) return;
  const key = caseDecisionDraftKey(data), saved = caseLabelDecisionUi.drafts.get(key);
  const reuse = saved && saved.adoptedId === revisionId;
  const source = reuse ? saved.source : adopted || {expected_output:"",tags:[],rationale:"",is_excluded:false};
  const node = $("#caseLabelingForm"), ordinary = {node,images:state.caseLabeling.pendingImages,dirty:state.caseLabeling.dirty,focus:document.activeElement?.id};
  closeAllReviewDropdowns();
  node.remove();
  const c = {key,data:structuredClone(reuse ? saved.data : data),adoptedId:revisionId,adopted,source,ordinary,
    images:reuse ? saved.images : [],retained:reuse ? saved.retained : (adopted?.attachments || []).map(a=>a.id),
    rationale:reuse ? saved.rationale : "",confirmed:false,excludedConfirmed:reuse ? saved.excludedConfirmed : false,
    pageContext:capturePageContext(),baselines:selectedBaselineQueryValue(),actor:state.session?.username || "",error:""};
  caseLabelDecisionUi.editor = c; state.caseLabeling.pendingImages = c.images; state.caseLabeling.dirty = true;
  $("#caseLabelDecisionDialog")?.close(); renderCaseLabelingEditor(data,{decision:c});
  $("#caseDecisionMode")?.focus();
}
function rememberCaseLabelDecisionDraft() {
  const c = caseLabelDecisionUi.editor;
  if (!c || !$("#caseLabelingForm")) return;
  c.source = caseLabelingFormPayload(); c.rationale = $("#caseDecisionReviewRationale")?.value || "";
  c.excludedConfirmed = Boolean($("#caseDecisionConfirmExclusion")?.checked);
  c.images = state.caseLabeling.pendingImages;
  caseLabelDecisionUi.drafts.set(c.key,{source:c.source,rationale:c.rationale,images:c.images,retained:c.retained,
    adoptedId:c.adoptedId,excludedConfirmed:c.excludedConfirmed,data:c.data});
}
function exitCaseDecisionEditor({discard = false} = {}) {
  const c = caseLabelDecisionUi.editor;
  if (!c || caseLabelDecisionUi.saving) return;
  if (discard) { c.images.forEach(i=>releasePreviewUrlLater(i.previewUrl)); caseLabelDecisionUi.drafts.delete(c.key); }
  else rememberCaseLabelDecisionDraft();
  caseLabelDecisionUi.editor = null;
  state.caseLabeling.pendingImages = c.ordinary.images; state.caseLabeling.dirty = c.ordinary.dirty;
  $("#caseLabelingEditor")?.replaceChildren(c.ordinary.node);
  refreshCaseLabelDecisionLanguage();
  syncCaseLabelingExpectedOutputFromTags(); updateTagSummary();
  $("#caseLabelGoAdjudication")?.focus();
}
function caseDecisionEditorHeader(c) {
  const source = c.adopted
    ? uiText(`采纳 ${c.adopted.author} · 版本 ${c.adopted.id}${c.adopted.historical ? "（旧版本）" : ""}`, `Adopting ${c.adopted.author} · revision ${c.adopted.id}${c.adopted.historical ? " (earlier revision)" : ""}`)
    : uiText("重新标注，确认完整 Issue 结果", "Relabel and confirm the complete Issue result");
  return `<section class="case-decision-mode" id="caseDecisionMode" tabindex="-1"><div class="review-section-heading"><h2>${uiText("裁决模式", "Decision mode")}</h2><div class="review-heading-actions"><button type="button" class="history-inline-button" id="caseDecisionExit">${uiText("退出裁决", "Exit decision mode")}</button></div></div><p class="quiet-meta">${escapeHtml(source)}</p>${c.adopted?.rationale ? `<details><summary>${uiText("查看原作者依据", "View original rationale")}</summary><p>${escapeHtml(c.adopted.rationale)}</p></details>` : ""}</section>`;
}

function caseDecisionEditorFields(c) {
  return `${c.source.evidence_gaps?.length ? `<p>${uiText("证据缺口", "Evidence gaps")}: ${escapeHtml(c.source.evidence_gaps.map(evidenceLabel).join(" · "))}</p>` : ""}<label class="review-reason case-decision-rationale"><span class="review-reason-heading">${uiText("裁决人补充依据（选填）", "Decision review rationale (optional)")}</span><textarea id="caseDecisionReviewRationale" rows="2" maxlength="8000">${escapeHtml(c.rationale)}</textarea></label><label class="case-decision-confirm"><input type="checkbox" id="caseDecisionConfirmExclusion" ${c.excludedConfirmed ? "checked" : ""} aria-required="true" aria-describedby="caseDecisionConfirmError"/><span>${uiText("已确认上方“是否排除”的选择", "I confirm the exclusion choice above")}</span></label><p class="case-label-decision-error" id="caseDecisionConfirmError" role="alert"></p><div class="case-decision-images" id="caseDecisionRetainedImages">${(c.adopted?.attachments || []).filter(a=>c.retained.includes(a.id)).map(a=>`<div>${caseDecisionImageMarkup([a])}<button type="button" class="button button-quiet" data-remove-decision-image="${escapeHtml(a.id)}">${uiText("移除引用", "Remove reference")}</button></div>`).join("")}</div><div class="case-decision-preview" id="caseDecisionPreview" aria-live="polite"></div><p class="case-label-decision-error" id="caseDecisionEditorError" role="alert">${escapeHtml(c.error ? caseExclusionErrorMessage({message:c.error}) : "")}</p>`;
}
function bindCaseDecisionEditor(c) {
  $("#caseDecisionExit").addEventListener("click",()=>exitCaseDecisionEditor());
  $("#caseDecisionEditorRefresh").addEventListener("click",()=>void refreshDecisionEditorSources());
  document.querySelectorAll("[data-remove-decision-image]").forEach(b=>b.addEventListener("click",()=>{c.retained=c.retained.filter(id=>id!==b.dataset.removeDecisionImage);b.parentElement.remove();rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();}));
  $("#caseLabelingExcluded").addEventListener("change",()=>{$("#caseDecisionConfirmExclusion").checked=false;});
  $("#caseLabelingForm").addEventListener("input",()=>{rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();});
  $("#caseLabelingForm").addEventListener("change",()=>{rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();});
  updateCaseDecisionPreview();
}
function updateCaseDecisionConfirmation() {
  const c=caseLabelDecisionUi.editor, checkbox=$("#caseDecisionConfirmExclusion"), error=$("#caseDecisionConfirmError");
  if(!c || !checkbox || !error)return;
  if(checkbox.checked)c.confirmationInvalid=false;
  checkbox.setAttribute("aria-invalid",String(Boolean(c.confirmationInvalid)));
  error.textContent=c.confirmationInvalid ? uiText("请确认上方“是否排除”的选择后再提交。","Confirm the exclusion choice above before submitting.") : "";
}
function updateCaseDecisionPreview() {
  updateCaseDecisionConfirmation();
  const c=caseLabelDecisionUi.editor, target=$("#caseDecisionPreview"); if(!c || !target)return;
  const p=caseLabelingFormPayload();
  const names={expected_output:uiText("分类","Classification"),tags:uiText("标签","Tags"),rationale:uiText("标注依据","Label rationale"),is_excluded:uiText("是否排除","Exclusion")};
  const changed=c.adopted ? Object.keys(names).filter(k=>JSON.stringify(p[k])!==JSON.stringify(c.adopted[k])).map(k=>names[k]) : [];
  target.textContent=uiText(`将确认：${expectedOutputDisplayText(p.expected_output) || "待补齐分类"} · ${caseExclusionText(p.is_excluded)}${changed.length ? `；已调整：${changed.join("、")}` : ""}`,`Confirm: ${expectedOutputDisplayText(p.expected_output) || "Classification missing"} · ${caseExclusionText(p.is_excluded)}${changed.length ? `; changed: ${changed.join(", ")}` : ""}`);
}
function refreshCaseLabelDecisionLanguage() {
  renderCaseLabelingStatusPicker();
  const data = state.caseLabeling.caseData, actions = $("#caseLabelResultActions");
  if(data && actions){actions.outerHTML=caseLabelFinalResultMarkup(data);bindCaseLabelResultActions(data);}
  if($("#caseLabelDecisionDialog")?.open){
    const body=$("#caseLabelDecisionDialog .case-label-decision-body");
    const scroll=body?.scrollTop || 0;
    const expanded=Array.from(body?.querySelectorAll("details") || [],item=>item.open);
    renderCaseLabelDecisionDialog();
    const next=$("#caseLabelDecisionDialog .case-label-decision-body");
    next?.querySelectorAll("details").forEach((item,index)=>{item.open=!!expanded[index];});
    if(next)next.scrollTop=scroll;
  }
  if(caseLabelDecisionUi.editor && !caseLabelDecisionUi.saving){
    const c=caseLabelDecisionUi.editor, focus=document.activeElement?.id, node=document.activeElement;
    const selection=node?.tagName === "TEXTAREA" ? [node.selectionStart,node.selectionEnd] : null;
    rememberCaseLabelDecisionDraft();renderCaseLabelingEditor(c.data,{decision:c});
    if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    if(selection)document.getElementById(focus)?.setSelectionRange(...selection);
  }
}
async function refreshUnifiedCaseDecisionSources() {
  const c=caseLabelDecisionUi.context;if(!c)return;
  try {
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
    if(!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId!==fresh.issue_id || c!==caseLabelDecisionUi.context)return;
    c.caseData=fresh;renderCaseLabelDecisionDialog();
  }catch(e){showToast(e.message,true);}
}
async function refreshDecisionEditorSources() {
  const c=caseLabelDecisionUi.editor;if(!c || caseLabelDecisionUi.saving)return;
  try{
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.data.issue_id)}`));
    if(c!==caseLabelDecisionUi.editor || !isPageContextCurrent(c.pageContext))return;
    // The new fingerprint becomes eligible only after explicit review in the dialog.
    openCaseLabelDecision(fresh, {compareEditor:c});
  }catch(e){if(c===caseLabelDecisionUi.editor){c.error=e.message;$("#caseDecisionEditorError").textContent=caseExclusionErrorMessage(e);}}
}
async function adjudicateIssueLabel(event) {
  event?.preventDefault();
  const c=caseLabelDecisionUi.editor;
  if(!c || caseLabelDecisionUi.saving || !hasDashboardWriteRole() || !isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId!==c.data.issue_id || selectedBaselineQueryValue()!==c.baselines || (c.actor && c.actor !== state.session?.username))return;
  rememberCaseLabelDecisionDraft();
  const p=caseLabelingFormPayload(), error=$("#caseDecisionEditorError");
  error.textContent="";
  if(!p.expected_output || caseLabelingOutputValidation().conflict){error.textContent=uiText("请补齐分类并解决标签冲突。","Complete the classification and resolve conflicting tags.");return;}
  if(!c.excludedConfirmed){c.confirmationInvalid=true;updateCaseDecisionConfirmation();$("#caseDecisionConfirmExclusion")?.focus();return;}
  if(c.images.length+c.retained.length>4){error.textContent=uiText("裁决截图最多 4 张。","Maximum 4 decision images.");return;}
  const payload={...p,full_result:true,label_rationale:p.rationale,rationale:c.rationale,adopted_revision_id:c.adoptedId,retained_attachment_ids:c.retained,
    expected_source_fingerprint:c.data.label_state?.source_fingerprint || "",expected_previous_decision_id:c.data.label_state?.decision?.id || null};
  const formNode=$("#caseLabelingForm");caseLabelDecisionUi.saving=true;
  formNode.querySelectorAll("button,input,textarea,select").forEach(n=>{n.dataset.decisionWasDisabled=String(n.disabled);n.disabled=true;});
  enhanceDashboardSelects(formNode);
  let committed=false;
  try{
    let body=JSON.stringify(payload),suffix="",headers={};
    if(c.images.length){body=new FormData();body.append("payload",JSON.stringify(payload));c.images.forEach(i=>body.append("attachments",i.file,i.file.name));suffix="-with-attachments";headers={"X-RA-Triage-Request":"labeling-v1"};}
    const saved=await api(`/api/labeling/issues/${encodeURIComponent(c.data.issue_id)}/decisions${suffix}`,{method:"POST",body,headers});
    committed=true;acknowledgeLocalChange(saved);caseLabelDecisionUi.drafts.delete(c.key);
    caseLabelDecisionUi.saving=false;
    if(caseLabelDecisionUi.editor===c)exitCaseDecisionEditor({discard:true});
    showToast(uiText("完整裁决已保存。","Complete decision saved."));
    await refreshCaseDecisionResult({caseData:c.data,pageContext:c.pageContext,baselines:c.baselines});
  }catch(e){if(!committed && caseLabelDecisionUi.editor===c){c.error=e.message;error.textContent=caseExclusionErrorMessage(e);}}
  finally{caseLabelDecisionUi.saving=false;formNode.querySelectorAll("[data-decision-was-disabled]").forEach(n=>{n.disabled=n.dataset.decisionWasDisabled==="true";delete n.dataset.decisionWasDisabled;});enhanceDashboardSelects(formNode);}
}
async function refreshCaseDecisionResult(c) {
  try{
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
    if(!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId!==c.caseData.issue_id || selectedBaselineQueryValue()!==c.baselines || (c.actor && c.actor !== state.session?.username))return;
    for(const key of ["label_cases","label_state","label_source_contexts","decision_history","exclusion_summary"])state.caseLabeling.caseData[key]=fresh[key];
    if (caseLabelDecisionUi.context?.caseData.issue_id === fresh.issue_id) caseLabelDecisionUi.context.caseData = fresh;
    refreshCaseLabelDecisionLanguage();
  }catch(_){showToast(uiText("裁决已保存，请刷新查看最新汇总。","Decision saved. Refresh to see the latest result."),true);}
}
