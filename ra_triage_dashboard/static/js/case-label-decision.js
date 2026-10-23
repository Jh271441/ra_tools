/* Issue decisions are separate from ordinary labeling drafts and task decisions. */
const caseLabelDecisionUi = { context: null, drafts: new Map(), saving: false };

function caseLabelHasIssueDecision(caseData) {
  const result = caseData?.label_state || {};
  return Boolean(result.decision || (result.sources || []).length > 1 || ["conflict", "stale"].includes(result.state));
}

function caseLabelDecisionMarkup(caseData) {
  const result = caseData.label_state || {};
  const decision = result.decision;
  const sources = result.sources || [];
  const status = decision ? decision.stale ? uiText("已有裁决需重新确认", "Previous decision is stale") : uiText("已有有效裁决", "Current decision is valid") : uiText("待裁决", "Awaiting decision");
  const rows = sources.map((source, index) => {
    const task = (state.caseLabeling.tasks || []).find(item => item.id === source.task_id);
    const name = source.task_id ? task?.name || (caseData.label_cases || []).find(item => item.task_id === source.task_id)?.task_name || uiText(`任务来源 ${index + 1}`, `Task source ${index + 1}`) : uiText("任务外标注", "Independent label");
    const status = ({resolved: uiText("已形成结论", "Resolved"), conflict: uiText("来源冲突", "Conflicting votes"), stale: uiText("需重新确认", "Needs confirmation"), pending: uiText("待完成", "Pending")})[source.state] || uiText("待完成", "Pending");
    const votes = (source.revision_summaries || []).map(vote => `<div class="case-decision-vote"><div><strong>${escapeHtml(vote.author || uiText("未记录", "Unknown"))}</strong><span class="case-decision-output">${escapeHtml(expectedOutputDisplayText(vote.expected_output) || uiText("待补充", "Incomplete"))}</span></div>${vote.created_at ? `<time>${escapeHtml(formatTime(vote.created_at))}</time>` : ""}${vote.rationale ? `<p>${escapeHtml(vote.rationale)}</p>` : ""}</div>`).join("");
    const href = source.task_id && source.state !== "resolved" ? pageUrl("labeling", {issue:caseData.issue_id, taskId:source.task_id, search:"", issueIds:[], status:[], author:[], assignee:[], gt:[], label:[], exclusion:[], commentState:[], cluster:"", baselines:selectedBaselineQueryValue(), forceBaselines:true}) : "";
    return `<li><div class="case-decision-source-heading"><strong>${escapeHtml(name)}</strong><span class="case-decision-source-state" data-state="${escapeHtml(source.state || "pending")}">${escapeHtml(status)}</span></div>${votes || `<small>${uiText("暂无有效提交", "No valid submissions")}</small>`}${href ? `<a class="text-link" href="${escapeHtml(href)}" data-decision-task-link>${uiText("进入任务处理", "Open task")}</a>` : ""}</li>`;
  }).join("");
  const history = [...(caseData.decision_history || [])];
  if (decision && !history.some(item => item.id === decision.id)) history.unshift(decision);
  const historyMarkup = history.length ? `<section class="case-decision-history"><h3>${uiText("裁决记录", "Decision history")}<span>${history.length}</span></h3><ol>${history.map(item => `<li><div><strong>${escapeHtml(expectedOutputDisplayText(item.expected_output))}</strong>${item.id === decision?.id ? `<span class="case-decision-source-state" data-state="${decision.stale ? "stale" : "resolved"}">${decision.stale ? uiText("需重新确认", "Needs confirmation") : uiText("当前裁决", "Current decision")}</span>` : ""}</div><small>${escapeHtml(item.created_by || uiText("未记录", "Unknown"))} · ${escapeHtml(formatTime(item.created_at))}</small><p>${escapeHtml(item.rationale || uiText("未填写依据", "No rationale recorded"))}</p></li>`).join("")}</ol></section>` : "";
  return `<section class="case-label-decision"><div class="case-label-decision-heading"><strong>${escapeHtml(status)}</strong><small>${escapeHtml(uiText(`${sources.length} 个来源`, `${sources.length} sources`))}</small></div><h3 class="case-decision-section-title">${uiText("来源与原始意见", "Sources and original votes")}</h3><ul class="case-label-decision-sources">${rows}</ul>${historyMarkup}</section>`;
}

function rememberCaseLabelDecisionDraft() {
  const context = caseLabelDecisionUi.context;
  if (!context || context.saved || !$("#caseLabelDecisionExpectedOutput")) return;
  caseLabelDecisionUi.drafts.set(context.key, {
    output: $("#caseLabelDecisionExpectedOutput").value,
    rationale: $("#caseLabelDecisionRationale").value,
  });
  while (caseLabelDecisionUi.drafts.size > 16) caseLabelDecisionUi.drafts.delete(caseLabelDecisionUi.drafts.keys().next().value);
}

function renderCaseLabelDecisionDialog() {
  const context = caseLabelDecisionUi.context;
  if (!context) return;
  const { caseData, key } = context;
  const result = caseData.label_state || {};
  const draft = caseLabelDecisionUi.drafts.get(key) || {output:result.decision?.expected_output || result.expected_output || "", rationale:result.decision?.rationale || ""};
  const blocked = (result.sources || []).some(source => source.task_id && source.state !== "resolved");
  const dialog = $("#caseLabelDecisionDialog");
  dialog.innerHTML = `<form class="dialog-card" id="caseLabelDecisionForm"><div class="dialog-heading"><div><small>${escapeHtml(caseData.issue_id)}</small><h2 id="caseLabelDecisionTitle">${uiText("Issue 裁决", "Issue adjudication")}</h2></div><button type="button" class="icon-button" data-close-decision aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body">${caseLabelDecisionMarkup(caseData)}${blocked ? `<p class="case-label-decision-blocked">${uiText("先处理未完成的任务来源，再保存最终裁决。", "Resolve pending task sources before saving the final decision.")}</p>` : ""}<h3 class="case-decision-section-title case-decision-edit-title">${uiText("本次裁决", "Your decision")}</h3><label class="case-label-decision-output"><span id="caseLabelDecisionOutputLabel">${uiText("最终期望输出", "Final expected output")}</span><select id="caseLabelDecisionExpectedOutput" aria-labelledby="caseLabelDecisionOutputLabel">${EXPECTED_OUTPUT_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}" ${item.value === draft.output ? "selected" : ""}>${escapeHtml(i18nLocale() === "en" ? item.labelEn : item.labelZh)}</option>`).join("")}</select></label><label><span>${uiText("裁决依据", "Decision rationale")}</span><textarea id="caseLabelDecisionRationale" rows="3" placeholder="${uiText("说明最终结论的依据", "Explain the final decision")}">${escapeHtml(draft.rationale)}</textarea></label><p class="case-label-decision-error" role="alert" ${context.error ? "" : "hidden"}>${escapeHtml(context.error || "")}</p></div><div class="dialog-actions"><button class="button button-quiet" type="button" data-close-decision>${uiText("取消", "Cancel")}</button><button class="button button-primary" id="caseLabelDecisionSubmit" type="submit" ${blocked || !hasDashboardWriteRole() || caseLabelDecisionUi.saving ? "disabled" : ""}>${caseLabelDecisionUi.saving ? uiText("保存中…", "Saving…") : uiText("保存裁决", "Save decision")}</button></div></form>`;
  syncCaseLabelDecisionSaving();
  dialog.querySelectorAll("[data-close-decision], [data-decision-task-link]").forEach(button => button.addEventListener("click", () => dialog.close()));
  $("#caseLabelDecisionForm").addEventListener("input", rememberCaseLabelDecisionDraft);
  $("#caseLabelDecisionForm").addEventListener("change", rememberCaseLabelDecisionDraft);
  $("#caseLabelDecisionForm").addEventListener("submit", event => { event.preventDefault(); void adjudicateIssueLabel(); });
}

function openCaseLabelDecision(caseData) {
  if (!caseLabelHasIssueDecision(caseData)) return;
  if (caseLabelDecisionUi.saving) return;
  let dialog = $("#caseLabelDecisionDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "caseLabelDecisionDialog";
    dialog.className = "dialog case-label-decision-dialog";
    dialog.setAttribute("aria-labelledby", "caseLabelDecisionTitle");
    dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener("close", () => {
      rememberCaseLabelDecisionDraft();
      if (state.activePage === "labeling" && state.caseLabeling.issueId === caseLabelDecisionUi.context?.caseData.issue_id) $("#caseLabelGoAdjudication")?.focus();
    });
    document.body.appendChild(dialog);
  }
  const result = caseData.label_state || {};
  caseLabelDecisionUi.context = {caseData, key:JSON.stringify([caseData.issue_id, result.source_fingerprint || "", result.decision?.id || null]), baselines:selectedBaselineQueryValue(), pageContext:capturePageContext(), error:""};
  renderCaseLabelDecisionDialog();
  dialog.showModal();
}

function bindCaseLabelResultActions(caseData) {
  $("#caseLabelWhy")?.addEventListener("click", () => showCaseLabelExplanation(caseData));
  $("#caseLabelGoAdjudication")?.addEventListener("click", () => {
    if (caseLabelHasIssueDecision(caseData)) openCaseLabelDecision(caseData);
    else $("#caseTaskAdjudicationPanel")?.scrollIntoView({behavior:"smooth", block:"start"});
  });
}

function refreshCaseLabelDecisionLanguage() {
  const summary = $("#caseLabelingEditor .case-label-final-result");
  if (summary && state.caseLabeling.caseData) {
    summary.outerHTML = caseLabelFinalResultMarkup(state.caseLabeling.caseData);
    bindCaseLabelResultActions(state.caseLabeling.caseData);
  }
  const dialog = $("#caseLabelDecisionDialog");
  if (!dialog?.open) return;
  const focus = document.activeElement?.id;
  const start = $("#caseLabelDecisionRationale")?.selectionStart;
  const end = $("#caseLabelDecisionRationale")?.selectionEnd;
  rememberCaseLabelDecisionDraft();
  renderCaseLabelDecisionDialog();
  if (focus) document.getElementById(focus)?.focus();
  if (focus === "caseLabelDecisionRationale") $("#caseLabelDecisionRationale")?.setSelectionRange(start, end);
}

function syncCaseLabelDecisionSaving() {
  const busy = caseLabelDecisionUi.saving;
  const select = $("#caseLabelDecisionExpectedOutput");
  const rationale = $("#caseLabelDecisionRationale");
  const button = $("#caseLabelDecisionSubmit");
  if (select) { select.disabled = busy; enhanceNativeUiSelect(select); }
  if (rationale) rationale.disabled = busy;
  if (button) {
    const sources = caseLabelDecisionUi.context?.caseData.label_state?.sources || [];
    button.disabled = busy || !hasDashboardWriteRole() || sources.some(source => source.task_id && source.state !== "resolved");
    button.textContent = busy ? uiText("保存中…", "Saving…") : uiText("保存裁决", "Save decision");
    if (busy) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
  }
}

async function adjudicateIssueLabel() {
  const context = caseLabelDecisionUi.context;
  if (!context || caseLabelDecisionUi.saving || !hasDashboardWriteRole()) return;
  const {caseData} = context;
  const labelState = caseData.label_state || {};
  const decision = labelState.decision || null;
  if (!isPageContextCurrent(context.pageContext) || state.caseLabeling.issueId !== caseData.issue_id || selectedBaselineQueryValue() !== context.baselines) return;
  if ((labelState.sources || []).some(source => source.task_id && source.state !== "resolved")) return;
  const expectedOutput = String($("#caseLabelDecisionExpectedOutput")?.value || "");
  const rationale = String($("#caseLabelDecisionRationale")?.value || "").trim();
  if (!EXPECTED_OUTPUT_OPTIONS.some(item => item.value && item.value === expectedOutput) || !rationale) {
    showToast(uiText("请选择最终期望输出并填写裁决依据。", "Select a final output and enter a rationale."), true);
    return;
  }
  rememberCaseLabelDecisionDraft();
  caseLabelDecisionUi.saving = true;
  syncCaseLabelDecisionSaving();
  try {
    const result = await api(`/api/labeling/issues/${encodeURIComponent(caseData.issue_id)}/decisions`, {method:"POST", body:JSON.stringify({expected_output:expectedOutput, rationale, expected_source_fingerprint:labelState.source_fingerprint || "", expected_previous_decision_id:decision?.id || null})});
    acknowledgeLocalChange(result);
    context.saved = true;
    $("#caseLabelDecisionDialog")?.close();
    caseLabelDecisionUi.drafts.delete(context.key);
    showToast(uiText("Issue 级裁决已保存。", "Issue decision saved."));
    // Refresh only the result, preserving the independent labeling form/images.
    try {
      const fresh = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(caseData.issue_id)}`));
      if (isPageContextCurrent(context.pageContext) && state.caseLabeling.issueId === caseData.issue_id) {
        state.caseLabeling.caseData.label_state = fresh.label_state;
        const restoreFocus = document.activeElement === $("#caseLabelGoAdjudication");
        const summary = $("#caseLabelingEditor .case-label-final-result");
        if (summary) summary.outerHTML = caseLabelFinalResultMarkup(state.caseLabeling.caseData);
        bindCaseLabelResultActions(state.caseLabeling.caseData);
        if (restoreFocus) $("#caseLabelGoAdjudication")?.focus();
      }
    } catch (_) { showToast(uiText("裁决已保存，汇总刷新失败，请刷新页面查看。", "Decision saved; summary refresh failed. Refresh to view it."), true); }
  } catch (error) {
    context.error = error.message;
    const target = $("#caseLabelDecisionDialog .case-label-decision-error");
    if (target) { target.textContent = error.message; target.hidden = false; }
    if (!$("#caseLabelDecisionDialog")?.open) showToast(error.message, true);
  } finally {
    caseLabelDecisionUi.saving = false;
    syncCaseLabelDecisionSaving();
  }
}
