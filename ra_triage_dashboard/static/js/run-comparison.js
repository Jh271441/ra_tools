/* Admin-only immutable Model Run comparison. */

const RUN_TRANSITIONS = ["ALL", "P2F", "F2P", "F2F", "P2P"];

function comparisonRunOptionLabel(run) {
  const name = String(run?.name || run?.source_name || run?.id || "未命名 Run");
  const shortId = String(run?.id || "").slice(0, 8);
  const createdAt = typeof formatTime === "function"
    ? formatTime(run?.created_at)
    : String(run?.created_at || "");
  return [name, shortId, createdAt].filter(Boolean).join(" · ");
}

function comparisonRunOptionHtml(run) {
  return `<option value="${escapeHtml(String(run.id || ""))}">${escapeHtml(comparisonRunOptionLabel(run))}</option>`;
}

function normalizeComparisonRunSelection() {
  const available = (state.modelRuns || []).filter((run) => run?.id);
  const ids = new Set(available.map((run) => String(run.id)));
  if (!ids.has(String(state.runComparison.baselineRunId || ""))) {
    state.runComparison.baselineRunId = available[1]?.id || available[0]?.id || "";
  }
  if (!ids.has(String(state.runComparison.candidateRunId || ""))) {
    state.runComparison.candidateRunId = available[0]?.id || available[1]?.id || "";
  }
  if (
    state.runComparison.baselineRunId === state.runComparison.candidateRunId &&
    available.length > 1
  ) {
    state.runComparison.baselineRunId = String(available[1].id);
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
    state.runComparison.baselineRunId !== state.runComparison.candidateRunId
  );
  if ($("#comparisonLoadButton")) $("#comparisonLoadButton").disabled = !valid || state.runComparison.loading;
  if ($("#comparisonSelectionNote")) {
    $("#comparisonSelectionNote").textContent = (state.modelRuns || []).length < 2
      ? uiText("至少需要两个 Run；请先导入或完成批次预测。", "At least two Runs are required.")
      : valid
        ? uiText("比较只读，不会修改任何 Review 或 Run。", "Comparison is read-only.")
        : uiText("请选择两个不同的 Run。", "Choose two different Runs.");
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
  return `<div class="comparison-prediction ${prediction?.correct ? "is-correct" : "is-error"}">
    <div class="comparison-prediction-output"><strong>${escapeHtml(label)}</strong>${confidence == null ? "" : `<span>${Number(confidence).toFixed(3)}</span>`}<small class="comparison-prediction-verdict">${escapeHtml(verdict)}</small></div>
    <span class="comparison-prediction-reason" title="${escapeHtml(prediction?.model_reason || "")}">${escapeHtml(prediction?.model_reason || uiText("无 reason", "No reason"))}</span>
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
  $(`#comparisonReason${prefix}Body`).textContent = prediction?.model_reason || uiText("该输出没有 Reason。", "This output has no reason.");
}

function openComparisonReasonDialog(issueId) {
  const payload = state.runComparison.data;
  const item = (payload?.items || []).find((entry) => String(entry.issue_id) === String(issueId));
  if (!item) return;
  const dialog = $("#comparisonReasonDialog");
  $("#comparisonReasonTitle").textContent = `${item.issue_id} · ${uiText("Reason 对比", "Reason comparison")}`;
  $("#comparisonReasonContext").textContent = `${uiText("GT", "GT")} ${item.gt_label || "—"} · ${comparisonTransitionText(item.transition)}`;
  renderComparisonReasonSide("Baseline", item.baseline, payload?.baseline_run);
  renderComparisonReasonSide("Candidate", item.candidate, payload?.candidate_run);
  if (dialog && !dialog.open) dialog.showModal();
}

function renderRunComparisonCases(payload) {
  const baselineRunId = payload.baseline_run?.id || "";
  const candidateRunId = payload.candidate_run?.id || "";
  const rows = (payload.items || []).map((item) => {
    const rowLabel = uiText(
      `打开 ${item.issue_id} 的双 Run Reason 对比`,
      `Open the two-Run reason comparison for ${item.issue_id}`,
    );
    return `<tr class="transition-${escapeHtml(String(item.transition || "").toLowerCase())}" data-comparison-row data-issue-id="${escapeHtml(item.issue_id)}" tabindex="0" aria-label="${escapeHtml(rowLabel)}">
      <td><a class="comparison-issue-link" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, candidateRunId))}">${escapeHtml(item.issue_id)}</a><div class="comparison-issue-meta"><span class="status-pill status-ready">GT ${escapeHtml(item.gt_label)}</span><small>${escapeHtml(item.baseline_scope || "")}</small></div></td>
      <td>${comparisonPredictionHtml(item.baseline)}</td>
      <td>${comparisonPredictionHtml(item.candidate)}</td>
      <td><div class="comparison-transition-cell"><span class="comparison-transition-badge ${escapeHtml(String(item.transition || "").toLowerCase())}">${escapeHtml(comparisonTransitionText(item.transition))}</span><small>${uiText("点击整行对比 Reason", "Click row to compare reasons")}</small></div></td>
      <td><div class="comparison-review-links"><a class="button button-quiet" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, baselineRunId))}">${uiText("基线复核", "Baseline review")}</a><a class="button button-quiet" href="${escapeHtml(runComparisonReviewUrl(item.issue_id, candidateRunId))}">${uiText("新 Run 复核", "Candidate review")}</a></div></td>
    </tr>`;
  }).join("");
  $("#comparisonCaseRows").innerHTML = rows || `<tr><td colspan="5" class="comparison-no-rows">${uiText("当前条件下没有 Case。", "No cases match the current filters.")}</td></tr>`;
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
  $("#comparisonBaselineSnapshot .comparison-snapshot-body").innerHTML = comparisonSnapshotHtml(payload.baseline_run);
  $("#comparisonCandidateSnapshot .comparison-snapshot-body").innerHTML = comparisonSnapshotHtml(payload.candidate_run);
  renderRunComparisonCases(payload);
}

async function loadRunComparison({ historyMode = "replace" } = {}) {
  if (!state.session.is_admin) throw new Error(uiText("Run 对比仅限管理员。", "Run comparison is admin-only."));
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
