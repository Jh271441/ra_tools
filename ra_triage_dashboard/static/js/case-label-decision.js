/* A single Issue entry for results, source history and explicit decisions. */
const caseLabelDecisionUi = {context:null, drafts:new Map(), saving:false};
function caseLabelHasIssueDecision(data) { return Boolean(data?.label_state?.sources?.length || data?.label_state?.decision || data?.label_cases?.length); }
function caseDecisionSourceName(data, source, index = 0) {
  const context = data.label_source_contexts?.[source.label_case_id || source.id] || {};
  const linked = (context.combined_reviews || []).map(item => item.task_name).filter(Boolean);
  const task = (state.caseLabeling.tasks || []).find(item => item.id === source.task_id);
  return linked.length ? [...new Set(linked)].join(" · ") : source.task_name || context.task_name || task?.name
    || (source.task_id ? uiText(`标注任务 ${index + 1}`, `Labeling task ${index + 1}`) : uiText("Issue 标注", "Issue label"));
}
function caseDecisionStateText(value) {
  return ({resolved:uiText("已形成结论", "Resolved"), conflict:uiText("待裁决", "Needs decision"), stale:uiText("需重新裁决", "Recheck decision"), pending:uiText("待完成", "Pending")})[value] || uiText("待完成", "Pending");
}
function caseDecisionRecordMarkup(vote, sourceName, kind = "") {
  return `<article class="history-row"><div class="history-head">${vote.expected_output ? labelBadge(vote.expected_output, "—", expectedOutputDisplayText(vote.expected_output)) : `<span class="tag">${uiText("待补充分类", "Incomplete label")}</span>`}${kind ? `<span class="tag">${escapeHtml(kind)}</span>` : ""}${typeof vote.is_excluded === "boolean" ? `<span class="tag ${vote.is_excluded ? "exclusion-tag" : ""}">${escapeHtml(caseExclusionText(vote.is_excluded))}</span>` : ""}<span class="history-reviewer">${escapeHtml(vote.author || vote.created_by || uiText("未记录", "Unknown"))}</span><time class="history-time">${escapeHtml(formatTime(vote.created_at))}</time></div><small class="case-decision-source-name">${escapeHtml(sourceName)}</small>${vote.tags?.length ? `<div class="tags">${vote.tags.map(tag => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>` : ""}<p>${escapeHtml(vote.rationale || uiText("未填写依据", "No rationale recorded"))}</p></article>`;
}
function caseDecisionFlowMarkup(data) {
  const explanation = caseLabelExplanation(data), result = data.label_state || {};
  const votes = caseExclusionVotes(data), excluded = data.exclusion_summary?.is_excluded;
  const count = votes.filter(v => v.is_excluded).length;
  const exclusionReason = count ? uiText(`${count} 份有效意见要求排除，当前按排除生效。`, `${count} effective opinions request exclusion, so exclusion currently applies.`)
    : votes.length ? uiText("当前有效意见均不排除。", "All current effective opinions include this Issue.")
    : uiText("暂无 Case 排除意见；旧 Run 复核记录可用于兜底。", "No Case exclusion opinions; legacy Run reviews may provide the fallback.");
  const steps = [
    [uiText("个人意见", "Opinions"),uiText(`${votes.length} 份有效意见`, `${votes.length} effective opinions`)],
    [uiText("来源汇总", "Source results"),uiText(`${(result.sources || []).length} 个标注来源`, `${(result.sources || []).length} label sources`)],
    [uiText("当前结果", "Current result"), explanation.output ? expectedOutputDisplayText(explanation.output) : caseDecisionStateText(explanation.status)]
  ];
  return `<section class="case-decision-result"><ol class="case-decision-flow" aria-label="${uiText("当前结论形成过程", "How the current result is formed")}">${steps.map(([title,text]) => `<li><strong>${escapeHtml(title)}</strong><span>${escapeHtml(text)}</span></li>`).join("")}</ol><div class="case-decision-reasons"><p><strong>${uiText("分类", "Classification")}</strong>${escapeHtml(explanation.reason)}${explanation.status !== "resolved" ? `${uiText("；", "; ")}${escapeHtml(explanation.next)}` : ""}</p><p><strong>${uiText("排除", "Exclusion")}</strong>${escapeHtml(exclusionReason)}${caseExclusionNeedsDecision(data) ? ` ${uiText("排除意见有分歧，仍待裁决。", "Exclusion opinions disagree and need a decision.")}` : ""}</p><p class="quiet-meta">${uiText("本地", "Local")}: ${escapeHtml(caseExclusionText(typeof excluded === "boolean" ? excluded : votes.length ? count > 0 : null))} · Trail: ${escapeHtml(caseExclusionTrailText(data))}</p></div></section>`;
}
function caseLabelDecisionMarkup(data) {
  const result = data.label_state || {}, sources = result.sources || [];
  const rows = sources.map((source,index) => {
    const name = caseDecisionSourceName(data,source,index);
    const votes = source.revision_summaries || [];
    return `<section class="case-decision-source"><div class="case-decision-source-heading"><strong>${escapeHtml(name)}</strong><span class="case-decision-source-state" data-state="${escapeHtml(source.state || "pending")}">${escapeHtml(caseDecisionStateText(source.state))}</span></div>${votes.map(v => caseDecisionRecordMarkup(v,name,source.adjudication?.result_revision_id === v.id ? source.adjudication.stale ? uiText("原任务裁决 · 已失效", "Stale task decision") : uiText("任务裁决", "Task decision") : uiText("个人标注", "Personal label"))).join("") || `<p class="muted">${uiText("暂无有效提交", "No valid submissions")}</p>`}</section>`;
  }).join("");
  const history = [...(data.decision_history || [])];
  if (result.decision && !history.some(v => v.id === result.decision.id)) history.unshift(result.decision);
  return `${caseDecisionFlowMarkup(data)}<h3 class="case-decision-section-title">${uiText("标注意见与依据", "Label opinions and rationales")}</h3><div class="case-decision-records history-dialog-content">${rows || `<p class="muted">${uiText("尚无标注，先保存你的意见。", "No labels yet. Save your opinion first.")}</p>`}</div>${history.length ? `<section class="case-decision-history"><h3>${uiText("裁决记录", "Decision history")} · ${history.length}</h3><div class="case-decision-records history-dialog-content">${history.map(v => caseDecisionRecordMarkup(v,uiText("Issue 最终分类", "Final Issue classification"),v.id === result.decision?.id ? result.decision.stale ? uiText("已失效", "Stale") : uiText("当前裁决", "Current decision") : uiText("历史裁决", "Previous decision"))).join("")}</div></section>` : ""}`;
}
function rememberCaseLabelDecisionDraft() {
  const c = caseLabelDecisionUi.context;
  if (c?.mode && c.mode !== "issue") { rememberCaseExclusionDraft(); return; }
  if (!c || c.saved || !$("#caseLabelDecisionExpectedOutput")) return;
  caseLabelDecisionUi.drafts.set(c.key,{output:$("#caseLabelDecisionExpectedOutput").value,rationale:$("#caseLabelDecisionRationale").value});
  while (caseLabelDecisionUi.drafts.size > 16) caseLabelDecisionUi.drafts.delete(caseLabelDecisionUi.drafts.keys().next().value);
}
function renderCaseLabelDecisionDialog() {
  const c = caseLabelDecisionUi.context;
  if (!c) return;
  const data = c.caseData, result = data.label_state || {}, tasks = caseTaskDecisionCandidates(data);
  const draft = caseLabelDecisionUi.drafts.get(c.key) || {output:result.decision?.expected_output || result.expected_output || "",rationale:result.decision?.rationale || ""};
  const blocked = (result.sources || []).some(s => s.task_id && s.state !== "resolved");
  const taskMode = c.mode !== "issue";
  const dialog = $("#caseLabelDecisionDialog");
  const options = [{value:"issue",label:uiText("Issue 最终分类", "Final Issue classification")},...tasks.map((t,i) => ({value:t.id,label:caseDecisionSourceName(data,t,i)}))];
  const editor = taskMode ? caseExclusionEditorMarkup() : `${blocked ? `<p class="case-label-decision-blocked">${tasks.length ? uiText("先在此窗口选择未完成的任务，处理其标签与排除意见，再保存 Issue 最终分类。", "Choose an unresolved task here and decide its label and exclusion before saving the final Issue classification.") : uiText("任务尚未完成，请先补齐任务提交；此处可查看原始意见。", "Task submissions are incomplete. Complete them first; original opinions remain visible here.")}</p>` : ""}<p class="quiet-meta">${uiText("本项只决定最终分类；排除意见按各来源分别汇总。", "This decides the final classification. Exclusion is aggregated separately from each source.")}</p><label><span id="caseLabelDecisionOutputLabel">${uiText("最终期望输出", "Final expected output")}</span><select id="caseLabelDecisionExpectedOutput" aria-labelledby="caseLabelDecisionOutputLabel">${EXPECTED_OUTPUT_OPTIONS.map(o => `<option value="${escapeHtml(o.value)}" ${o.value === draft.output ? "selected" : ""}>${escapeHtml(i18nLocale() === "en" ? o.labelEn : o.labelZh)}</option>`).join("")}</select></label><label>${uiText("裁决依据", "Decision rationale")}<textarea id="caseLabelDecisionRationale" rows="3" maxlength="8000">${escapeHtml(draft.rationale)}</textarea></label>`;
  dialog.innerHTML = `<form class="dialog-card" id="caseLabelDecisionForm"><div class="dialog-heading"><div><h2 id="caseLabelDecisionTitle">${uiText("Issue 裁决", "Issue decision")}</h2><small>${escapeHtml(data.issue_id)}</small></div><div class="case-decision-heading-actions"><button type="button" class="icon-button" id="caseDecisionInfo" aria-label="${uiText("查看裁决规则与流程图", "Decision rules and flowchart")}" title="${uiText("裁决规则", "Decision rules")}">ⓘ</button><button type="button" class="icon-button" data-close-decision aria-label="${uiText("关闭", "Close")}">×</button></div></div><div class="case-label-decision-body"><div id="caseDecisionEvidence">${caseLabelDecisionMarkup(data)}</div><details class="case-decision-editor" ${c.editing ? "open" : ""}><summary>${uiText("调整裁决", "Make a decision")}</summary><label>${uiText("裁决范围", "Decision scope")}<select id="caseLabelDecisionScope">${options.map(o => `<option value="${escapeHtml(o.value)}" ${o.value === c.mode ? "selected" : ""}>${escapeHtml(o.label)}</option>`).join("")}</select></label>${editor}<p class="case-label-decision-error" role="alert" ${c.error ? "" : "hidden"}>${escapeHtml(c.error || "")}</p></details></div><div class="dialog-actions"><button type="button" class="button button-quiet" id="caseDecisionRefresh">${uiText("刷新来源", "Refresh sources")}</button><button type="button" class="button button-quiet" data-close-decision>${uiText("关闭", "Close")}</button><button class="button button-primary" id="caseLabelDecisionSubmit" type="submit" ${c.editing ? "" : "hidden"}>${uiText("保存裁决", "Save decision")}</button></div></form>`;
  dialog.querySelectorAll("[data-close-decision]").forEach(b => b.addEventListener("click", () => dialog.close()));
  $("#caseDecisionInfo").addEventListener("click", showCaseDecisionInfo);
  $("#caseDecisionRefresh").addEventListener("click", () => void refreshUnifiedCaseDecisionSources());
  dialog.querySelector(".case-decision-editor").addEventListener("toggle", e => { c.editing = e.currentTarget.open; $("#caseLabelDecisionSubmit").hidden = !c.editing; });
  $("#caseLabelDecisionScope").addEventListener("change", e => {
    rememberCaseLabelDecisionDraft(); c.mode = e.target.value; c.error = "";
    if (c.mode !== "issue") prepareCaseTaskDecision(data,c.mode,c.pageContext,c.baselines);
    renderCaseLabelDecisionDialog(); $("#caseLabelDecisionScope")?.closest(".ui-select")?.querySelector("button")?.focus();
  });
  $("#caseLabelDecisionForm").addEventListener("input", rememberCaseLabelDecisionDraft);
  $("#caseLabelDecisionForm").addEventListener("change", rememberCaseLabelDecisionDraft);
  $("#caseLabelDecisionForm").addEventListener("submit", e => { e.preventDefault(); if (c.mode === "issue") void adjudicateIssueLabel(); else void saveCaseExclusionDecision(); });
  bindCaseTaskDecisionEditor(); syncCaseLabelDecisionSaving();
}
function openCaseLabelDecision(data) {
  if (caseLabelDecisionUi.saving || caseExclusionUi.saving) return;
  let dialog = $("#caseLabelDecisionDialog");
  if (!dialog) {
    dialog = document.createElement("dialog"); dialog.id = "caseLabelDecisionDialog";
    dialog.className = "dialog case-label-decision-dialog history-dialog"; dialog.setAttribute("aria-labelledby","caseLabelDecisionTitle");
    dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener("close", () => { rememberCaseLabelDecisionDraft(); if (state.activePage === "labeling" && state.caseLabeling.issueId === caseLabelDecisionUi.context?.caseData.issue_id) $("#caseLabelGoAdjudication")?.focus(); });
    document.body.appendChild(dialog);
  }
  const result = data.label_state || {}, key = JSON.stringify([data.issue_id,selectedBaselineQueryValue(),result.source_fingerprint || "",result.decision?.id || null]);
  const prior = caseLabelDecisionUi.context;
  const mode = prior?.key === key ? prior.mode : "issue";
  caseLabelDecisionUi.context = {caseData:JSON.parse(JSON.stringify(data)),key,mode,editing:false,baselines:selectedBaselineQueryValue(),pageContext:capturePageContext(),error:""};
  if (mode !== "issue") prepareCaseTaskDecision(caseLabelDecisionUi.context.caseData,mode,caseLabelDecisionUi.context.pageContext,caseLabelDecisionUi.context.baselines);
  renderCaseLabelDecisionDialog(); dialog.showModal();
}
function bindCaseLabelResultActions(data) {
  $("#caseLabelGoAdjudication")?.addEventListener("click", () => openCaseLabelDecision(data));
}
function refreshCaseLabelDecisionLanguage() {
  const data = state.caseLabeling.caseData;
  const button = $("#caseLabelGoAdjudication");
  if (data && button) { button.outerHTML = caseLabelFinalResultMarkup(data); bindCaseLabelResultActions(data); }
  if (!$("#caseLabelDecisionDialog")?.open) return;
  const focus = document.activeElement?.id, node = focus && document.getElementById(focus);
  const selection = node?.tagName === "TEXTAREA" ? [node.selectionStart,node.selectionEnd] : null;
  const scroll = $("#caseLabelDecisionDialog .case-label-decision-body")?.scrollTop;
  rememberCaseLabelDecisionDraft(); renderCaseLabelDecisionDialog(); document.getElementById(focus)?.focus({preventScroll:true});
  if (selection) document.getElementById(focus)?.setSelectionRange(...selection);
  $("#caseLabelDecisionDialog .case-label-decision-body").scrollTop = scroll || 0;
}
function syncCaseLabelDecisionSaving() {
  const busy = caseLabelDecisionUi.saving || caseExclusionUi.saving, dialog = $("#caseLabelDecisionDialog");
  const c = caseLabelDecisionUi.context;
  const selects = dialog?.querySelectorAll?.("select") || [$("#caseLabelDecisionExpectedOutput")].filter(Boolean);
  selects.forEach(node => { node.disabled = busy; enhanceNativeUiSelect(node); });
  dialog?.querySelectorAll?.("textarea,input,#caseDecisionRefresh").forEach(node => {node.disabled = busy;});
  const button = $("#caseLabelDecisionSubmit");
  if (button) {
    button.disabled = busy || !hasDashboardWriteRole() || ((c?.mode || "issue") === "issue" && (!c?.caseData.label_state?.sources?.length || c.caseData.label_state.sources.some(s => s.task_id && s.state !== "resolved")));
    button.textContent = busy ? uiText("保存中…", "Saving…") : uiText("保存裁决", "Save decision");
    if (busy) button.setAttribute("aria-busy","true"); else button.removeAttribute("aria-busy");
  }
}
function showCaseDecisionError(context, error) {
  context.error = caseExclusionErrorMessage(error);
  const c = caseLabelDecisionUi.context;
  if (c && c !== context) c.error = context.error;
  const target = $("#caseLabelDecisionDialog .case-label-decision-error");
  if (target) { target.textContent = context.error; target.hidden = false; }
  if (!$("#caseLabelDecisionDialog")?.open) showToast(context.error,true);
}
async function refreshCaseDecisionResult(c) {
  try {
    const fresh = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
    if (!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId !== c.caseData.issue_id || selectedBaselineQueryValue() !== c.baselines) return;
    const data = state.caseLabeling.caseData;
    for (const key of ["label_cases","label_state","label_source_contexts","decision_history","exclusion_summary"]) if (fresh[key] !== undefined) data[key] = fresh[key];
    refreshCaseLabelDecisionLanguage();
  } catch (_) { showToast(uiText("裁决已保存，请刷新查看最新汇总。", "Decision saved. Refresh to view the latest result."),true); }
}
async function refreshUnifiedCaseDecisionSources() {
  const c = caseLabelDecisionUi.context;
  if (!c || caseLabelDecisionUi.saving || caseExclusionUi.saving) return;
  rememberCaseLabelDecisionDraft(); caseLabelDecisionUi.saving = true; syncCaseLabelDecisionSaving();
  try {
    const fresh = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`));
    if (!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId !== c.caseData.issue_id || c.baselines !== selectedBaselineQueryValue()) return;
    const draft = caseLabelDecisionUi.drafts.get(c.key);
    c.caseData = fresh; c.key = JSON.stringify([fresh.issue_id,c.baselines,fresh.label_state?.source_fingerprint || "",fresh.label_state?.decision?.id || null]);
    if (draft) caseLabelDecisionUi.drafts.set(c.key,draft);
    if (c.mode !== "issue") {
      const rationale = caseExclusionUi.context?.draft.rationale || "";
      if (!caseTaskDecisionCandidates(fresh).some(t => t.id === c.mode)) c.mode = "issue";
      else { prepareCaseTaskDecision(fresh,c.mode,c.pageContext,c.baselines); Object.assign(caseExclusionUi.context.draft,{referenceId:"",choice:"",confirmed:false,rationale}); }
    }
    c.error = ""; renderCaseLabelDecisionDialog();
  } catch (error) { showCaseDecisionError(c,error); }
  finally { caseLabelDecisionUi.saving = false; syncCaseLabelDecisionSaving(); }
}
async function adjudicateIssueLabel() {
  const c = caseLabelDecisionUi.context;
  if (!c || caseLabelDecisionUi.saving || caseExclusionUi.saving || !hasDashboardWriteRole()) return;
  const caseData = c.caseData, result = caseData.label_state || {};
  if (!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId !== caseData.issue_id || selectedBaselineQueryValue() !== c.baselines) return;
  if ((result.sources || []).some(s => s.task_id && s.state !== "resolved")) return;
  const output = String($("#caseLabelDecisionExpectedOutput")?.value || ""), rationale = String($("#caseLabelDecisionRationale")?.value || "").trim();
  if (!EXPECTED_OUTPUT_OPTIONS.some(o => o.value && o.value === output) || !rationale) { showToast(uiText("请选择最终期望输出并填写裁决依据。", "Select a final output and enter a rationale."),true); return; }
  rememberCaseLabelDecisionDraft(); caseLabelDecisionUi.saving = true; syncCaseLabelDecisionSaving();
  try {
    const saved = await api(`/api/labeling/issues/${encodeURIComponent(caseData.issue_id)}/decisions`,{method:"POST",body:JSON.stringify({expected_output:output,rationale,expected_source_fingerprint:result.source_fingerprint || "",expected_previous_decision_id:result.decision?.id || null})});
    acknowledgeLocalChange(saved); c.saved = true; caseLabelDecisionUi.drafts.delete(c.key); $("#caseLabelDecisionDialog")?.close();
    showToast(uiText("Issue 级裁决已保存。", "Issue decision saved.")); await refreshCaseDecisionResult(c);
  } catch (error) { showCaseDecisionError(c,error); }
  finally { caseLabelDecisionUi.saving = false; syncCaseLabelDecisionSaving(); }
}
