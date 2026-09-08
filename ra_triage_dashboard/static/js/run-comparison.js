/* Admin-only immutable Model Run comparison. */

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

function comparisonRunOptionHtml(run) {
  return `<option value="${escapeHtml(String(run.id || ""))}">${escapeHtml(comparisonRunOptionLabel(run))}</option>`;
}

function normalizeComparisonRunSelection() {
  const available = (state.modelRuns || []).filter((run) => run?.id);
  const covered = available.filter((run) => Number(run.baseline_prediction_count || 0) > 0);
  const ids = new Set(available.map((run) => String(run.id)));
  if (!ids.has(String(state.runComparison.baselineRunId || ""))) {
    state.runComparison.baselineRunId = covered[1]?.id || covered[0]?.id || available[1]?.id || available[0]?.id || "";
  }
  if (!ids.has(String(state.runComparison.candidateRunId || ""))) {
    state.runComparison.candidateRunId = covered[0]?.id || available[0]?.id || available[1]?.id || "";
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
  if (selectedCoverage <= 0 && covered.length) {
    state.runComparison.candidateRunId = String(covered[0].id);
    state.runComparison.baselineRunId = String(
      covered[1]?.id
        || available.find((run) => String(run.id) !== String(covered[0].id))?.id
        || ""
    );
  }
}

function renderRunComparisonSelectors() {
  normalizeComparisonRunSelection();
  const options = (state.modelRuns || []).map(comparisonRunOptionHtml).join("");
  const empty = `<option value="">${uiText("请选择 Run", "Choose a Run")}</option>`;
  const baseline = $("#comparisonBaselineRun");
  const candidate = $("#comparisonCandidateRun");
  if (baseline) {
    baseline.innerHTML = empty + options;
    baseline.value = state.runComparison.baselineRunId || "";
  }
  if (candidate) {
    candidate.innerHTML = empty + options;
    candidate.value = state.runComparison.candidateRunId || "";
  }
  const valid = Boolean(
    state.runComparison.baselineRunId &&
    state.runComparison.candidateRunId &&
    state.runComparison.baselineRunId !== state.runComparison.candidateRunId &&
    [state.runComparison.baselineRunId, state.runComparison.candidateRunId]
      .map((runId) => (state.modelRuns || []).find((run) => String(run.id) === String(runId)))
      .some((run) => Number(run?.baseline_prediction_count || 0) > 0)
  );
  if ($("#comparisonLoadButton")) $("#comparisonLoadButton").disabled = !valid || state.runComparison.loading;
  if ($("#comparisonSelectionNote")) {
    const selectedRuns = [state.runComparison.baselineRunId, state.runComparison.candidateRunId]
      .map((runId) => (state.modelRuns || []).find((run) => String(run.id) === String(runId)))
      .filter(Boolean);
    const oneSideMissing = selectedRuns.length === 2 && selectedRuns.some(
      (run) => Number(run.baseline_prediction_count || 0) <= 0
    );
    $("#comparisonSelectionNote").textContent = (state.modelRuns || []).length < 2
      ? uiText("至少需要两个 Run；请先导入或完成批次预测。", "At least two Runs are required.")
      : valid
        ? oneSideMissing
          ? uiText("按并集比较；无当前数据集输出的一侧将显示为 NONE。", "Union comparison; the uncovered side is shown as NONE.")
          : uiText("比较只读，不会修改任何 Review 或 Run。", "Comparison is read-only.")
        : uiText("请选择两个不同的 Run，且至少一侧覆盖当前数据集。", "Choose two different Runs with coverage on at least one side.");
  }
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
  renderRunComparisonSelectors();
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

function comparisonPredictionHtml(prediction) {
  const label = prediction?.model_label || "NONE";
  const confidence = prediction?.model_confidence;
  const verdict = prediction?.correct ? uiText("匹配 GT", "Matches GT") : uiText("不匹配 GT", "Differs from GT");
  const reason = prediction?.model_reason || uiText("未保存／未生成 Reason", "Reason not saved / generated");
  return `<div class="comparison-prediction ${prediction?.correct ? "is-correct" : "is-error"}">
    <div class="comparison-prediction-output"><strong class="comparison-output-label">${escapeHtml(label)}</strong>${confidence == null ? "" : `<span class="comparison-prediction-confidence">${Number(confidence).toFixed(3)}</span>`}<small class="comparison-prediction-verdict comparison-chip ${prediction?.correct ? "comparison-match" : "comparison-mismatch"}">${escapeHtml(verdict)}</small></div>
    <span class="comparison-prediction-reason" title="${escapeHtml(reason)}" aria-label="${escapeHtml(reason)}">${escapeHtml(reason)}</span>
  </div>`;
}

function renderComparisonReasonSide(prefix, prediction, run) {
  const confidence = prediction?.model_confidence;
  const verdict = prediction?.correct ? uiText("匹配 GT", "Matches GT") : uiText("不匹配 GT", "Differs from GT");
  $(`#comparisonReason${prefix}Run`).textContent = run?.name || run?.id || "—";
  $(`#comparisonReason${prefix}ModelLabel`).textContent = prediction?.model_label || "NONE";
  $(`#comparisonReason${prefix}Confidence`).textContent = confidence == null ? "—" : Number(confidence).toFixed(3);
  const verdictElement = $(`#comparisonReason${prefix}Verdict`);
  verdictElement.textContent = verdict;
  verdictElement.classList.toggle("is-error", !prediction?.correct);
  $(`#comparisonReason${prefix}Body`).textContent = prediction?.model_reason || uiText("未保存／未生成 Reason", "Reason not saved / generated");
}

function openComparisonReasonDialog(issueId) {
  const payload = state.runComparison.data;
  const item = (payload?.items || []).find((entry) => String(entry.issue_id) === String(issueId));
  if (!item) return;
  const dialog = $("#comparisonReasonDialog");
  $("#comparisonReasonTitle").textContent = `${item.issue_id} · ${uiText("Case 对比", "Case comparison")}`;
  $("#comparisonReasonContext").textContent = `${uiText("GT", "GT")} ${item.gt_label || "—"} · ${comparisonTransitionText(item.transition)}`;
  renderComparisonReasonSide("Baseline", item.baseline, payload?.baseline_run);
  renderComparisonReasonSide("Candidate", item.candidate, payload?.candidate_run);
  dialog.dataset.issueId = String(issueId);
  const preview = $('#comparisonCaseBevImage');
  preview.hidden = false;
  preview.parentElement.classList.remove('is-missing');
  preview.src = withBase(`/api/case-thumbnails/${encodeURIComponent(issueId)}`);
  selectComparisonCaseTab('output');
  if (dialog && !dialog.open) dialog.showModal();
  loadComparisonCaseInputs(issueId, payload);
}

function renderRunComparisonCases(payload) {
  const baselineRunId = payload.baseline_run?.id || "";
  const candidateRunId = payload.candidate_run?.id || "";
  const rows = (payload.items || []).map((item) => {
    const rowLabel = uiText(
      `打开 ${item.issue_id} 的双 Run Case 对比`,
      `Open the two-Run reason comparison for ${item.issue_id}`,
    );
    return `<tr class="transition-${escapeHtml(String(item.transition || "").toLowerCase())}" data-comparison-row data-issue-id="${escapeHtml(item.issue_id)}" tabindex="0" aria-label="${escapeHtml(rowLabel)}">
      <td><a class="comparison-issue-link" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, candidateRunId))}">${escapeHtml(item.issue_id)}</a><div class="comparison-issue-meta"><span class="comparison-gt-summary"><span>GT</span><strong>${escapeHtml(item.gt_label || "—")}</strong></span><small>${escapeHtml(item.baseline_scope || "")}</small></div></td>
      <td><button type="button" class="comparison-bev" data-comparison-media="${escapeHtml(item.issue_id)}" aria-label="打开 ${escapeHtml(item.issue_id)} 参考媒体"><img loading="lazy" src="${escapeHtml(withBase(`/api/case-thumbnails/${encodeURIComponent(item.issue_id)}`))}" alt="BEV 预览"><span>暂无 BEV</span></button></td>
      <td>${comparisonPredictionHtml(item.baseline)}</td>
      <td>${comparisonPredictionHtml(item.candidate)}</td>
      <td><div class="comparison-transition-cell"><span class="comparison-transition-badge ${escapeHtml(String(item.transition || "").toLowerCase())}">${escapeHtml(comparisonTransitionText(item.transition))}</span><small>${uiText("点击整行打开 Case 对比", "Click row to compare reasons")}</small></div></td>
      <td><div class="comparison-review-links"><a class="button button-quiet" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, baselineRunId))}">${uiText("基线复核", "Baseline review")}</a><a class="button button-quiet" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, candidateRunId))}">${uiText("新 Run 复核", "Candidate review")}</a></div></td>
    </tr>`;
  }).join("");
  $("#comparisonCaseRows").innerHTML = rows || `<tr><td colspan="6" class="comparison-no-rows">${uiText("当前条件下没有 Case。", "No cases match the current filters.")}</td></tr>`;
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
  renderRunComparisonSummary(payload);
  renderComparisonMatrix("#comparisonBaselineMatrix", payload.summary.baseline);
  renderComparisonMatrix("#comparisonCandidateMatrix", payload.summary.candidate);
  $("#comparisonBaselineMatrixMeta").textContent = percentage(payload.summary.baseline?.accuracy);
  $("#comparisonCandidateMatrixMeta").textContent = percentage(payload.summary.candidate?.accuracy);
  renderComparisonRunDiff(payload);
  renderRunComparisonCases(payload);
}

async function loadRunComparison({ historyMode = "replace" } = {}) {
  const baselineRunId = String(state.runComparison.baselineRunId || "");
  const candidateRunId = String(state.runComparison.candidateRunId || "");
  if (!baselineRunId || !candidateRunId || baselineRunId === candidateRunId) {
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
  $('#comparisonCaseBev')?.addEventListener('click', () => openCaseMediaPreview($('#comparisonReasonDialog').dataset.issueId, null, true).catch(error => showToast(error.message,true)));
  $('#comparisonCaseBevImage')?.addEventListener('error', event => { event.target.hidden = true; event.target.parentElement.classList.add('is-missing'); });
  $('#comparisonReasonDialog')?.addEventListener('close', () => { comparisonCaseRequest++; });
  document.querySelectorAll('[data-case-tab]').forEach(button => button.addEventListener('click', () => selectComparisonCaseTab(button.dataset.caseTab)));
  $('#comparisonCaseRows')?.addEventListener('click', event => {
    const button=event.target.closest('[data-comparison-media]');
    if(button) openCaseMediaPreview(button.dataset.comparisonMedia, null, true).catch(error => showToast(error.message,true));
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
    state.runComparison.baselineRunId = event.target.value;
    state.runComparison.page = 1;
    renderRunComparisonSelectors();
  });
  $("#comparisonCandidateRun")?.addEventListener("change", (event) => {
    state.runComparison.candidateRunId = event.target.value;
    state.runComparison.page = 1;
    renderRunComparisonSelectors();
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
    state.runComparison.page = 1;
    if ($("#comparisonSearchInput")) $("#comparisonSearchInput").value = "";
    if ($("#comparisonGtFilter")) $("#comparisonGtFilter").value = "ALL";
    if ($("#comparisonBaselineLabelFilter")) $("#comparisonBaselineLabelFilter").value = "ALL";
    if ($("#comparisonCandidateLabelFilter")) $("#comparisonCandidateLabelFilter").value = "ALL";
    if ($("#comparisonLabelChangeFilter")) $("#comparisonLabelChangeFilter").value = "ALL";
    renderRunComparisonTransitionFilter();
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
  target.innerHTML = `<div class="comparison-diff-controls"><label><input type="checkbox" data-diff-full> 完整原文（默认仅看差异）</label><label><input type="checkbox" data-diff-unified> 统一视图（默认并排）</label></div><div class="comparison-diff-body"></div>`;
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
      return `<div class="diff-pair"><div class="diff-line ${r.kind === 'same' ? 'same' : 'delete'}"><small>${r.i || ''}</small><code>${a}</code></div><div class="diff-line ${r.kind === 'same' ? 'same' : 'add'}"><small>${r.j || ''}</small><code>${b}</code></div></div>`;
    };
    let html = '';
    for (let n=0;n<rows.length;) {
      if (rows[n].kind !== 'same') {html += renderRow(rows[n++]); continue;}
      const start = n; while(n<rows.length && rows[n].kind==='same') n++;
      const group = rows.slice(start,n);
      html += group.length > 8 ? group.slice(0,3).map(renderRow).join('') + `<details class="diff-fold"><summary>展开 ${group.length-6} 行相同内容</summary>${group.slice(3,-3).map(renderRow).join('')}</details>` + group.slice(-3).map(renderRow).join('') : group.map(renderRow).join('');
    }
    body.innerHTML = `<p>${escapeHtml(notice)}</p><div class="diff-head"><span>基线</span><span>新 Run</span></div>${html}`;
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
  return [types[prompt?.source_type] || '未保存',prompt?.source,prompt?.version,prompt?.stage,prompt?.sha256 || prompt?.computed_sha256, prompt?.hash_matches === false ? "保存哈希与文本不一致" : "", prompt?.example_case_id ? `示例 Case: ${prompt.example_case_id}` : '',prompt?.redacted ? '展示内容已脱敏' : ''].filter(Boolean).map(escapeHtml).join(' · ');
}
function renderComparisonRunDiff(payload) {
  const target = $('#comparisonRunDiff');
  const a=payload.baseline_run, b=payload.candidate_run;
  target.innerHTML = `<div class="comparison-original"><p>${escapeHtml(a.name)}<br>${comparisonPromptMeta(a.prompt)}</p><p>${escapeHtml(b.name)}<br>${comparisonPromptMeta(b.prompt)}</p></div><h4>Prompt</h4><div data-run-prompt></div><h4>输入配置 · Run 参考</h4><div data-run-config></div>`;
  mountComparisonDiff(target.querySelector('[data-run-prompt]'),a.prompt?.template,b.prompt?.template);
  mountComparisonDiff(target.querySelector('[data-run-config]'),a.input?.available ? comparisonConfigText(a.input.config) : '', b.input?.available ? comparisonConfigText(b.input.config) : '');
}
let comparisonCaseRequest = 0;
async function loadComparisonCaseInputs(issueId,payload) {
  const seq=++comparisonCaseRequest;
  const target=$('#comparisonCaseInputs'); target.textContent='正在读取已保存输入…';
  const params=new URLSearchParams({baseline_run_id:payload.baseline_run.id,candidate_run_id:payload.candidate_run.id,baselines:selectedBaselineQueryValue() || ''});
  try {
    const data=await api(`/api/model-run-comparison/cases/${encodeURIComponent(issueId)}/inputs?${params}`);
    if(seq!==comparisonCaseRequest || !$('#comparisonReasonDialog').open) return;
    const a=data.baseline,b=data.candidate;
    target.innerHTML=`<section data-case-content="prompt"><h3>Prompt 对比</h3><div class="comparison-original"><p>${comparisonPromptMeta(a.prompt)}</p><p>${comparisonPromptMeta(b.prompt)}</p></div><div data-case-prompt></div><details><summary>Run 模板／示例参考（不是该 Case 实际输入）</summary><div class="comparison-original"><p>${comparisonPromptMeta(a.run_reference.prompt)}</p><p>${comparisonPromptMeta(b.run_reference.prompt)}</p></div><div data-case-reference></div></details></section><section data-case-content="config" hidden><p>逐 Case 配置：基线 ${a.input.available ? '实际输入' : '未保存'} · 新 Run ${b.input.available ? '实际输入' : '未保存'}</p><div data-case-config></div><h4>已记录媒体 · 顺序与时间点</h4><p>${escapeHtml(a.media.notice)}</p><div data-case-media></div><details><summary>Run 输入配置参考</summary><div data-case-config-reference></div></details></section>`;
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
  $('#comparisonCaseEvidence').classList.toggle('config-only', tab==='config');
  dialog.querySelectorAll('[data-case-content]').forEach(el => el.hidden=el.dataset.caseContent!==(tab==='output' ? 'prompt' : tab));
  dialog.querySelectorAll('[data-case-tab]').forEach(el=>el.setAttribute('aria-selected',String(el.dataset.caseTab===tab)));
}
