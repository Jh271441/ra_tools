/* Shared exclusion input and read-only result helpers. */
function expectedOutputDisplayText(value) {
  const option = EXPECTED_OUTPUT_OPTIONS.find(item => item.value === value);
  return option ? (i18nLocale() === "en" ? option.labelEn : option.labelZh) : value;
}
function caseExclusionToggleMarkup(id, checked, disabled = false, decision = false) {
  return `<label class="review-exclude-toggle" title="${escapeHtml(uiText(decision ? "按 K 切换；随完整裁决确认" : "按 K 切换；随 Case 标签保存", decision ? "Press K to toggle; confirmed with the complete decision" : "Press K to toggle; saved with the Case label"))}"><input id="${id}" type="checkbox" aria-keyshortcuts="K" ${id === "reviewExcludeInput" ? 'data-case-exclusion="true"' : ""} ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}/><span><strong class="ui-lang-zh">排除此 Issue</strong><strong class="ui-lang-en">Exclude this Issue</strong><small class="ui-lang-zh">${decision ? "随完整裁决确认；同步到 Trail 需单独确认" : "随 Case 标签保存；同步到 Trail 需单独确认"}</small><small class="ui-lang-en">${decision ? "Confirmed with the full decision; Trail sync is separate" : "Saved with the Case label; Trail sync needs separate confirmation"}</small></span><kbd class="review-control-shortcut review-exclude-shortcut" aria-hidden="true">K</kbd></label>`;
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
  if (data.label_state?.decision?.full_result && !data.label_state.decision.stale) return false;
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
function refreshCaseExclusionSummary() {
  const c = caseLabelDecisionUi.context, data = state.activePage === "review" ? state.selectedCase : state.caseLabeling.caseData;
  if (!c || !data || !$("#caseLabelDecisionDialog")?.open) return;
  if (!isPageContextCurrent(c.pageContext) || c.caseData.issue_id !== data.issue_id || c.baselines !== selectedBaselineQueryValue()) { $("#caseLabelDecisionDialog").close(); return; }
  // Deferred Trail metadata can update facts without replacing the editor or draft.
  Object.assign(c.caseData, {trail_metadata_status:data.trail_metadata_status, dashboard_should_exclude:data.dashboard_should_exclude});
  const evidence = $("#caseDecisionEvidence");
  if (evidence) renderCaseLabelDecisionDialog();
}
function refreshCaseExclusionLanguage() {
  if ($("#caseDecisionInfoDialog")?.open) showCaseDecisionInfo();
}
function caseExclusionErrorMessage(error) {
  const message=String(error?.message || "");
  const known=[
    ["Issue 标签裁决需要已验证 writer 或管理员。", "Issue decisions require a verified writer or administrator."],
    ["Issue 标签裁决必须选择合法三分类结果。", "Choose a valid classification for this decision."],
    ["Issue 标签裁决必须填写裁决依据。", "Enter a decision review rationale."],
    ["Issue 不存在或不属于当前数据集。", "The Issue is unavailable in this dataset."],
    ["当前数据集尚未启用 Case 标注写入。", "Case labeling is not enabled for this dataset."],
    ["当前 Issue 还没有可裁决的标注来源。", "This Issue has no label sources to review."],
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
  const found=known.find(([zh,en])=>message.includes(zh) || message.includes(en));
  if (found) return uiText(...found);
  const bilingual=message.split(" / ");
  return bilingual.length === 2 ? uiText(...bilingual) : message;
}
