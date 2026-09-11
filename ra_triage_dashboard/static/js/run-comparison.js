/* Read-only immutable Model Run inspection and comparison. */

const RUN_TRANSITIONS = ["ALL", "P2F", "F2P", "F2F", "P2P"];

function comparisonRunOptionLabel(run) {
  const name = String(run?.name || run?.source_name || run?.id || "未命名 Run");
  const coverage = Math.max(0, Number(run?.baseline_prediction_count || 0));
  const shortId = String(run?.id || "").slice(0, 8);
  const createdAt = typeof formatTime === "function"
    ? formatTime(run?.created_at)
    : String(run?.created_at || "");
  return [
    name,
    `${coverage} ${uiText("条当前数据集输出", "outputs in current dataset")}`,
    shortId,
    createdAt,
  ].filter(Boolean).join(" · ");
}

function normalizeComparisonRunSelection({ repairCoverage = false } = {}) {
  const available = (state.modelRuns || []).filter((run) => run?.id);
  // Route restoration can run before the async Run registry is available.
  // Preserve those IDs until there is a real option set to validate against.
  if (!available.length) return;
  const covered = available.filter((run) => Number(run.baseline_prediction_count || 0) > 0);
  const ids = new Set(available.map((run) => String(run.id)));
  const hadSelection = Boolean(
    state.runComparison.baselineRunId || state.runComparison.candidateRunId
  );
  if (state.runComparison.baselineRunId && !ids.has(String(state.runComparison.baselineRunId))) {
    state.runComparison.baselineRunId = "";
  }
  if (state.runComparison.candidateRunId && !ids.has(String(state.runComparison.candidateRunId))) {
    state.runComparison.candidateRunId = "";
  }
  if (!hadSelection) {
    state.runComparison.candidateRunId = covered[0]?.id || available[0]?.id || "";
    state.runComparison.baselineRunId = covered[1]?.id || available.find(
      (run) => String(run.id) !== String(state.runComparison.candidateRunId)
    )?.id || "";
  }
  if (
    state.runComparison.baselineRunId === state.runComparison.candidateRunId &&
    available.length > 1
  ) {
    state.runComparison.baselineRunId = String(
      covered.find((run) => String(run.id) !== String(state.runComparison.candidateRunId))?.id
        || available.find((run) => String(run.id) !== String(state.runComparison.candidateRunId))?.id
        || ""
    );
  }
  const selectedCoverage = available
    .filter((run) => [
      String(state.runComparison.baselineRunId || ""),
      String(state.runComparison.candidateRunId || ""),
    ].includes(String(run.id)))
    .reduce((sum, run) => sum + Number(run.baseline_prediction_count || 0), 0);
  // Dataset switches can leave two valid Run IDs in the URL even though both
  // belong to another workset. Prefer a useful pair for the current dataset;
  // a covered + zero-coverage pair remains valid for union/NONE comparison.
  if (repairCoverage && selectedCoverage <= 0 && covered.length) {
    if (state.runComparison.baselineRunId && !state.runComparison.candidateRunId) {
      state.runComparison.baselineRunId = String(covered[0].id);
    } else if (state.runComparison.candidateRunId && !state.runComparison.baselineRunId) {
      state.runComparison.candidateRunId = String(covered[0].id);
    } else {
      state.runComparison.candidateRunId = String(covered[0].id);
      state.runComparison.baselineRunId = String(
        covered[1]?.id
          || available.find((run) => String(run.id) !== String(covered[0].id))?.id
          || ""
      );
    }
  }
}

function renderRunComparisonSelectors({ repairCoverage = false } = {}) {
  normalizeComparisonRunSelection({ repairCoverage });
  const runOptions = (disabledId = "") => [
    { value: "", label: uiText("不选择（单 Run 查看）", "Not selected (single Run)") },
    ...(state.modelRuns || []).map((run) => ({
      value: String(run.id || ""),
      label: comparisonRunOptionLabel(run),
      disabled: Boolean(disabledId && String(run.id) === String(disabledId)),
    })),
  ];
  populateUiSelect(
    $("#comparisonBaselineRunPicker"),
    runOptions(state.runComparison.candidateRunId),
    state.runComparison.baselineRunId || "",
  );
  populateUiSelect(
    $("#comparisonCandidateRunPicker"),
    runOptions(state.runComparison.baselineRunId),
    state.runComparison.candidateRunId || "",
  );
  bindUiSelect($("#comparisonBaselineRunPicker"), { maxHeight: 380, maxWidth: 920 });
  bindUiSelect($("#comparisonCandidateRunPicker"), { maxHeight: 380, maxWidth: 920 });
  const selectedRunIds = [
    state.runComparison.baselineRunId,
    state.runComparison.candidateRunId,
  ].filter(Boolean);
  const selectedRuns = selectedRunIds
    .map((runId) => (state.modelRuns || []).find((run) => String(run.id) === String(runId)))
    .filter(Boolean);
  const valid = Boolean(
    selectedRunIds.length &&
    new Set(selectedRunIds).size === selectedRunIds.length &&
    selectedRuns.length === selectedRunIds.length
  );
  if ($("#comparisonLoadButton")) $("#comparisonLoadButton").disabled = !valid || state.runComparison.loading;
  if ($("#comparisonSelectionNote")) {
    const singleRun = selectedRunIds.length === 1;
    const selectedCoverage = selectedRuns.reduce(
      (sum, run) => sum + Number(run?.baseline_prediction_count || 0),
      0,
    );
    const oneSideMissing = selectedRuns.length === 2 && selectedRuns.some(
      (run) => Number(run.baseline_prediction_count || 0) <= 0
    );
    $("#comparisonSelectionNote").textContent = valid
        ? singleRun
          ? selectedCoverage > 0
            ? uiText("单 Run 查看；另一侧的对比内容已收起。", "Single Run view; comparison-only content is hidden.")
            : uiText("单 Run 查看；当前数据集暂无输出。", "Single Run view; no outputs in the current dataset.")
          : oneSideMissing
          ? uiText("按并集比较；无当前数据集输出的一侧将显示为 NONE。", "Union comparison; the uncovered side is shown as NONE.")
          : uiText("比较只读，不会修改任何 Review 或 Run。", "Comparison is read-only.")
        : uiText("请至少选择一个有效 Run。", "Choose at least one valid Run.");
  }
}

async function selectRunComparisonRun(side, runId) {
  const stateKey = side === "baseline" ? "baselineRunId" : "candidateRunId";
  state.runComparison[stateKey] = String(runId || "");
  state.runComparison.transition = "ALL";
  state.runComparison.labelChange = "ALL";
  if (!state.runComparison.baselineRunId) state.runComparison.baselineLabel = "ALL";
  if (!state.runComparison.candidateRunId) state.runComparison.candidateLabel = "ALL";
  if (!state.runComparison.baselineRunId || !state.runComparison.candidateRunId) {
    state.runComparison.inputFilter.run = state.runComparison.candidateRunId ? "candidate" : "baseline";
  }
  state.runComparison.page = 1;
  renderRunComparisonSelectors();
  const run = (state.modelRuns || []).find(
    (item) => String(item.id) === state.runComparison[stateKey]
  );
  if (!run) return false;
  // Reuse the immutable-scope inference used by Review and Analysis.
  // The last Run explicitly selected by the user owns the dataset switch.
  return applyInferredBaselinesFromRun(run, { reason: "run" });
}

function runComparisonRouteOptions(overrides = {}) {
  return {
    baselineRunId: state.runComparison.baselineRunId,
    candidateRunId: state.runComparison.candidateRunId,
    transition: state.runComparison.transition,
    gtLabel: state.runComparison.gtLabel,
    baselineLabel: state.runComparison.baselineLabel,
    candidateLabel: state.runComparison.candidateLabel,
    labelChange: state.runComparison.labelChange,
    inputFilter: state.runComparison.inputFilter,
    search: state.runComparison.search,
    page: state.runComparison.page,
    pageSize: state.runComparison.pageSize,
    ...overrides,
  };
}

function applyRunComparisonRoute(filters = {}) {
  state.runComparison.baselineRunId = String(filters.baselineRunId || "");
  state.runComparison.candidateRunId = String(filters.candidateRunId || "");
  state.runComparison.transition = RUN_TRANSITIONS.includes(String(filters.transition || "").toUpperCase())
    ? String(filters.transition).toUpperCase()
    : "ALL";
  state.runComparison.gtLabel = ["ALL", ...LABELS].includes(String(filters.gtLabel || ""))
    ? String(filters.gtLabel)
    : "ALL";
  state.runComparison.baselineLabel = ["ALL", ...MODEL_LABELS, "NONE"].includes(String(filters.baselineLabel || ""))
    ? String(filters.baselineLabel)
    : "ALL";
  state.runComparison.candidateLabel = ["ALL", ...MODEL_LABELS, "NONE"].includes(String(filters.candidateLabel || ""))
    ? String(filters.candidateLabel)
    : "ALL";
  state.runComparison.labelChange = ["ALL", "CHANGED", "UNCHANGED"].includes(String(filters.labelChange || "").toUpperCase())
    ? String(filters.labelChange).toUpperCase()
    : "ALL";
  try {
    const parsed = typeof filters.inputFilter === "string" ? JSON.parse(filters.inputFilter || "{}") : filters.inputFilter;
    state.runComparison.inputFilter = parsed?.version === 1
      ? parsed
      : { version: 1, run: "candidate", relation: "all", conditions: [] };
  } catch (_) {
    state.runComparison.inputFilter = { version: 1, run: "candidate", relation: "all", conditions: [] };
  }
  state.runComparison.search = String(filters.search || "").trim().slice(0, 128);
  state.runComparison.page = Math.max(1, Number(filters.page) || 1);
  state.runComparison.pageSize = CASE_PAGE_SIZES.includes(Number(filters.pageSize))
    ? Number(filters.pageSize)
    : 10;
  if ($("#comparisonSearchInput")) $("#comparisonSearchInput").value = state.runComparison.search;
  if ($("#comparisonPageSize")) $("#comparisonPageSize").value = String(state.runComparison.pageSize);
  if ($("#comparisonGtFilter")) $("#comparisonGtFilter").value = state.runComparison.gtLabel;
  if ($("#comparisonBaselineLabelFilter")) $("#comparisonBaselineLabelFilter").value = state.runComparison.baselineLabel;
  if ($("#comparisonCandidateLabelFilter")) $("#comparisonCandidateLabelFilter").value = state.runComparison.candidateLabel;
  if ($("#comparisonLabelChangeFilter")) $("#comparisonLabelChangeFilter").value = state.runComparison.labelChange;
  populateComparisonInputFilter();
  renderRunComparisonSelectors({ repairCoverage: true });
  renderRunComparisonTransitionFilter();
}

function runComparisonReviewUrl(issueId, runId) {
  const url = new URL(withBase(PAGE_ROUTES.review.path), window.location.origin);
  url.searchParams.set("issue", String(issueId));
  url.searchParams.set("run", String(runId));
  url.searchParams.set("comparison", "all");
  const baselines = selectedBaselineQueryValue();
  if (baselines) url.searchParams.set("baselines", baselines);
  return `${url.pathname}${url.search}`;
}

function comparisonTransitionText(value) {
  return {
    P2F: uiText("P2F · 退化", "P2F · Regression"),
    F2P: uiText("F2P · 改善", "F2P · Improvement"),
    F2F: uiText("F2F · 仍错误", "F2F · Still wrong"),
    P2P: uiText("P2P · 均正确", "P2P · Both correct"),
  }[value] || value;
}

function renderRunComparisonTransitionFilter() {
  document.querySelectorAll("[data-comparison-transition]").forEach((button) => {
    const value = String(button.dataset.comparisonTransition || "ALL");
    button.classList.toggle("active", value === state.runComparison.transition);
    const count = state.runComparison.data?.summary?.transition_counts?.[value];
    const baseLabel = button.dataset.baseLabel || button.textContent.replace(/\s+\d+$/, "").trim();
    button.dataset.baseLabel = baseLabel;
    button.textContent = value === "ALL" || count == null ? baseLabel : `${baseLabel} ${count}`;
  });
}

function comparisonSceneReviewTitle(review) {
  if (!review) return "";
  const source = {candidate: "新 Run Review", unbound: "未绑定 Run 的历史 Review", other_run: "其他 Run 的最新 Review"}[review.source] || "Review";
  return [source, review.author, typeof formatTime === "function" ? formatTime(review.created_at) : review.created_at].filter(Boolean).join(" · ");
}

function comparisonSceneTagsHtml(review) {
  const tags = Array.isArray(review?.tags) ? review.tags : [];
  if (!tags.length) return "";
  const full = `${tags.map(tagLabel).join(" · ")}\n${comparisonSceneReviewTitle(review)}`;
  return `<div class="comparison-scene-tags-line" tabindex="0" title="${escapeHtml(full)}">${tags.map((key) => {
    const item = reviewTagCatalogItem(key) || {};
    return `<span class="comparison-scene-tag" data-tag-section="${escapeHtml(item.section || "")}" data-tag-group="${escapeHtml(item.group || "")}">${escapeHtml(tagLabel(key))}</span>`;
  }).join("")}</div>`;
}

function comparisonExtraInputsEqual(left, right) {
  const comparable = (summary) => Object.fromEntries(Object.entries(summary?.axes || {}).sort().map(([axis, value]) => [
    axis,
    { status: value.status, counts: Object.fromEntries(Object.entries(value.counts || {}).sort()) },
  ]));
  return JSON.stringify(comparable(left)) === JSON.stringify(comparable(right));
}

function comparisonExtraAxisHtml(axis, compact = false) {
  if (!axis) return "";
  const chips = Object.entries(axis.counts || {}).filter(([, count]) => Number(count) > 0)
    .map(([label, count]) => `<span class="comparison-extra-chip">${escapeHtml(label)} ${Number(count)}帧</span>`).join("");
  return chips ? `<div class="comparison-extra-axis"><small>${escapeHtml(axis.label || "")}</small><div>${chips}</div></div>`
    : compact ? "" : `<div class="comparison-extra-axis"><small>${escapeHtml(axis.label || "")}</small><span class="muted">部分输入未保存</span></div>`;
}

function comparisonExtraSummaryHtml(summary, compact = false) {
  return Object.values(summary?.axes || {}).map((axis) => comparisonExtraAxisHtml(axis, compact)).join("");
}

function comparisonExtraInputsHtml(extraInputs, { dialog = false } = {}) {
  const baseline = extraInputs?.baseline || {};
  const candidate = extraInputs?.candidate || {};
  if (!baseline.available && !candidate.available) return "";
  if (baseline.available && candidate.available && comparisonExtraInputsEqual(baseline, candidate)) {
    return `<div class="comparison-extra-side">${comparisonExtraSummaryHtml(candidate, dialog)}</div>`;
  }
  return [
    baseline.available ? `<div class="comparison-extra-side"><b>基线</b>${comparisonExtraSummaryHtml(baseline, dialog)}</div>` : "",
    candidate.available ? `<div class="comparison-extra-side"><b>新 Run</b>${comparisonExtraSummaryHtml(candidate, dialog)}</div>` : "",
  ].join("");
}

function renderComparisonInputFilterSummary() {
  const filter = state.runComparison.inputFilter || {};
  const count = (filter.conditions || []).reduce((sum, item) => sum + (item.values || []).length, 0);
  const badge = $("#comparisonInputFilterCount");
  if (badge) { badge.hidden = !count; badge.textContent = String(count); }
  if ($("#comparisonInputFilterSummary")) $("#comparisonInputFilterSummary").textContent = count ? `额外输入 · ${count} 项` : "额外输入";
}

function populateComparisonInputFilter(filter = state.runComparison.inputFilter) {
  $("#comparisonInputFilterRun").value = filter?.run || "candidate";
  $("#comparisonInputFilterRelation").value = filter?.relation || "all";
  document.querySelectorAll("[data-input-filter-axis]").forEach((field) => {
    const condition = (filter?.conditions || []).find((item) => item.axis === field.dataset.inputFilterAxis);
    field.querySelector("[data-input-filter-operator]").value = condition?.operator || "any";
    field.querySelectorAll('input[type="checkbox"]').forEach((input) => { input.checked = Boolean(condition?.values?.includes(input.value)); });
  });
  renderComparisonInputFilterSummary();
}

function readComparisonInputFilterDraft() {
  const conditions = [...document.querySelectorAll("[data-input-filter-axis]")].map((field) => ({
    axis: field.dataset.inputFilterAxis,
    operator: field.querySelector("[data-input-filter-operator]").value,
    values: [...field.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value),
  })).filter((item) => item.values.length);
  return { version: 1, run: $("#comparisonInputFilterRun").value, relation: $("#comparisonInputFilterRelation").value, conditions };
}

function positionComparisonInputFilter() {
  const details = $("#comparisonInputFilter");
  const panel = details?.querySelector(".comparison-input-filter-panel");
  const trigger = details?.querySelector("summary");
  if (!details?.open || !panel || !trigger) return;
  const margin = 12;
  const gap = 6;
  const triggerRect = trigger.getBoundingClientRect();
  const width = Math.min(460, window.innerWidth - margin * 2);
  const measuredHeight = Math.min(panel.scrollHeight, window.innerHeight - margin * 2);
  const below = window.innerHeight - triggerRect.bottom - gap - margin;
  const above = triggerRect.top - gap - margin;
  const openAbove = below < Math.min(measuredHeight, 300) && above > below;
  const available = Math.max(120, openAbove ? above : below);
  const top = openAbove
    ? Math.max(margin, triggerRect.top - gap - Math.min(measuredHeight, available))
    : Math.min(window.innerHeight - margin, triggerRect.bottom + gap);
  const left = Math.max(margin, Math.min(triggerRect.right - width, window.innerWidth - width - margin));
  panel.style.setProperty("--comparison-filter-width", `${width}px`);
  panel.style.setProperty("--comparison-filter-left", `${left}px`);
  panel.style.setProperty("--comparison-filter-top", `${top}px`);
  panel.style.setProperty("--comparison-filter-max-height", `${available}px`);
}

function comparisonMetricCard(labelZh, labelEn, value, note = "", className = "") {
  return `<article class="page-card comparison-metric ${className}">
    <span><span class="ui-lang-zh">${escapeHtml(labelZh)}</span><span class="ui-lang-en">${escapeHtml(labelEn)}</span></span>
    <strong>${escapeHtml(String(value))}</strong>
    ${note ? `<small>${escapeHtml(note)}</small>` : ""}
  </article>`;
}

function percentage(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function renderRunComparisonSummary(payload) {
  const summary = payload.summary || {};
  const baseline = summary.baseline || {};
  const candidate = summary.candidate || {};
  if (payload.view_mode === "single") {
    const side = payload.candidate_run ? candidate : baseline;
    const run = payload.candidate_run || payload.baseline_run || {};
    $("#comparisonSummary").innerHTML = [
      comparisonMetricCard("Run 准确率", "Run accuracy", percentage(side.accuracy), `${side.correct_count || 0} / ${side.total_count || 0}`),
      comparisonMetricCard("有输出 Case", "Predicted cases", side.prediction_count || 0, run.name || run.id || ""),
      comparisonMetricCard("正确 Case", "Correct cases", side.correct_count || 0, `${side.total_count || 0} ${uiText("条 GT Case", "GT cases")}`),
    ].join("");
    return;
  }
  const delta = Number(summary.accuracy_delta || 0);
  const transitionCounts = summary.transition_counts || {};
  $("#comparisonSummary").innerHTML = [
    comparisonMetricCard("基线准确率", "Baseline accuracy", percentage(baseline.accuracy), `${baseline.correct_count || 0} / ${baseline.total_count || 0}`),
    comparisonMetricCard("新 Run 准确率", "Candidate accuracy", percentage(candidate.accuracy), `${candidate.correct_count || 0} / ${candidate.total_count || 0}`),
    comparisonMetricCard("准确率变化", "Accuracy delta", `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)} pp`, `${candidate.prediction_count || 0} ${uiText("条有输出", "predicted")}`, delta > 0 ? "is-positive" : delta < 0 ? "is-negative" : ""),
    comparisonMetricCard("P2F 退化", "P2F regressions", transitionCounts.P2F || 0, uiText("基线正确 → 新 Run 错误", "baseline correct → candidate wrong"), "is-negative"),
    comparisonMetricCard("F2P 改善", "F2P improvements", transitionCounts.F2P || 0, uiText("基线错误 → 新 Run 正确", "baseline wrong → candidate correct"), "is-positive"),
    comparisonMetricCard("标签变化", "Label changes", summary.label_changed_count || 0, `${summary.total_count || 0} ${uiText("条 GT Case", "GT cases")}`),
  ].join("");
}

function renderComparisonMatrix(targetSelector, matrix) {
  const columns = matrix?.columns || [];
  const rows = matrix?.rows || [];
  const header = columns.map((label) => `<th>${escapeHtml(label)}</th>`).join("");
  const body = rows.map((row) => {
    const cells = columns.map((label) => {
      const count = Number(row.cells?.[label] || 0);
      const correct = label !== "NONE" && modelLabelMatchesGt?.(label, row.gt_label);
      return `<td class="${correct ? "matrix-correct" : count ? "matrix-error" : ""}">${count}</td>`;
    }).join("");
    return `<tr><th>${escapeHtml(row.gt_label)}</th>${cells}<td>${row.total}</td><td>${percentage(row.accuracy)}</td></tr>`;
  }).join("");
  $(targetSelector).innerHTML = `<table class="comparison-matrix"><thead><tr><th>GT ↓ / Model →</th>${header}<th>Σ</th><th>Acc</th></tr></thead><tbody>${body}</tbody></table>`;
}

function comparisonSnapshotHtml(run) {
  const prompt = run?.prompt || {};
  const input = run?.input || {};
  const model = run?.model || {};
  const promptMeta = [prompt.version, prompt.mode, prompt.sha256 ? prompt.sha256.slice(0, 12) : ""].filter(Boolean).join(" · ");
  const inputJson = input.config && Object.keys(input.config).length
    ? JSON.stringify(input.config, null, 2)
    : "";
  return `<div class="comparison-snapshot-meta">
      <span><strong>Run</strong> ${escapeHtml(run?.name || run?.id || "—")}</span>
      <span><strong>Model</strong> ${escapeHtml(model.name || model.resolved_id || model.requested_id || "—")}</span>
      <span><strong>Input profile</strong> ${escapeHtml(input.profile || "—")}</span>
    </div>
    <h4>Prompt ${promptMeta ? `<small>${escapeHtml(promptMeta)}</small>` : ""}</h4>
    ${prompt.template ? `<pre>${escapeHtml(prompt.template)}</pre>` : `<p class="muted">${uiText("该 Run 没有保存 Prompt 快照。", "No Prompt snapshot was saved for this Run.")}</p>`}
    <h4><span class="ui-lang-zh">输入配置</span><span class="ui-lang-en">Input configuration</span></h4>
    ${inputJson ? `<pre>${escapeHtml(inputJson)}</pre>` : `<p class="muted">${uiText("该 Run 没有保存输入配置快照。", "No input snapshot was saved for this Run.")}</p>`}`;
}

function comparisonPredictionHtml(prediction, reviewUrl = "", reviewLabel = "") {
  const label = prediction?.model_label || "NONE";
  const confidence = prediction?.model_confidence;
  const verdict = prediction?.correct ? uiText("匹配 GT", "Matches GT") : uiText("不匹配 GT", "Differs from GT");
  const savedReason = String(prediction?.model_reason || "").trim();
  const reason = savedReason || uiText("未保存／未生成 Reason", "Reason not saved / generated");
  const reasonTooltip = savedReason
    ? ` title="${escapeHtml(savedReason)}" aria-label="${escapeHtml(savedReason)}"`
    : ` aria-label="${escapeHtml(reason)}"`;
  return `<div class="comparison-prediction ${prediction?.correct ? "is-correct" : "is-error"}">
    <div class="comparison-prediction-output"><strong class="comparison-output-label">${escapeHtml(label)}</strong>${confidence == null ? "" : `<span class="comparison-prediction-confidence">${Number(confidence).toFixed(3)}</span>`}<small class="comparison-prediction-verdict comparison-chip ${prediction?.correct ? "comparison-match" : "comparison-mismatch"}">${escapeHtml(verdict)}</small></div>
    <span class="comparison-prediction-reason${savedReason ? " has-saved-reason" : " is-empty"}"${reasonTooltip}>${escapeHtml(reason)}</span>
    ${reviewUrl ? `<a class="button button-quiet comparison-inline-review" href="${escapeHtml(reviewUrl)}">${escapeHtml(reviewLabel)}</a>` : ""}
  </div>`;
}

function renderComparisonReasonSide(prefix, prediction, run) {
  const confidence = prediction?.model_confidence;
  const verdict = prediction?.correct ? uiText("匹配 GT", "Matches GT") : uiText("不匹配 GT", "Differs from GT");
  $(`#comparisonReason${prefix}Run`).textContent = run?.name || run?.id || "—";
  $(`#comparisonReason${prefix}ModelLabel`).textContent = prediction?.model_label || "NONE";
  $(`#comparisonReason${prefix}ModelLabel`).dataset.triageLabel = prediction?.model_label || "NONE";
  $(`#comparisonReason${prefix}Confidence`).textContent = confidence == null ? "—" : Number(confidence).toFixed(3);
  const verdictElement = $(`#comparisonReason${prefix}Verdict`);
  verdictElement.textContent = verdict;
  verdictElement.classList.toggle("is-error", !prediction?.correct);
  $(`#comparisonReason${prefix}Body`).textContent = prediction?.model_reason || uiText("未保存／未生成 Reason", "Reason not saved / generated");
}

function openComparisonReasonDialog(issueId, { preserveTab = false } = {}) {
  const payload = state.runComparison.data;
  const item = (payload?.items || []).find((entry) => String(entry.issue_id) === String(issueId));
  if (!item) return;
  const dialog = $("#comparisonReasonDialog");
  const selectedTab = preserveTab ? dialog.dataset.tab || "output" : "output";
  const single = payload?.view_mode === "single";
  dialog.classList.toggle("is-single-run", single);
  dialog.querySelector(".comparison-case-tabs")?.setAttribute("aria-label", uiText(single ? "Case 详情" : "Case 对比", single ? "Case details" : "Case comparison"));
  $("#comparisonReasonTitle").textContent = `${item.issue_id} · ${uiText(single ? "Case 详情" : "Case 对比", single ? "Case details" : "Case comparison")}`;
  $("#comparisonReasonContext").innerHTML = `<span class="comparison-context-gt"><small>GT</small><strong data-triage-label="${escapeHtml(item.gt_label || "")}">${escapeHtml(item.gt_label || "未保存")}</strong></span>${single ? "" : `<span class="comparison-context-transition">${escapeHtml(comparisonTransitionText(item.transition))}</span>`}`;
  const extraTarget = $("#comparisonDialogExtraInputs");
  extraTarget.innerHTML = comparisonExtraInputsHtml(item.extra_inputs, { dialog: true });
  extraTarget.hidden = !extraTarget.innerHTML;
  const tagTarget = $("#comparisonDialogSceneTags");
  tagTarget.innerHTML = comparisonSceneTagsHtml(item.scene_review);
  tagTarget.hidden = !tagTarget.innerHTML;
  $("#comparisonCaseScroll").scrollTop = 0;
  const baselinePanel = $("#comparisonReasonBaselinePanel");
  const candidatePanel = $("#comparisonReasonCandidatePanel");
  baselinePanel.hidden = !payload?.baseline_run;
  candidatePanel.hidden = !payload?.candidate_run;
  if (payload?.baseline_run) renderComparisonReasonSide("Baseline", item.baseline, payload.baseline_run);
  if (payload?.candidate_run) renderComparisonReasonSide("Candidate", item.candidate, payload.candidate_run);
  dialog.dataset.issueId = String(issueId);
  const preview = $('#comparisonCaseBevImage');
  preview.hidden = false;
  preview.parentElement.classList.remove('is-missing');
  preview.src = withBase(`/api/case-thumbnails/${encodeURIComponent(issueId)}`);
  loadComparisonImagePreviews(issueId);
  selectComparisonCaseTab(selectedTab);
  if (dialog && !dialog.open) dialog.showModal();
  loadComparisonCaseInputs(issueId, payload);
}

async function stepComparisonCaseDialog(delta) {
  const dialog = $("#comparisonReasonDialog");
  if (!dialog?.open || state.activePage !== "comparison") return;
  let payload = state.runComparison.data;
  let items = payload?.items || [];
  const index = items.findIndex((item) => String(item.issue_id) === String(dialog.dataset.issueId));
  if (index < 0) return;
  let next = items[index + delta];
  if (!next) {
    const page = Number(payload.page) + delta;
    if (page < 1 || page > Number(payload.page_count)) {
      showToast(
        delta < 0
          ? uiText("已经是第一个 Case", "Already at the first Case")
          : uiText("已经是最后一个 Case", "Already at the last Case")
      );
      return;
    }
    state.runComparison.page = page;
    await loadRunComparison({ historyMode: "replace" });
    if (!dialog.open) return;
    payload = state.runComparison.data;
    items = payload?.items || [];
    next = delta > 0 ? items[0] : items[items.length - 1];
  }
  if (next) openComparisonReasonDialog(next.issue_id, { preserveTab: true });
}

let comparisonCaseNavigationTail = Promise.resolve();
function navigateComparisonCaseDialog(delta) {
  const direction = delta < 0 ? -1 : 1;
  const task = comparisonCaseNavigationTail.then(() => stepComparisonCaseDialog(direction));
  comparisonCaseNavigationTail = task.catch(() => {});
  return task;
}

function renderRunComparisonCases(payload) {
  const baselineRunId = payload.baseline_run?.id || "";
  const candidateRunId = payload.candidate_run?.id || "";
  const rows = (payload.items || []).map((item) => {
    const single = payload.view_mode === "single";
    const reviewRunId = candidateRunId || baselineRunId;
    const rowLabel = uiText(
      `打开 ${item.issue_id} 的${single ? "单 Run 详情" : "双 Run Case 对比"}`,
      `Open ${single ? "the single-Run details" : "the two-Run comparison"} for ${item.issue_id}`,
    );
    return `<tr class="transition-${escapeHtml(String(item.transition || "").toLowerCase())}" data-comparison-row data-issue-id="${escapeHtml(item.issue_id)}" tabindex="0" aria-label="${escapeHtml(rowLabel)}">
      <td><a class="comparison-issue-link" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, reviewRunId))}">${escapeHtml(item.issue_id)}</a><div class="comparison-issue-meta"><span class="comparison-gt-summary"><span>GT</span><strong>${escapeHtml(item.gt_label || "—")}</strong></span><small>${escapeHtml(item.baseline_scope || "")}</small></div>${comparisonSceneTagsHtml(item.scene_review)}</td>
      <td><button type="button" class="comparison-bev" data-comparison-media="${escapeHtml(item.issue_id)}" aria-label="打开 ${escapeHtml(item.issue_id)} 参考媒体"><img loading="lazy" src="${escapeHtml(withBase(`/api/case-thumbnails/${encodeURIComponent(item.issue_id)}`))}" alt="BEV 预览"><span>暂无 BEV</span></button></td>
      ${baselineRunId ? `<td>${comparisonPredictionHtml(item.baseline, runComparisonReviewUrl(item.issue_id, baselineRunId), uiText("基线复核", "Baseline review"))}</td>` : ""}
      ${candidateRunId ? `<td>${comparisonPredictionHtml(item.candidate, runComparisonReviewUrl(item.issue_id, candidateRunId), uiText("新 Run 复核", "Candidate review"))}</td>` : ""}
      ${single ? "" : `<td><div class="comparison-transition-cell"><span class="comparison-transition-badge ${escapeHtml(String(item.transition || "").toLowerCase())}">${escapeHtml(comparisonTransitionText(item.transition))}</span></div></td>`}
      <td><div class="comparison-extra-inputs">${comparisonExtraInputsHtml(item.extra_inputs) || `<span class="muted">未保存</span>`}</div></td>
    </tr>`;
  }).join("");
  const columnCount = 3 + Number(Boolean(baselineRunId)) + Number(Boolean(candidateRunId)) + Number(payload.view_mode !== "single");
  $("#comparisonCaseRows").innerHTML = rows || `<tr><td colspan="${columnCount}" class="comparison-no-rows">${uiText("当前条件下没有 Case。", "No cases match the current filters.")}</td></tr>`;
  $("#comparisonCaseRows").querySelectorAll('.comparison-bev img').forEach(img => {
    img.addEventListener('error', () => { img.hidden = true; img.parentElement.classList.add('is-missing'); });
  });
  $("#comparisonCaseCount").textContent = uiText(
    `筛选后 ${payload.total || 0} 条；当前第 ${payload.page || 1} / ${payload.page_count || 1} 页`,
    `${payload.total || 0} filtered · page ${payload.page || 1} / ${payload.page_count || 1}`
  );
  const page = Math.max(1, Number(payload.page) || 1);
  const pageCount = Math.max(1, Number(payload.page_count) || 1);
  $("#comparisonPageSummary").textContent = `${page} / ${pageCount}`;
  $("#comparisonPagePrevious").disabled = page <= 1;
  $("#comparisonPageNext").disabled = page >= pageCount;
  const jumpInput = $("#comparisonPageJump");
  if (jumpInput) {
    const focused = document.activeElement === jumpInput;
    jumpInput.max = String(pageCount);
    jumpInput.disabled = pageCount <= 1;
    jumpInput.dataset.pageCount = String(pageCount);
    if (!focused) jumpInput.value = String(page);
  }
  if ($("#comparisonPageJumpButton")) $("#comparisonPageJumpButton").disabled = pageCount <= 1;
  if ($("#comparisonPageSize")) $("#comparisonPageSize").value = String(state.runComparison.pageSize);
}

function renderRunComparison(payload = state.runComparison.data) {
  const hasPayload = Boolean(payload?.summary);
  $("#comparisonEmptyState")?.classList.toggle("hidden", hasPayload);
  $("#comparisonResults")?.classList.toggle("hidden", !hasPayload);
  renderRunComparisonSelectors();
  renderRunComparisonTransitionFilter();
  if (!hasPayload) return;
  const single = payload.view_mode === "single";
  $("#comparisonResults").classList.toggle("is-single-run", single);
  $("#comparisonCasesTitle").textContent = uiText(single ? "Case 明细" : "Case 变化明细", single ? "Cases" : "Case transitions");
  $("#comparisonTransitionFilter").hidden = single;
  $("#comparisonLabelChangeFilter")?.closest("label")?.toggleAttribute("hidden", single);
  $("#comparisonBaselineLabelFilter")?.closest("label")?.toggleAttribute("hidden", !payload.baseline_run);
  $("#comparisonCandidateLabelFilter")?.closest("label")?.toggleAttribute("hidden", !payload.candidate_run);
  $("#comparisonBaselineOutputHeading").hidden = !payload.baseline_run;
  $("#comparisonCandidateOutputHeading").hidden = !payload.candidate_run;
  $("#comparisonTransitionHeading").hidden = single;
  const inputRunFilter = $("#comparisonInputFilterRun");
  if (inputRunFilter) {
    inputRunFilter.querySelector('option[value="baseline"]').disabled = !payload.baseline_run;
    inputRunFilter.querySelector('option[value="candidate"]').disabled = !payload.candidate_run;
    inputRunFilter.querySelector('option[value="either"]').disabled = single;
  }
  if (single) {
    state.runComparison.inputFilter.run = payload.candidate_run ? "candidate" : "baseline";
    populateComparisonInputFilter();
  }
  renderRunComparisonSummary(payload);
  $("#comparisonBaselineMatrixCard").hidden = !payload.baseline_run;
  $("#comparisonCandidateMatrixCard").hidden = !payload.candidate_run;
  if (payload.baseline_run) {
    renderComparisonMatrix("#comparisonBaselineMatrix", payload.summary.baseline);
    $("#comparisonBaselineMatrixMeta").textContent = percentage(payload.summary.baseline?.accuracy);
  }
  if (payload.candidate_run) {
    renderComparisonMatrix("#comparisonCandidateMatrix", payload.summary.candidate);
    $("#comparisonCandidateMatrixMeta").textContent = percentage(payload.summary.candidate?.accuracy);
  }
  renderComparisonRunDiff(payload);
  renderRunComparisonCases(payload);
}

async function loadRunComparison({ historyMode = "replace" } = {}) {
  const baselineRunId = String(state.runComparison.baselineRunId || "");
  const candidateRunId = String(state.runComparison.candidateRunId || "");
  if ((!baselineRunId && !candidateRunId) || (baselineRunId && baselineRunId === candidateRunId)) {
    state.runComparison.data = null;
    renderRunComparison();
    return;
  }
  const requestSeq = ++state.runComparison.requestSeq;
  state.runComparison.loading = true;
  renderRunComparisonSelectors();
  const params = new URLSearchParams({
    baseline_run_id: baselineRunId,
    candidate_run_id: candidateRunId,
    transition: state.runComparison.transition,
    gt_label: state.runComparison.gtLabel,
    baseline_label: state.runComparison.baselineLabel,
    candidate_label: state.runComparison.candidateLabel,
    label_change: state.runComparison.labelChange,
    input_filter: JSON.stringify(state.runComparison.inputFilter || {}),
    q: state.runComparison.search,
    page: String(state.runComparison.page),
    page_size: String(state.runComparison.pageSize),
  });
  const baselines = selectedBaselineQueryValue();
  if (baselines) params.set("baselines", baselines);
  try {
    const payload = await api(`/api/model-run-comparison?${params.toString()}`);
    if (requestSeq !== state.runComparison.requestSeq) return;
    state.runComparison.data = payload;
    state.runComparison.page = Number(payload.page || 1);
    renderRunComparison(payload);
    if (historyMode) {
      const route = pageUrl("comparison", runComparisonRouteOptions());
      history[historyMode === "push" ? "pushState" : "replaceState"]({ page: "comparison" }, "", route);
    }
  } finally {
    if (requestSeq === state.runComparison.requestSeq) {
      state.runComparison.loading = false;
      renderRunComparisonSelectors();
    }
  }
}

async function jumpToRunComparisonPage(rawPage) {
  const pageCount = Math.max(1, Number(state.runComparison.data?.page_count) || 1);
  const target = Number(rawPage);
  if (!Number.isInteger(target) || target < 1 || target > pageCount) {
    showToast(uiText(`请输入 1–${pageCount} 之间的页码。`, `Enter a page from 1–${pageCount}.`), true);
    return;
  }
  if (target === state.runComparison.page) {
    const input = $("#comparisonPageJump");
    if (input) input.value = String(target);
    return;
  }
  state.runComparison.page = target;
  await loadRunComparison({ historyMode: "push" });
}

function bindRunComparisonEvents() {
  $('#comparisonCaseCamera')?.addEventListener('click', () => openComparisonMedia($('#comparisonReasonDialog').dataset.issueId, 'camera').catch(error => showToast(error.message,true)));

  $('#comparisonCaseBev')?.addEventListener('click', () => openComparisonMedia($('#comparisonReasonDialog').dataset.issueId, 'bev').catch(error => showToast(error.message,true)));
  $('#comparisonCaseCameraImage')?.addEventListener('error', event => { event.target.hidden=true; event.target.parentElement.classList.add('is-missing'); });
  $('#comparisonCaseBevImage')?.addEventListener('error', event => { event.target.hidden = true; event.target.parentElement.classList.add('is-missing'); });
  $('#comparisonReasonDialog')?.addEventListener('close', () => { comparisonCaseRequest++; });
  $('#comparisonInputFilter')?.addEventListener('toggle', (event) => {
    if (event.target.open) {
      populateComparisonInputFilter();
      window.requestAnimationFrame(positionComparisonInputFilter);
    }
  });
  window.addEventListener('resize', positionComparisonInputFilter);
  window.addEventListener('scroll', positionComparisonInputFilter, true);
  $('#comparisonInputFilterApply')?.addEventListener('click', () => {
    state.runComparison.inputFilter = readComparisonInputFilterDraft();
    state.runComparison.page = 1;
    $('#comparisonInputFilter').open = false;
    renderComparisonInputFilterSummary();
    loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
  });
  $('#comparisonInputFilterClear')?.addEventListener('click', () => populateComparisonInputFilter({ version: 1, run: "candidate", relation: "all", conditions: [] }));
  document.addEventListener('click', (event) => {
    const details = $('#comparisonInputFilter');
    if (details?.open && !details.contains(event.target)) details.open = false;
  });
  document.addEventListener('keydown', (event) => {
    const details = $('#comparisonInputFilter');
    if (event.key === 'Escape' && details?.open) { details.open = false; details.querySelector('summary')?.focus(); }
  });
  document.querySelectorAll('[data-case-tab]').forEach(button => button.addEventListener('click', () => selectComparisonCaseTab(button.dataset.caseTab)));
  $('#comparisonCaseRows')?.addEventListener('click', event => {
    const button=event.target.closest('[data-comparison-media]');
    if(button) openComparisonMedia(button.dataset.comparisonMedia, 'bev').catch(error => showToast(error.message,true));
  });
  $("#comparisonCaseRows")?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-comparison-row]");
    if (!row || event.target.closest("a, button, input, select, textarea")) return;
    openComparisonReasonDialog(row.dataset.issueId);
  });
  $("#comparisonCaseRows")?.addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-comparison-row]");
    if (!row || event.target !== row || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    openComparisonReasonDialog(row.dataset.issueId);
  });
  $("#comparisonReasonDialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  $("#comparisonBaselineRun")?.addEventListener("change", (event) => {
    selectRunComparisonRun("baseline", event.target.value).catch((error) =>
      showToast(error.message || String(error), true)
    );
  });
  $("#comparisonCandidateRun")?.addEventListener("change", (event) => {
    selectRunComparisonRun("candidate", event.target.value).catch((error) =>
      showToast(error.message || String(error), true)
    );
  });
  $("#comparisonSwapButton")?.addEventListener("click", () => {
    [state.runComparison.baselineRunId, state.runComparison.candidateRunId] = [
      state.runComparison.candidateRunId,
      state.runComparison.baselineRunId,
    ];
    state.runComparison.page = 1;
    renderRunComparisonSelectors();
    loadRunComparison().catch((error) => showToast(error.message, true));
  });
  $("#comparisonLoadButton")?.addEventListener("click", () => {
    state.runComparison.page = 1;
    loadRunComparison().catch((error) => showToast(error.message, true));
  });
  document.querySelectorAll("[data-comparison-transition]").forEach((button) => {
    button.addEventListener("click", () => {
      state.runComparison.transition = button.dataset.comparisonTransition || "ALL";
      state.runComparison.page = 1;
      renderRunComparisonTransitionFilter();
      loadRunComparison().catch((error) => showToast(error.message, true));
    });
  });
  const filterBindings = [
    ["#comparisonGtFilter", "gtLabel"],
    ["#comparisonBaselineLabelFilter", "baselineLabel"],
    ["#comparisonCandidateLabelFilter", "candidateLabel"],
    ["#comparisonLabelChangeFilter", "labelChange"],
  ];
  filterBindings.forEach(([selector, stateKey]) => {
    $(selector)?.addEventListener("change", (event) => {
      state.runComparison[stateKey] = event.target.value || "ALL";
      state.runComparison.page = 1;
      loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
    });
  });
  $("#comparisonResetFilters")?.addEventListener("click", () => {
    state.runComparison.transition = "ALL";
    state.runComparison.gtLabel = "ALL";
    state.runComparison.baselineLabel = "ALL";
    state.runComparison.candidateLabel = "ALL";
    state.runComparison.labelChange = "ALL";
    state.runComparison.search = "";
    state.runComparison.inputFilter = { version: 1, run: "candidate", relation: "all", conditions: [] };
    state.runComparison.page = 1;
    if ($("#comparisonSearchInput")) $("#comparisonSearchInput").value = "";
    if ($("#comparisonGtFilter")) $("#comparisonGtFilter").value = "ALL";
    if ($("#comparisonBaselineLabelFilter")) $("#comparisonBaselineLabelFilter").value = "ALL";
    if ($("#comparisonCandidateLabelFilter")) $("#comparisonCandidateLabelFilter").value = "ALL";
    if ($("#comparisonLabelChangeFilter")) $("#comparisonLabelChangeFilter").value = "ALL";
    renderRunComparisonTransitionFilter();
    populateComparisonInputFilter();
    loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
  });
  let searchTimer = null;
  $("#comparisonSearchInput")?.addEventListener("input", (event) => {
    state.runComparison.search = event.target.value.trim().slice(0, 128);
    state.runComparison.page = 1;
    if (searchTimer) window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadRunComparison().catch((error) => showToast(error.message, true)), 250);
  });
  $("#comparisonPagePrevious")?.addEventListener("click", () => {
    state.runComparison.page = Math.max(1, state.runComparison.page - 1);
    loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
  });
  $("#comparisonPageNext")?.addEventListener("click", () => {
    state.runComparison.page += 1;
    loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
  });
  const comparisonPageJump = $("#comparisonPageJump");
  const commitComparisonPageJump = () => {
    jumpToRunComparisonPage(comparisonPageJump?.value).catch((error) => showToast(error.message, true));
  };
  $("#comparisonPageJumpButton")?.addEventListener("click", commitComparisonPageJump);
  comparisonPageJump?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitComparisonPageJump();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      comparisonPageJump.value = String(state.runComparison.page);
      comparisonPageJump.blur();
    }
  });
  comparisonPageJump?.addEventListener("focus", () => {
    window.requestAnimationFrame(() => comparisonPageJump.select());
  });
  $("#comparisonPageSize")?.addEventListener("change", (event) => {
    state.runComparison.pageSize = CASE_PAGE_SIZES.includes(Number(event.target.value)) ? Number(event.target.value) : 10;
    state.runComparison.page = 1;
    loadRunComparison({ historyMode: "push" }).catch((error) => showToast(error.message, true));
  });
}

// Bounded LCS: at most one million cells; oversized inputs stay readable as text.
function comparisonDiffLines(left, right) {
  const a = left.split('\n'), b = right.split('\n');
  if (left.length + right.length > 200000 || a.length * b.length > 1000000) return null;
  const dp = Array.from({length: a.length + 1}, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) {
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const rows = []; let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) rows.push({kind:'same', a:a[i++], b:b[j++], i, j});
    else if (i < a.length && (j === b.length || dp[i + 1][j] >= dp[i][j + 1])) rows.push({kind:'delete', a:a[i++], i});
    else rows.push({kind:'add', b:b[j++], j});
  }
  const aligned = [];
  for (let n = 0; n < rows.length;) {
    if (rows[n].kind === 'same') { aligned.push(rows[n++]); continue; }
    const removed = [], added = [];
    while (n < rows.length && rows[n].kind !== 'same') { const r = rows[n++]; (r.kind === 'delete' ? removed : added).push(r); }
    for (let k = 0; k < Math.max(removed.length, added.length); k++) aligned.push({...removed[k], ...added[k], kind: removed[k] && added[k] ? 'change' : removed[k] ? 'delete' : 'add'});
  }
  return aligned;
}

function comparisonInline(a, b) {
  if (a == null || b == null) return [escapeHtml(a || ''), escapeHtml(b || '')];
  let start = 0, end = 0;
  while (start < Math.min(a.length, b.length) && a[start] === b[start]) start++;
  while (end < Math.min(a.length, b.length) - start && a[a.length - end - 1] === b[b.length - end - 1]) end++;
  return [a,b].map(s => `${escapeHtml(s.slice(0,start))}<mark>${escapeHtml(s.slice(start,s.length-end))}</mark>${escapeHtml(end ? s.slice(-end) : '')}`);
}

function mountComparisonDiff(target, left, right) {
  left = String(left || ''); right = String(right || '');
  const rows = comparisonDiffLines(left, right);
  target.innerHTML = `<div class="comparison-diff-controls"><label><input type="checkbox" data-diff-full> 完整原文</label><label><input type="checkbox" data-diff-unified> 统一视图</label></div><div class="comparison-diff-body"></div>`;
  const draw = () => {
    const full = target.querySelector('[data-diff-full]').checked;
    const unified = target.querySelector('[data-diff-unified]').checked;
    const body = target.querySelector('.comparison-diff-body');
    let notice = !left && !right ? '两侧均未保存' : !left ? '基线未保存' : !right ? '新 Run 未保存' : left === right ? '内容一致' : '';
    if (!rows || full) {
      body.innerHTML = `<p>${escapeHtml(notice)} ${!rows ? '文本超出差异计算上限，已降级为原文。' : ''}</p><div class="comparison-original"><pre>${escapeHtml(left || '未保存')}</pre><pre>${escapeHtml(right || '未保存')}</pre></div>`;
      return;
    }
    const renderRow = r => {
      const [a,b] = r.kind === 'change' ? comparisonInline(r.a,r.b) : [escapeHtml(r.a || ''),escapeHtml(r.b || '')];
      if (unified) return r.kind === 'same' ? `<div class="diff-line same"><small>${r.i} / ${r.j}</small><code> ${a}</code></div>` : `${r.a == null ? '' : `<div class="diff-line delete"><small>${r.i}</small><code>− ${a}</code></div>`}${r.b == null ? '' : `<div class="diff-line add"><small>${r.j}</small><code>+ ${b}</code></div>`}`;
      return `<div class="diff-pair"><div class="diff-line ${r.a == null ? 'empty' : r.kind === 'same' ? 'same' : 'delete'}"><small>${r.i || ''}</small><code>${a}</code></div><div class="diff-line ${r.b == null ? 'empty' : r.kind === 'same' ? 'same' : 'add'}"><small>${r.j || ''}</small><code>${b}</code></div></div>`;
    };
    let html = '';
    for (let n=0;n<rows.length;) {
      if (rows[n].kind !== 'same') {html += renderRow(rows[n++]); continue;}
      const start = n; while(n<rows.length && rows[n].kind==='same') n++;
      const group = rows.slice(start,n);
      html += group.length > 8 ? group.slice(0,3).map(renderRow).join('') + `<details class="diff-fold"><summary>展开 ${group.length-6} 行相同内容</summary>${group.slice(3,-3).map(renderRow).join('')}</details>` + group.slice(-3).map(renderRow).join('') : group.map(renderRow).join('');
    }
    body.innerHTML = `${notice ? `<p class="diff-notice">${escapeHtml(notice)}</p>` : ""}<div class="diff-head"><span>基线</span><span>新 Run</span></div>${html}`;
  };
  target.querySelectorAll('input').forEach(input => input.addEventListener('change',draw)); draw();
}

function comparisonCanonical(value) {
  if (Array.isArray(value)) return value.map(comparisonCanonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k,comparisonCanonical(value[k])]));
  return value;
}
function comparisonConfigText(value) { return value == null ? '' : JSON.stringify(comparisonCanonical(value),null,2); }
function comparisonPromptMeta(prompt) {
  const types = {actual_input:'实际输入',run_example:'Run 示例',run_template:'Run 模板',not_saved:'未保存'};
  const hash = String(prompt?.sha256 || prompt?.computed_sha256 || '');
  const details = [prompt?.source, prompt?.version, prompt?.stage, hash, prompt?.hash_matches === false ? '保存哈希与文本不一致' : '', prompt?.redacted ? '展示内容已脱敏' : ''].filter(Boolean).map(escapeHtml).join('<br>');
  return `<span class="prompt-source-badge">${escapeHtml(types[prompt?.source_type] || '未保存')}</span>${prompt?.example_case_id ? `<span class="prompt-example">示例 Case: ${escapeHtml(prompt.example_case_id)}</span>` : ''}<details class="prompt-provenance"><summary>${hash ? `SHA ${escapeHtml(hash.slice(0,12))}` : '来源信息'}</summary><div>${details || '未保存'}</div></details>`;
}
function renderComparisonRunDiff(payload) {
  const target = $('#comparisonRunDiff');
  const a=payload.baseline_run, b=payload.candidate_run;
  if (payload.view_mode === 'single') {
    target.innerHTML = comparisonSnapshotHtml(b || a);
    return;
  }
  target.innerHTML = `<div class="comparison-original"><div class="prompt-meta"><strong>${escapeHtml(a.name)}</strong><br>${comparisonPromptMeta(a.prompt)}</div><div class="prompt-meta"><strong>${escapeHtml(b.name)}</strong><br>${comparisonPromptMeta(b.prompt)}</div></div><h4>Prompt</h4><div data-run-prompt></div><h4>输入配置 · Run 参考</h4><div data-run-config></div>`;
  mountComparisonDiff(target.querySelector('[data-run-prompt]'),a.prompt?.template,b.prompt?.template);
  mountComparisonDiff(target.querySelector('[data-run-config]'),a.input?.available ? comparisonConfigText(a.input.config) : '', b.input?.available ? comparisonConfigText(b.input.config) : '');
}
let comparisonCaseRequest = 0;
async function loadComparisonCaseInputs(issueId,payload) {
  const seq=++comparisonCaseRequest;
  const target=$('#comparisonCaseInputs'); target.textContent='正在读取已保存输入…';
  const params=new URLSearchParams({baselines:selectedBaselineQueryValue() || ''});
  if (payload.baseline_run?.id) params.set('baseline_run_id', payload.baseline_run.id);
  if (payload.candidate_run?.id) params.set('candidate_run_id', payload.candidate_run.id);
  try {
    const data=await api(`/api/model-run-comparison/cases/${encodeURIComponent(issueId)}/inputs?${params}`);
    if(seq!==comparisonCaseRequest || !$('#comparisonReasonDialog').open) return;
    const a=data.baseline,b=data.candidate;
    const extraTarget = $('#comparisonDialogExtraInputs');
    extraTarget.innerHTML = comparisonExtraInputsHtml({baseline:a?.extra_inputs,candidate:b?.extra_inputs}, {dialog:true});
    extraTarget.hidden = !extraTarget.innerHTML;
    const sceneTarget = $('#comparisonDialogSceneTags');
    sceneTarget.innerHTML = comparisonSceneTagsHtml(data.scene_review);
    sceneTarget.hidden = !sceneTarget.innerHTML;
    if (payload.view_mode === 'single') {
      const selected = b || a;
      const runLabel = payload.candidate_run ? '新 Run' : '基线 Run';
      target.innerHTML=`<section data-case-content="prompt"><h3>${runLabel} Prompt</h3><div class="prompt-meta">${comparisonPromptMeta(selected.prompt)}</div><pre>${escapeHtml(selected.prompt?.text || '未保存')}</pre><details><summary>Run 模板／示例参考（不是该 Case 实际输入）</summary>${comparisonSnapshotHtml(selected.run_reference)}</details></section><section data-case-content="config" hidden><p>逐 Case 配置：${selected.input.available ? '实际输入' : '未保存'}</p><pre>${escapeHtml(selected.input.available ? comparisonConfigText(selected.input.config) : '未保存')}</pre><h4>已记录媒体 · 顺序与时间点</h4><p>${escapeHtml(selected.media.notice)}</p><pre>${escapeHtml(selected.media.available ? comparisonConfigText({count:selected.media.count,items:selected.media.items}) : '未保存')}</pre></section>`;
      selectComparisonCaseTab($('#comparisonReasonDialog').dataset.tab || 'output');
      return;
    }
    target.innerHTML=`<section data-case-content="prompt"><h3>Prompt 对比</h3><div class="comparison-original"><div class="prompt-meta">${comparisonPromptMeta(a.prompt)}</div><div class="prompt-meta">${comparisonPromptMeta(b.prompt)}</div></div><div data-case-prompt></div><details><summary>Run 模板／示例参考（不是该 Case 实际输入）</summary><div class="comparison-original"><div class="prompt-meta">${comparisonPromptMeta(a.run_reference.prompt)}</div><div class="prompt-meta">${comparisonPromptMeta(b.run_reference.prompt)}</div></div><div data-case-reference></div></details></section><section data-case-content="config" hidden><p>逐 Case 配置：基线 ${a.input.available ? '实际输入' : '未保存'} · 新 Run ${b.input.available ? '实际输入' : '未保存'}</p><div data-case-config></div><h4>已记录媒体 · 顺序与时间点</h4><p>${escapeHtml(a.media.notice)}</p><div data-case-media></div><details><summary>Run 输入配置参考</summary><div data-case-config-reference></div></details></section>`;
    mountComparisonDiff(target.querySelector('[data-case-prompt]'),a.prompt.text,b.prompt.text);
    mountComparisonDiff(target.querySelector('[data-case-reference]'),a.run_reference.prompt.template,b.run_reference.prompt.template);
    mountComparisonDiff(target.querySelector('[data-case-config]'),a.input.available ? comparisonConfigText(a.input.config) : '',b.input.available ? comparisonConfigText(b.input.config) : '');
    mountComparisonDiff(target.querySelector('[data-case-media]'),a.media.available ? comparisonConfigText({count:a.media.count,items:a.media.items}) : '',b.media.available ? comparisonConfigText({count:b.media.count,items:b.media.items}) : '');
    mountComparisonDiff(target.querySelector('[data-case-config-reference]'),a.run_reference.input.available ? comparisonConfigText(a.run_reference.input.config) : '',b.run_reference.input.available ? comparisonConfigText(b.run_reference.input.config) : '');
    selectComparisonCaseTab($('#comparisonReasonDialog').dataset.tab || 'output');
  } catch(error) {if(seq===comparisonCaseRequest) target.textContent=`输入读取失败：${error.message}`;}
}
function selectComparisonCaseTab(tab) {
  const dialog=$('#comparisonReasonDialog'); dialog.dataset.tab=tab;
  dialog.querySelector('.comparison-reason-grid').hidden=tab!=='output';
  $('#comparisonCaseInputs').hidden=false;
  $('#comparisonCaseEvidence').hidden=tab!=='output';
  dialog.querySelectorAll('[data-case-content]').forEach(el => el.hidden=el.dataset.caseContent!==(tab==='output' ? 'prompt' : tab));
  dialog.querySelectorAll('[data-case-tab]').forEach(el=>el.setAttribute('aria-selected',String(el.dataset.caseTab===tab)));
}

let comparisonPreviewSeq = 0;
async function loadComparisonImagePreviews(issueId) {
  const seq = ++comparisonPreviewSeq;
  const camera = $('#comparisonCaseCameraImage'); camera.removeAttribute('src'); camera.hidden = true;
  camera.parentElement.classList.add('is-missing');
  $('#comparisonCaseCameraTime').textContent = 'Camera · 加载中…';
  $('#comparisonCaseBevTime').textContent = 'BEV · 时间读取中…';
  try {
    const data = await comparisonImageMedia(issueId);
    if (seq !== comparisonPreviewSeq || $('#comparisonReasonDialog').dataset.issueId !== issueId) return;
    for (const [prefix, frames] of [['Bev',data.assets?.frames || []],['Camera',data.camera?.frames || []]]) {
      const frame = frames[heroFrameIndex(frames)];
      const label = $(`#comparisonCase${prefix}Time`);
      if (!frame) {label.textContent = `${prefix === 'Bev' ? 'BEV' : 'Camera'} · 未保存`;continue;}
      const ms = mediaFrameOffsetMs(frame);
      label.textContent = `${prefix === 'Bev' ? 'BEV' : 'Camera'} · ${Number.isFinite(ms) ? `t = ${ms/1000}s${ms === 0 ? '' : '（最近帧）'}` : '时间未保存'}`;
      if (prefix === 'Camera') {
        const url = safeSameOriginAssetUrl(frame.url);
        if (url) {camera.src=url;camera.hidden=false;camera.parentElement.classList.remove('is-missing');}
      }
    }
  } catch (_) { if (seq === comparisonPreviewSeq) $('#comparisonCaseCameraTime').textContent = 'Camera · 加载失败'; }
}
