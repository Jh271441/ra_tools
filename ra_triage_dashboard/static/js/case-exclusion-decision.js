/* Shared Case exclusion control and task editor inside the single Issue dialog. */
const caseExclusionUi = { context: null, drafts: new Map(), saving: false };
function expectedOutputDisplayText(value) {
  const option = EXPECTED_OUTPUT_OPTIONS.find(item => item.value === value);
  return option ? (i18nLocale() === "en" ? option.labelEn : option.labelZh) : value;
}
function caseExclusionToggleMarkup(id, checked, disabled = false) {
  return `<label class="review-exclude-toggle" title="${escapeHtml(uiText("按 K 切换；随 Case 标签保存", "Press K to toggle; saved with the Case label"))}"><input id="${id}" type="checkbox" aria-keyshortcuts="K" ${id === "reviewExcludeInput" ? 'data-case-exclusion="true"' : ""} ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}/><span><strong class="ui-lang-zh">排除此 Issue</strong><strong class="ui-lang-en">Exclude this Issue</strong><small class="ui-lang-zh">随 Case 标签保存；同步到 Trail 需单独确认</small><small class="ui-lang-en">Saved with the Case label; Trail sync needs separate confirmation</small></span><kbd class="review-control-shortcut review-exclude-shortcut" aria-hidden="true">K</kbd></label>`;
}
function caseExclusionVotes(data) {
  return (data.label_cases || []).flatMap(item => {
    const resolution = item.resolution || {};
    const decided = resolution.state === "resolved" && resolution.method === "adjudication";
    return (decided ? [resolution.result_revision || {}] : resolution.heads || []).filter(v => v.id)
      .map(v => ({...v, caseId:item.id, adjudicated:decided}));
  });
}
function caseExclusionNeedsDecision(data) {
  return new Set(caseExclusionVotes(data).map(v => Boolean(v.is_excluded))).size > 1;
}
function caseExclusionText(value) {
  return value === true ? uiText("排除", "Excluded") : value === false ? uiText("不排除", "Included") : uiText("暂无意见", "No opinion");
}
function caseExclusionTrailText(data) {
  if (data.trail_metadata_status === "pending") return uiText("查询中", "Checking");
  if (data.trail_metadata_status !== "ready") return uiText("无法确认", "Unconfirmed");
  return typeof data.dashboard_should_exclude === "boolean" ? caseExclusionText(data.dashboard_should_exclude) : uiText("未设置", "Unset");
}
function caseTaskDecisionCandidates(data) {
  return (data.label_cases || []).filter(c => c.can_adjudicate || c.can_adjudicate_exclusion);
}
function caseExclusionReference(task, id) {
  const r = task?.resolution || {};
  const rows = [...(r.heads || []), ...(r.method === "adjudication" && r.result_revision ? [r.result_revision] : [])];
  return {rows, selected:rows.find(v => String(v.id) === String(id)) || null};
}
function prepareCaseTaskDecision(data, caseId, pageContext, baselines) {
  const task = caseTaskDecisionCandidates(data).find(c => c.id === caseId);
  if (!task) { caseExclusionUi.context = null; return; }
  const key = JSON.stringify([data.issue_id, baselines, task.id, (task.resolution.heads || []).map(v => v.id), task.resolution.adjudication?.id]);
  caseExclusionUi.context = {caseData:data, key, pageContext, baselines, error:"", draft:caseExclusionUi.drafts.get(key) || {caseId:task.id, referenceId:"", choice:"", rationale:"", confirmed:false}};
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
function caseExclusionEditorMarkup() {
  const c = caseExclusionUi.context;
  if (!c) return "";
  const d = c.draft, task = caseTaskDecisionCandidates(c.caseData).find(t => t.id === d.caseId);
  const refs = caseExclusionReference(task, d.referenceId), ref = refs.selected;
  const option = (value, text, current) => `<option value="${escapeHtml(String(value))}" ${String(value) === String(current) ? "selected" : ""}>${escapeHtml(text)}</option>`;
  return `<input type="hidden" id="caseExclusionTask" value="${escapeHtml(d.caseId)}"/>
    <p class="quiet-meta">${uiText("此操作确认所选任务的标签与排除意见，其他来源仍独立参与汇总。", "This confirms the selected task's label and exclusion. Other sources still contribute independently.")}</p>
    <label>${uiText("参考标注意见", "Label opinion to adopt")}<select id="caseExclusionReference">${option("",uiText("请选择一份完整标注", "Choose a complete label"),d.referenceId)}${refs.rows.filter(v => EXPECTED_OUTPUT_OPTIONS.some(o => o.value && o.value === v.expected_output)).map(v => option(v.id,`${v.author} · ${expectedOutputDisplayText(v.expected_output)} · ${formatTime(v.created_at)}`,d.referenceId)).join("")}</select></label>
    ${ref ? `<article class="history-row case-task-preview"><div class="history-head">${labelBadge(ref.expected_output, "—", expectedOutputDisplayText(ref.expected_output))}<span>${uiText("本次采用", "Adopting")}</span></div><div class="tags">${(ref.tags || []).map(tag => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>${ref.evidence_gaps?.length ? `<p>${uiText("证据缺口", "Evidence gaps")}: ${escapeHtml(ref.evidence_gaps.map(evidenceLabel).join(" · "))}</p>` : ""}<p>${escapeHtml(ref.rationale || uiText("未填写依据", "No rationale recorded"))}</p></article>` : ""}
    <label>${uiText("是否排除", "Exclusion")}<select id="caseExclusionChoice">${option("",uiText("请选择", "Choose"),d.choice)}${option("false",uiText("不排除", "Include"),d.choice)}${option("true",uiText("排除", "Exclude"),d.choice)}</select></label>
    <label>${uiText("裁决依据", "Decision rationale")}<textarea id="caseExclusionRationale" rows="3" maxlength="8000">${escapeHtml(d.rationale)}</textarea></label>
    <label class="case-exclusion-confirm"><input type="checkbox" id="caseExclusionConfirm" ${d.confirmed ? "checked" : ""}/><span>${uiText("确认采用以上标签、证据和排除意见", "Confirm the label, evidence and exclusion above")}</span></label>`;
}
function bindCaseTaskDecisionEditor() {
  for (const id of ["caseExclusionReference", "caseExclusionChoice"]) $("#"+id)?.addEventListener("change", () => {
    rememberCaseExclusionDraft(); caseExclusionUi.context.draft.confirmed = false;
    renderCaseLabelDecisionDialog();
    document.getElementById(id)?.closest(".ui-select")?.querySelector("button")?.focus();
  });
}
function refreshCaseExclusionSummary() {
  const c = caseLabelDecisionUi.context, data = state.caseLabeling.caseData;
  if (!c || !data || !$("#caseLabelDecisionDialog")?.open) return;
  if (!isPageContextCurrent(c.pageContext) || c.caseData.issue_id !== data.issue_id || c.baselines !== selectedBaselineQueryValue()) { $("#caseLabelDecisionDialog").close(); return; }
  // Deferred Trail metadata can update facts without replacing the editor or draft.
  Object.assign(c.caseData, {trail_metadata_status:data.trail_metadata_status, dashboard_should_exclude:data.dashboard_should_exclude});
  const evidence = $("#caseDecisionEvidence");
  if (evidence) evidence.innerHTML = caseLabelDecisionMarkup(c.caseData);
}
function refreshCaseExclusionLanguage() {
  if ($("#caseDecisionInfoDialog")?.open) showCaseDecisionInfo();
}
function syncCaseExclusionSaving() { syncCaseLabelDecisionSaving(); }
async function refreshCaseExclusionSources() { return refreshUnifiedCaseDecisionSources(); }
async function saveCaseExclusionDecision() {
  const c = caseExclusionUi.context;
  if (!c || caseExclusionUi.saving || caseLabelDecisionUi.saving || !hasDashboardWriteRole()) return;
  if (!isPageContextCurrent(c.pageContext) || state.caseLabeling.issueId !== c.caseData.issue_id || selectedBaselineQueryValue() !== c.baselines) return;
  rememberCaseExclusionDraft();
  const d = c.draft, task = caseTaskDecisionCandidates(c.caseData).find(t => t.id === d.caseId);
  const ref = caseExclusionReference(task,d.referenceId).selected;
  if (!task || !ref?.expected_output || !["false","true"].includes(d.choice) || !d.rationale.trim() || !d.confirmed) {
    showToast(uiText("请选择标签和排除意见，填写依据并确认。", "Choose a label and exclusion, enter a rationale and confirm."),true); return;
  }
  const payload = {expected_output:ref.expected_output,tags:ref.tags || [],evidence_gaps:ref.evidence_gaps || [],is_excluded:d.choice === "true",rationale:d.rationale.trim(),source_revision_ids:task.resolution.heads.map(v => v.id),expected_previous_resolution_id:task.resolution.adjudication?.id || null,adjudication_scope:task.can_adjudicate_exclusion ? "exclusion" : "label",confirm_full_label:true};
  caseExclusionUi.saving = true; syncCaseExclusionSaving();
  try {
    const result = await api(`/api/labeling/label-cases/${encodeURIComponent(task.id)}/adjudications`, {method:"POST",body:JSON.stringify(payload)});
    acknowledgeLocalChange(result); c.saved = true; caseExclusionUi.drafts.delete(c.key); $("#caseLabelDecisionDialog")?.close();
    showToast(uiText("裁决已保存。", "Decision saved."));
    await refreshCaseDecisionResult(c);
  } catch (error) { showCaseDecisionError(c, error); }
  finally { caseExclusionUi.saving = false; syncCaseExclusionSaving(); }
}

function caseExclusionErrorMessage(error) {
  const message=String(error?.message || "");
  const known=[
    ["标注来源已变化，请刷新后重新裁决。", "Label sources changed. Refresh and decide again."],
    ["Issue 标签裁决已变化，请刷新后重新提交。", "The Issue decision changed. Refresh and try again."],
    ["仍有任务来源未完成或未裁决，不能跳过任务结果直接做 Issue 裁决。", "Resolve unfinished task sources before the final Issue decision."],
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
