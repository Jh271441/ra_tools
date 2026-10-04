/* Shared Case/Review assignment naming: rule fallback, manual edits and model refresh.
 * Callbacks resolve page-specific context when invoked, after all modules load. */
const assignmentNameSuggestionState = {
  review: { timer: null, seq: 0, requestFingerprint: "", appliedFingerprint: "" },
  labeling: { timer: null, seq: 0, requestFingerprint: "", appliedFingerprint: "" },
};

function assignmentNameElements(kind) {
  return kind === "review"
    ? { input: $("#workSplitName"), status: $("#workSplitNameStatus"), refresh: $("#workSplitRefreshName") }
    : { input: $("#labelingTaskName"), status: $("#labelingTaskNameStatus"), refresh: $("#labelingTaskRefreshName") };
}

function assignmentBaselineIds(kind) {
  if (kind === "review") {
    return parseFilterList(workSplitFilters().baselines || workSplitFilters().baseline_scopes || []);
  }
  return parseFilterList(state.selectedBaselineIds || selectedBaselineQueryValue());
}

function assignmentBaselineLabels(ids) {
  const catalog = state.baselineCatalog || state.config?.baselines || [];
  return ids.map((id) => {
    const item = catalog.find((entry) => String(entry.id || "") === String(id));
    return String(item?.label || id);
  });
}

function assignmentNameContext(kind) {
  const baselineIds = assignmentBaselineIds(kind);
  const reviewersPerIssue = kind === "review"
    ? workSplitReviewersPerIssue()
    : labelingTaskReviewersPerIssue();
  const overlapRatio = reviewersPerIssue > 1
    ? (kind === "review" ? workSplitOverlapRatio() : labelingTaskOverlapRatio())
    : 0;
  const assignees = kind === "review"
    ? readWorkSplitAssignees()
    : readLabelingTaskAssignees();
  const filters = kind === "review" ? workSplitFilters() : {};
  const runId = kind === "review" ? String(filters.model_run_id || "") : "";
  const run = (state.modelRuns || []).find((item) => String(item.id || "") === runId);
  return {
    assignmentKind: kind === "review" ? "model_review" : "case_labeling",
    baselineIds,
    datasetLabels: assignmentBaselineLabels(baselineIds),
    caseCount: kind === "review" ? workSplitTotal() : Number(state.caseLabeling.data?.total || 0),
    reviewersPerIssue,
    overlapRatio,
    memberCount: assignees.length,
    workflowMode: kind === "review"
      ? ($("#workSplitWorkflowMode")?.value || "model_review_and_case_label")
      : "",
    modelRunId: runId,
    runName: String(run?.name || runId),
    comparison: String(filters.comparison || filters.comparison_status || "all"),
  };
}

function ruleBasedAssignmentName(context) {
  const scope = context.datasetLabels
    .map((label) => String(label || "").split("·", 1)[0].trim())
    .filter(Boolean).join("+") || "Dataset";
  const mode = context.memberCount <= 0
    ? "待选人员"
    : context.reviewersPerIssue > 1 && context.memberCount > 1 && context.overlapRatio > 0
      ? `${context.reviewersPerIssue}人交叉${Math.round(context.overlapRatio * 100)}%复核`
      : context.reviewersPerIssue === 1
        ? (context.memberCount === 1 ? "单人均分" : `${context.memberCount}人均分`)
        : `${context.reviewersPerIssue}人复核`;
  const subject = context.assignmentKind === "case_labeling"
    ? "Case标注"
    : context.workflowMode === "model_review_and_case_label" ? "联合复核" : "判错复核";
  const runPart = context.assignmentKind === "model_review"
    ? String(context.runName || "").split("·", 1)[0].trim().slice(0, 28)
    : "";
  const comparisonPart = context.assignmentKind === "model_review"
    && !["", "all"].includes(String(context.comparison || "").toLowerCase())
      ? String(context.comparison).toUpperCase()
      : "";
  const suffix = [subject, comparisonPart, mode, String(Math.max(1, context.caseCount)), "Case"]
    .filter(Boolean).join(" ");
  const prefix = [scope, runPart].filter(Boolean).join(" ");
  const available = Math.max(0, 80 - suffix.length - 1);
  return `${prefix.slice(0, available)} ${suffix}`.trim().slice(0, 80);
}

function renderAssignmentNameStatus(kind, status = "ready") {
  const { input, status: node, refresh } = assignmentNameElements(kind);
  if (!node || !input) return;
  const source = input.dataset.manualEdited === "true" ? "manual" : input.dataset.suggestionSource || "rule";
  if (refresh) {
    const context = assignmentNameContext(kind);
    const available = Boolean(state.session?.is_admin && context.baselineIds.length
      && context.caseCount && context.memberCount
      && (context.assignmentKind !== "model_review" || context.modelRunId));
    refresh.disabled = status === "loading" || !available;
    refresh.dataset.loading = String(status === "loading");
    refresh.setAttribute("aria-busy", String(status === "loading"));
    const label = status === "loading" ? uiText("正在生成实验名称", "Generating experiment name")
      : available ? uiText("重新生成实验名称", "Regenerate experiment name")
      : uiText("请先选择人员和分配范围", "Select people and an assignment scope first");
    refresh.title = label;
    refresh.setAttribute("aria-label", label);
  }
  const reasons = {
    not_configured: uiText("未配置模型", "Model not configured"),
    timeout: uiText("模型超时", "Model timed out"),
    unavailable: uiText("模型暂不可用", "Model unavailable"),
    invalid_output: uiText("名称未通过校验", "Name validation failed"),
    request_failed: uiText("请求失败", "Request failed"),
  };
  const reason = source === "rule" && status !== "loading" ? reasons[input.dataset.suggestionReason] || "" : "";
  node.dataset.status = status;
  node.dataset.source = source;
  node.textContent = source === "manual" ? uiText("手动编辑", "Manual")
    : source === "llm" ? uiText("模型结果", "Model result")
    : status === "loading" ? uiText("规则结果 · 优化中", "Rule · refining")
    : reason ? uiText("规则结果 · 未更新", "Rule · unchanged") : uiText("规则结果", "Rule result");
  node.title = source === "manual" ? uiText("保留你手动输入的名称", "Your edited name is preserved")
    : source === "llm" ? uiText("当前名称来自模型", "The current name was generated by the model")
    : status === "loading" ? uiText("当前为规则名称，正在请求模型优化", "Showing a rule name while requesting model refinement")
    : reason ? `${reason} · ${uiText("已使用规则名称，可点击刷新重试", "Using a rule name; refresh to retry")}`
    : uiText("当前名称按实验配置规则生成", "The current name was generated from configuration rules");
}

function updateAssignmentNameSuggestion(kind, { immediate = false } = {}) {
  const slot = assignmentNameSuggestionState[kind];
  const { input } = assignmentNameElements(kind);
  if (!slot || !input) return;
  const context = assignmentNameContext(kind);
  const fallback = ruleBasedAssignmentName(context);
  const fingerprint = JSON.stringify({
    assignment_kind: context.assignmentKind,
    baseline_ids: context.baselineIds,
    case_count: context.caseCount,
    reviewers_per_issue: context.reviewersPerIssue,
    overlap_ratio: context.overlapRatio,
    member_count: context.memberCount,
    workflow_mode: context.workflowMode,
    model_run_id: context.modelRunId,
    comparison: context.comparison,
    draft_name: fallback,
  });
  const manual = input.dataset.manualEdited === "true" && Boolean(input.value.trim());
  if (!manual && !(slot.appliedFingerprint === fingerprint && input.dataset.suggestionSource === "llm")) {
    input.value = fallback;
    input.dataset.suggestionSource = "rule";
    if (slot.appliedFingerprint !== fingerprint) input.dataset.suggestionReason = "";
  }
  window.clearTimeout(slot.timer);
  const seq = ++slot.seq;
  renderAssignmentNameStatus(kind);
  if (
    manual || !state.session?.is_admin
    || !context.baselineIds.length || !context.caseCount
    || !context.memberCount
    || (context.assignmentKind === "model_review" && !context.modelRunId)
  ) {
    renderAssignmentNameStatus(kind);
    return;
  }
  if (
    slot.appliedFingerprint === fingerprint
    && ["llm", "rule"].includes(input.dataset.suggestionSource)
  ) return;
  slot.requestFingerprint = fingerprint;
  renderAssignmentNameStatus(kind, "loading");
  slot.timer = window.setTimeout(async () => {
    try {
      const payload = await api("/api/assignment-name-suggestion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: fingerprint,
      });
      if (seq !== slot.seq || input.dataset.manualEdited === "true") return;
      const suggestion = String(payload.suggestion || "").trim();
      if (payload.source === "llm" && suggestion) {
        input.value = suggestion;
        input.dataset.suggestionSource = "llm";
        input.dataset.suggestionReason = "";
        slot.appliedFingerprint = fingerprint;
      } else {
        input.value = fallback;
        input.dataset.suggestionSource = "rule";
        input.dataset.suggestionReason = String(payload.reason || "");
        slot.appliedFingerprint = fingerprint;
      }
    } catch (_error) {
      if (seq === slot.seq && input.dataset.manualEdited !== "true") {
        input.value = fallback;
        input.dataset.suggestionSource = "rule";
        input.dataset.suggestionReason = "request_failed";
        slot.appliedFingerprint = fingerprint;
      }
    } finally {
      if (seq === slot.seq) renderAssignmentNameStatus(kind);
    }
  }, immediate ? 0 : 650);
}

function resetAssignmentNameSuggestion(kind) {
  const slot = assignmentNameSuggestionState[kind];
  const { input } = assignmentNameElements(kind);
  if (!slot || !input) return;
  window.clearTimeout(slot.timer);
  slot.seq += 1;
  slot.requestFingerprint = "";
  slot.appliedFingerprint = "";
  input.value = "";
  input.dataset.manualEdited = "false";
  input.dataset.suggestionSource = "";
  input.dataset.suggestionReason = "";
  updateAssignmentNameSuggestion(kind);
}

function bindAssignmentNameInput(kind) {
  const { input, refresh } = assignmentNameElements(kind);
  if (!input || input.dataset.assignmentNameBound === "1") return;
  input.dataset.assignmentNameBound = "1";
  refresh?.addEventListener("click", () => {
    if (refresh.disabled) return;
    const slot = assignmentNameSuggestionState[kind];
    slot.appliedFingerprint = "";
    input.dataset.manualEdited = "false";
    updateAssignmentNameSuggestion(kind, { immediate: true });
  });
  input.addEventListener("input", () => {
    input.dataset.manualEdited = input.value.trim() ? "true" : "false";
    if (input.dataset.manualEdited === "true") {
      const slot = assignmentNameSuggestionState[kind];
      window.clearTimeout(slot?.timer);
      if (slot) slot.seq += 1;
      renderAssignmentNameStatus(kind);
      return;
    }
    updateAssignmentNameSuggestion(kind);
  });
}
