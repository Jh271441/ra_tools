/* ra_triage_dashboard/static/js/routing.js
 * Theme, i18n, comparison filters, SPA routing
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

function normalizedColorTheme(value) {
  return String(value || "").toLowerCase() === "light" ? "light" : "dark";
}

function applyColorTheme(theme, { persist = true } = {}) {
  state.colorTheme = normalizedColorTheme(theme);
  document.documentElement.dataset.colorTheme = state.colorTheme;
  if (persist) localStorage.setItem("ra-triage-color-theme", state.colorTheme);
  const toggle = $("#themeToggleButton");
  if (!toggle) return;
  const light = state.colorTheme === "light";
  toggle.textContent = light ? "☾" : "☀";
  toggle.setAttribute("aria-label", light ? "切换到深色模式" : "切换到浅色模式");
  toggle.title = light ? "切换到深色模式" : "切换到浅色模式";
}

function normalizedUiLanguage(value) {
  return String(value || "").toLowerCase() === "en" ? "en" : "zh";
}

function uiText(zh, en) {
  return state.uiLanguage === "en" ? en : zh;
}

function renderPageChrome() {
  const route = PAGE_ROUTES[state.activePage] || PAGE_ROUTES.review;
  const title = state.uiLanguage === "en" ? route.titleEn : route.titleZh;
  $("#pageTitle").textContent = title;
  document.title = `${title} · Manual Triage`;
}

function applyUiLanguage(language, { persist = true } = {}) {
  state.uiLanguage = normalizedUiLanguage(language);
  document.documentElement.dataset.uiLang = state.uiLanguage;
  document.documentElement.lang = state.uiLanguage === "en" ? "en" : "zh-CN";
  if (persist) localStorage.setItem("ra-triage-ui-language", state.uiLanguage);
  const toggle = $("#languageToggleButton");
  if (toggle) {
    const english = state.uiLanguage === "en";
    toggle.textContent = english ? "中文" : "EN";
    toggle.setAttribute("aria-label", english ? "切换到中文" : "切换到 English");
    toggle.title = english ? "切换到中文" : "Switch to English";
  }
  renderPageChrome();
  renderSystemStatus();
  applySidebarState();
  renderSession();
}

function normalizedAnalysisComparisonStatus(value, fallback = "all") {
  const normalized = String(value || "").trim().toLowerCase();
  return ANALYSIS_COMPARISON_STATUSES.includes(normalized) ? normalized : fallback;
}

function normalizedReviewComparisonStatus(value, fallback = "all") {
  const normalized = String(value || "").trim().toLowerCase();
  return REVIEW_COMPARISON_STATUSES.includes(normalized) ? normalized : fallback;
}

function setReviewComparisonStatus(
  comparisonStatus,
  { hasRun = Boolean($("#modelRunFilter")?.value) } = {}
) {
  let nextStatus = normalizedReviewComparisonStatus(comparisonStatus);
  if (!hasRun && nextStatus !== "all") nextStatus = "all";
  state.reviewComparisonStatus = nextStatus;
  state.failureOnly = nextStatus === "mismatch";
  const select = $("#comparisonFilter");
  if (select) {
    select.disabled = !hasRun;
    select.value = nextStatus;
  }
  return nextStatus;
}

function selectedReviewComparisonStatus() {
  const runId = $("#modelRunFilter")?.value || state.selectedRunId;
  const status = normalizedReviewComparisonStatus(
    $("#comparisonFilter")?.value,
    state.reviewComparisonStatus || (state.failureOnly ? "mismatch" : "all")
  );
  return runId ? status : "all";
}

function routeReviewComparisonStatus(params) {
  const requested = String(params.get("comparison") || "").trim().toLowerCase();
  if (REVIEW_COMPARISON_STATUSES.includes(requested)) return requested;
  if (params.get("failure") === "1") return "mismatch";
  return params.has("run") ? "all" : null;
}

function routeAnalysisComparisonStatus(params) {
  const requested = String(params.get("comparison") || "").trim().toLowerCase();
  if (ANALYSIS_COMPARISON_STATUSES.includes(requested)) return requested;
  if (params.get("failure") === "1") return "mismatch";
  return params.has("run") ? "all" : null;
}

function normalizedReviewRouteFilters(params) {
  const gtLabel = params.get("gt") || "";
  const modelLabel = params.get("model_label") || params.get("annotation") || "";
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10
  );
  return {
    search: params.get("q") || "",
    gtLabel: LABELS.includes(gtLabel) ? gtLabel : "",
    modelLabel: LABELS.includes(modelLabel) ? modelLabel : "",
    annotationAuthor: params.get("reviewer") || "",
    workAssignee: params.get("work_assignee") || params.get("assignee") || "",
    clusterKey: params.get("evidence") || "",
    casePage: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    casePageSize: CASE_PAGE_SIZES.includes(rawPageSize)
      ? rawPageSize
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

function normalizedAnalysisRouteFilters(params) {
  const reviewStatus = params.get("status") || "";
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const modelLabel = params.get("model_label") || params.get("annotation") || "";
  return {
    search: params.get("q") || "",
    gtLabel: LABELS.includes(params.get("gt")) ? params.get("gt") : "",
    modelLabel: LABELS.includes(modelLabel) ? modelLabel : "",
    annotationAuthor: params.get("reviewer") || "",
    reviewStatus: ["pending", "reviewed", "needs_gt_review"].includes(reviewStatus)
      ? reviewStatus
      : "",
    missingEvidence: params.get("evidence") || "",
    sceneTag: params.get("scene_tag") || "",
    triggerTag: params.get("trigger_tag") || "",
    egressTag: params.get("egress_tag") || "",
    legacyTag: params.get("tag") || "",
    comparisonStatus: routeAnalysisComparisonStatus(params),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
  };
}

function parsePageRoute() {
  const pathname = stripBasePath(window.location.pathname);
  const match = Object.entries(PAGE_ROUTES).find(([, config]) => config.path === pathname);
  const params = new URLSearchParams(window.location.search);
  const legacyHash = decodeURIComponent(window.location.hash.slice(1));
  const issueIds = params
    .getAll("issue")
    .filter((issueId) => /^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const legacyImport = pathname === "/import";
  const reviewFilters = normalizedReviewRouteFilters(params);
  return {
    page:
      match?.[0] ||
      (pathname === "/inference"
        ? "prediction"
        : legacyImport
          ? "runs"
          : "review"),
    issue:
      issueIds[0] ||
      (/^[A-Za-z0-9_-]{3,128}$/.test(legacyHash) ? legacyHash : ""),
    issues: issueIds,
    source: params.get("source") || "",
    runId: params.get("run") || "",
    comparisonStatus: routeReviewComparisonStatus(params),
    failureOnly: params.has("failure") ? params.get("failure") === "1" : params.has("run") ? false : null,
    ...reviewFilters,
    analysisFilters: normalizedAnalysisRouteFilters(params),
    // Issue / GT 上传已从页面移除；旧链接统一落到安全的模型结果导入区。
    importKind:
      params.get("import") === "model" ||
      params.get("kind") === "model" ||
      params.has("import") ||
      params.has("kind") ||
      legacyImport
        ? "model"
        : "",
    legacyRoute: legacyImport || pathname === "/inference" || Boolean(legacyHash),
  };
}

function currentReviewRouteOptions(overrides = {}) {
  return {
    issue: state.selectedId,
    runId: state.selectedRunId,
    comparisonStatus: state.reviewComparisonStatus,
    failureOnly: state.failureOnly,
    search: $("#searchInput")?.value.trim() || "",
    gtLabel: $("#gtFilter")?.value || "",
    modelLabel: $("#annotationFilter")?.value || "",
    annotationAuthor: $("#reviewerFilter")?.value || "",
    workAssignee: $("#workAssigneeFilter")?.value || "",
    clusterKey: state.clusterKey,
    casePage: state.casePage,
    casePageSize: state.casePageSize,
    ...overrides,
  };
}

function applyReviewRouteControls(route) {
  if (!route) return;
  if ($("#searchInput")) $("#searchInput").value = route.search || "";
  if ($("#gtFilter")) $("#gtFilter").value = LABELS.includes(route.gtLabel) ? route.gtLabel : "";
  if ($("#annotationFilter")) {
    $("#annotationFilter").value = LABELS.includes(route.modelLabel)
      ? route.modelLabel
      : "";
  }
  if ($("#workAssigneeFilter")) {
    const assignee = route.workAssignee || "";
    $("#workAssigneeFilter").value =
      !assignee ||
      [...$("#workAssigneeFilter").options].some((option) => option.value === assignee)
        ? assignee
        : "";
  }
  if ($("#reviewerFilter")) {
    const reviewer = route.annotationAuthor || "";
    $("#reviewerFilter").value =
      !reviewer || [...$("#reviewerFilter").options].some((option) => option.value === reviewer)
        ? reviewer
        : "";
  }
  state.clusterKey = route.clusterKey || "";
  state.casePage = Math.max(1, Number(route.casePage) || 1);
  state.casePageSize = CASE_PAGE_SIZES.includes(Number(route.casePageSize))
    ? Number(route.casePageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  if ($("#casePageSize")) $("#casePageSize").value = String(state.casePageSize);
  if (route.comparisonStatus !== null && route.comparisonStatus !== undefined) {
    state.reviewComparisonStatus = normalizedReviewComparisonStatus(
      route.comparisonStatus,
      state.reviewComparisonStatus || "all"
    );
  }
  if (state.selectedRunId) {
    setReviewComparisonStatus(state.reviewComparisonStatus, { hasRun: true });
  } else {
    state.failureOnly = state.reviewComparisonStatus === "mismatch";
    const select = $("#comparisonFilter");
    if (select) {
      select.disabled = true;
      select.value = "all";
    }
  }
}

function currentAnalysisRouteOptions(overrides = {}) {
  return {
    runId: state.selectedRunId,
    comparisonStatus: state.reviewAnalysis.comparisonStatus,
    search: $("#analysisSearchInput")?.value.trim() || "",
    gtLabel: $("#analysisGtFilter")?.value || "",
    modelLabel: $("#analysisModelLabelFilter")?.value || "",
    annotationAuthor: $("#analysisReviewerFilter")?.value || "",
    reviewStatus: $("#analysisStatusFilter")?.value || "",
    missingEvidence: $("#analysisEvidenceFilter")?.value || "",
    sceneTag: $("#analysisSceneFilter")?.value || "",
    triggerTag: $("#analysisTriggerFilter")?.value || "",
    egressTag: $("#analysisEgressFilter")?.value || "",
    page: state.reviewAnalysis.page,
    ...overrides,
  };
}

function applyAnalysisRouteControls(route) {
  const filters = route?.analysisFilters || route || {};
  if ($("#analysisSearchInput")) $("#analysisSearchInput").value = filters.search || "";
  if ($("#analysisGtFilter")) {
    $("#analysisGtFilter").value = LABELS.includes(filters.gtLabel) ? filters.gtLabel : "";
  }
  if ($("#analysisModelLabelFilter")) {
    $("#analysisModelLabelFilter").value = LABELS.includes(filters.modelLabel)
      ? filters.modelLabel
      : "";
  }
  if ($("#analysisStatusFilter")) $("#analysisStatusFilter").value = filters.reviewStatus || "";
  if ($("#analysisReviewerFilter")) {
    const reviewer = filters.annotationAuthor || "";
    $("#analysisReviewerFilter").value =
      !reviewer ||
      [...$("#analysisReviewerFilter").options].some((option) => option.value === reviewer)
        ? reviewer
        : "";
  }
  if ($("#analysisEvidenceFilter")) {
    const evidence = filters.missingEvidence || "";
    $("#analysisEvidenceFilter").value =
      !evidence ||
      [...$("#analysisEvidenceFilter").options].some((option) => option.value === evidence)
        ? evidence
        : "";
  }
  const catalog = state.config?.review_tag_catalog || [];
  const legacyTag = filters.legacyTag || "";
  const legacyItem = catalog.find((item) => item.key === legacyTag);
  const sceneTag = filters.sceneTag || (legacyItem?.section === "scene" ? legacyTag : "");
  const triggerTag = filters.triggerTag || (legacyItem?.section === "interaction_decision" ? legacyTag : "");
  const egressTag = filters.egressTag || (legacyItem?.section === "egress" ? legacyTag : "");
  [
    ["#analysisSceneFilter", sceneTag],
    ["#analysisTriggerFilter", triggerTag],
    ["#analysisEgressFilter", egressTag],
  ].forEach(([selector, value]) => {
    const select = $(selector);
    if (!select) return;
    select.value = !value || [...select.options].some((option) => option.value === value)
      ? value
      : "";
  });
  const requestedComparison =
    filters.comparisonStatus ||
    (state.failureOnly && state.selectedRunId
      ? "mismatch"
      : state.reviewAnalysis.comparisonStatus);
  setAnalysisComparisonStatus(requestedComparison, {
    hasRun: Boolean($("#analysisRunFilter")?.value),
  });
  state.reviewAnalysis.page = Math.max(1, Number(filters.page) || 1);
}

function pageUrl(page, options = {}) {
  const config = PAGE_ROUTES[page] || PAGE_ROUTES.review;
  const url = new URL(withBase(config.path), window.location.origin);
  if (page === "review") {
    const review = currentReviewRouteOptions(options);
    const issueId = review.issue;
    const runId = review.runId;
    const comparisonStatus = normalizedReviewComparisonStatus(
      review.comparisonStatus,
      review.failureOnly ? "mismatch" : "all"
    );
    if (issueId) url.searchParams.set("issue", issueId);
    if (runId) url.searchParams.set("run", runId);
    if (runId) url.searchParams.set("comparison", runId ? comparisonStatus : "all");
    if (review.search) url.searchParams.set("q", review.search);
    if (review.gtLabel) url.searchParams.set("gt", review.gtLabel);
    if (review.modelLabel) url.searchParams.set("model_label", review.modelLabel);
    if (review.annotationAuthor) url.searchParams.set("reviewer", review.annotationAuthor);
    if (review.workAssignee) url.searchParams.set("work_assignee", review.workAssignee);
    if (review.clusterKey) url.searchParams.set("evidence", review.clusterKey);
    if (Number(review.casePage) > 1) url.searchParams.set("page", String(review.casePage));
    if (Number(review.casePageSize) !== DEFAULT_CASE_PAGE_SIZE) {
      url.searchParams.set("page_size", String(review.casePageSize));
    }
  }
  if (page === "analysis") {
    const analysis = currentAnalysisRouteOptions(options);
    url.searchParams.set("run", analysis.runId || "none");
    url.searchParams.set(
      "comparison",
      analysis.runId
        ? normalizedAnalysisComparisonStatus(analysis.comparisonStatus)
        : "all"
    );
    if (analysis.search) url.searchParams.set("q", analysis.search);
    if (analysis.gtLabel) url.searchParams.set("gt", analysis.gtLabel);
    if (analysis.modelLabel) url.searchParams.set("model_label", analysis.modelLabel);
    if (analysis.annotationAuthor) url.searchParams.set("reviewer", analysis.annotationAuthor);
    if (analysis.reviewStatus) url.searchParams.set("status", analysis.reviewStatus);
    if (analysis.missingEvidence) url.searchParams.set("evidence", analysis.missingEvidence);
    if (analysis.sceneTag) url.searchParams.set("scene_tag", analysis.sceneTag);
    if (analysis.triggerTag) url.searchParams.set("trigger_tag", analysis.triggerTag);
    if (analysis.egressTag) url.searchParams.set("egress_tag", analysis.egressTag);
    if (Number(analysis.page) > 1) url.searchParams.set("page", String(analysis.page));
  }
  if (page === "prediction") {
    const issueIds = options.issues ?? (options.issue ? [options.issue] : []);
    [...new Set(issueIds)].forEach((issueId) => {
      if (/^[A-Za-z0-9_-]{3,128}$/.test(issueId)) url.searchParams.append("issue", issueId);
    });
    if (options.source) url.searchParams.set("source", options.source);
  }
  if (page === "runs" && options.importKind) {
    url.searchParams.set("import", "model");
  }
  return `${url.pathname}${url.search}`;
}

function setReviewView(issueId = "") {
  const gallery = $("#reviewGalleryView");
  const detail = $("#reviewDetailView");
  if (!gallery || !detail) return;
  const showingDetail = Boolean(issueId);
  gallery.classList.toggle("hidden", showingDetail);
  detail.classList.toggle("hidden", !showingDetail);
  $("#reviewPage")?.classList.toggle("is-detail", showingDetail);
  if (!showingDetail) {
    $("#detailHeroMedia")?.querySelector("video")?.pause();
    closeDialog("mediaDialog");
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: state.galleryScrollY, behavior: "auto" });
    });
  }
}

function showPage(
  page,
  {
    historyMode = "",
    issue = "",
    issues = [],
    source = "",
    importKind = "",
    runSourceTab = "",
    restoreRoute = false,
    loadPageData = true,
  } = {}
) {
  const target = PAGE_ROUTES[page] ? page : "review";
  if (target !== "review") $("#detailHeroMedia")?.querySelector("video")?.pause();
  state.activePage = target;
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("hidden", section.dataset.page !== target);
  });
  document.querySelectorAll(".sidebar-item[data-page-target]").forEach((item) => {
    const active = item.dataset.pageTarget === target;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  renderPageChrome();
  if (target === "runs") {
    renderRunManager();
    if (importKind) setImportKind(importKind);
    else activateRunSourceTab(runSourceTab || "upload");
  }
  if (target === "prediction") {
    const issueIds = issues.length ? issues : issue ? [issue] : [];
    ensurePredictionBatchName();
    const issueInput = $("#predictionBatchIssues");
    if (issueInput && (issueIds.length || restoreRoute)) {
      issueInput.value = [...new Set(issueIds)].join(", ");
    }
    if (issueIds.length) {
      state.batchDraftSource = source || (issueIds.length === 1 ? "single" : "");
    } else if (restoreRoute) {
      state.batchDraftSource = "";
    }
    renderPredictionSourceSummary();
    updatePredictionBatchCount();
    renderBatchRuntimeSummary();
    if (loadPageData) {
      loadPredictionConfig().catch((error) => showToast(error.message, true));
      loadPredictionBatches().catch((error) => showToast(error.message, true));
    }
  }
  if (target === "analysis") renderAnalysisRunFilter();
  if (target === "status" && loadPageData) {
    loadStatus().catch((error) => showToast(error.message, true));
  }
  if (target === "users" && loadPageData) {
    loadAccessUsers().catch((error) => showToast(error.message, true));
  }
  if (target === "review") setReviewView(issue);
  const routeOptions =
    target === "review"
      ? currentReviewRouteOptions({ issue })
      : target === "analysis"
        ? currentAnalysisRouteOptions()
        : { issue, issues, source, importKind };
  const historyState = {
    page: target,
    issue: target === "review" ? issue : "",
    openedFromGallery:
      target === "review" &&
      Boolean(issue) &&
      (historyMode === "push" || Boolean(window.history.state?.openedFromGallery)),
  };
  if (historyMode === "push") {
    history.pushState(historyState, "", pageUrl(target, routeOptions));
  }
  if (historyMode === "replace") {
    history.replaceState(historyState, "", pageUrl(target, routeOptions));
  }
  if (target !== "review" || issue) {
    window.scrollTo({ top: 0, behavior: historyMode === "push" ? "smooth" : "auto" });
  }
}

function navigatePage(page, options = {}) {
  const previousPage = state.activePage;
  const restoreRoute =
    page === "prediction" &&
    !options.issue &&
    !(Array.isArray(options.issues) && options.issues.length);
  if (page === "review" && previousPage === "analysis" && state.reviewQueueStale) {
    state.casePage = 1;
  }
  showPage(page, { ...options, restoreRoute, historyMode: "push" });
  if (page === "analysis" && state.config) {
    loadReviewReasonAnalysis().catch((error) => showToast(error.message, true));
  }
  if (page === "review" && previousPage === "analysis" && state.reviewQueueStale) {
    reloadReviewGallery({ includeOverview: false, historyMode: "" }).catch((error) =>
      showToast(error.message, true)
    );
  }
}

