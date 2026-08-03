const LABELS = ["误触发", "正确触发", "无需协助"];
const CASE_PAGE_SIZES = [10, 20, 50, 100];
const DEFAULT_CASE_PAGE_SIZE = 20;
const ANALYSIS_COMPARISON_STATUSES = ["all", "mismatch", "match", "none"];
const ANALYSIS_COMPARISON_META = {
  all: { label: "全部", description: "不按模型判断结果收窄" },
  mismatch: { label: "MISMATCH", description: "GT 与模型输出不一致" },
  match: { label: "MATCH", description: "GT 与模型输出一致" },
  none: { label: "NONE", description: "该 Run 未预测" },
};
const REVIEW_COMPARISON_STATUSES = ANALYSIS_COMPARISON_STATUSES;
const REVIEW_COMPARISON_META = ANALYSIS_COMPARISON_META;

function normalizeClientBasePath(value) {
  const raw = String(value ?? "");
  if (!raw || raw === "/") return "";
  const normalized = raw.endsWith("/") ? raw.slice(0, -1) : raw;
  if (
    normalized.includes("..") ||
    !/^\/(?:[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*)$/.test(normalized)
  ) {
    throw new Error("RA Triage base path 配置非法。");
  }
  return normalized;
}

const CONFIGURED_BASE_PATH = normalizeClientBasePath(
  document.querySelector('meta[name="ra-triage-base"]')?.content || ""
);
const BASE_PATH = normalizeClientBasePath(
  window.__RA_TRIAGE_BASE__ ?? CONFIGURED_BASE_PATH
);

function removeBasePath(path, basePath) {
  if (!basePath) return path;
  if (path === basePath) return "/";
  if (path.startsWith(`${basePath}/`)) return path.slice(basePath.length);
  if (path.startsWith(`${basePath}?`) || path.startsWith(`${basePath}#`)) {
    return `/${path.slice(basePath.length)}`;
  }
  return path;
}

function withBase(path) {
  const value = String(path || "");
  if (/^https?:\/\//i.test(value) || value.startsWith("//")) return value;
  if (!value.startsWith("/")) return value;
  if (
    BASE_PATH &&
    (value === BASE_PATH ||
      value.startsWith(`${BASE_PATH}/`) ||
      value.startsWith(`${BASE_PATH}?`) ||
      value.startsWith(`${BASE_PATH}#`))
  ) {
    return value;
  }
  const logicalPath = removeBasePath(value, CONFIGURED_BASE_PATH);
  if (!BASE_PATH) return logicalPath;
  return `${BASE_PATH}${logicalPath}`;
}

function stripBasePath(pathname) {
  const value = String(pathname || "");
  return removeBasePath(
    removeBasePath(value, BASE_PATH),
    CONFIGURED_BASE_PATH
  );
}

const PAGE_ROUTES = {
  review: {
    path: "/review",
    titleZh: "判错复核",
    titleEn: "Manual Triage Review",
  },
  analysis: {
    path: "/review-analysis",
    titleZh: "原因聚类",
    titleEn: "Review Reason Clusters",
  },
  runs: {
    path: "/runs",
    titleZh: "模型结果",
    titleEn: "Model Runs",
  },
  prediction: {
    path: "/batch-prediction",
    titleZh: "批次预测",
    titleEn: "Batch Model Inference",
  },
  status: {
    path: "/system-status",
    titleZh: "系统状态",
    titleEn: "System Status",
  },
};

const state = {
  config: null,
  cases: [],
  caseTotal: 0,
  casePage: 1,
  casePageSize: DEFAULT_CASE_PAGE_SIZE,
  caseRequestSeq: 0,
  caseListRequestSeq: 0,
  reviewReloadSeq: 0,
  galleryScrollY: 0,
  selectedId: "",
  selectedCase: null,
  modelRuns: [],
  reviewers: [],
  predictionBatches: [],
  predictionBatchTotal: 0,
  predictionBatchDetails: {},
  expandedPredictionBatchId: "",
  predictionRequesters: [],
  batchListRequestSeq: 0,
  batchDefaultModel: null,
  gatewayModels: [],
  gatewayModelStatus: null,
  gatewayModelRequestSeq: 0,
  selectedGatewayModelId: "",
  selectedGatewayProviderId: "",
  batchPrompts: [],
  batchPromptStatus: null,
  batchFacets: {
    models: [],
    prompts: [],
    input_profiles: [],
  },
  batchDraftSource: "",
  batchDefaultName: "",
  selectedRunId: "",
  reviewComparisonStatus: "all",
  failureOnly: false,
  clusterKey: "",
  reviewQueueStale: false,
  reviewAnalysis: {
    page: 1,
    pageSize: 50,
    requestSeq: 0,
    data: null,
    comparisonStatus: "mismatch",
    theme: "",
  },
  selectedAnnotationLabel: "",
  pollingBatchId: "",
  pollTimer: null,
  changeRevision: null,
  changePollEpoch: 0,
  changePollTimer: null,
  changePollInFlight: false,
  reviewFormDirty: false,
  deferredDetailRefresh: false,
  media: {
    kind: "bev",
    index: 0,
    zoom: 1,
    drag: null,
    snapshot: null,
    requestSeq: 0,
    imageRequestSeq: 0,
  },
  detailMedia: {
    issueId: "",
    kind: "",
    indexes: { bev: 0, camera: 0 },
    loadSeq: 0,
  },
  raEventDialog: { issueId: "", events: [], trailUrl: "" },
  sourcePreview: { runId: "", page: 1, pageSize: 100, pageCount: 1 },
  session: {
    username: "",
    source: "anonymous",
    identity_pending: true,
    authenticated: false,
    verified: false,
    can_manage_team_default: false,
    can_write: true,
    read_only: false,
  },
  sidebarCollapsed: false,
  colorTheme: "dark",
  uiLanguage: "zh",
  activePage: "review",
  systemStatus: null,
  trailInspection: null,
  pendingReviewImages: [],
  savingAnnotation: false,
};

const $ = (selector) => document.querySelector(selector);

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
  const annotationLabel = params.get("annotation") || "";
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10
  );
  return {
    search: params.get("q") || "",
    gtLabel: LABELS.includes(gtLabel) ? gtLabel : "",
    annotationLabel: LABELS.includes(annotationLabel) ? annotationLabel : "",
    annotationAuthor: params.get("reviewer") || "",
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
  return {
    search: params.get("q") || "",
    gtLabel: LABELS.includes(params.get("gt")) ? params.get("gt") : "",
    annotationLabel: LABELS.includes(params.get("annotation")) ? params.get("annotation") : "",
    annotationAuthor: params.get("reviewer") || "",
    reviewStatus: ["pending", "reviewed", "needs_gt_review"].includes(reviewStatus)
      ? reviewStatus
      : "",
    missingEvidence: params.get("evidence") || "",
    theme: params.get("theme") || "",
    tag: params.get("tag") || "",
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
    annotationLabel: $("#annotationFilter")?.value || "",
    annotationAuthor: $("#reviewerFilter")?.value || "",
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
    $("#annotationFilter").value = LABELS.includes(route.annotationLabel)
      ? route.annotationLabel
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
    annotationLabel: $("#analysisAnnotationFilter")?.value || "",
    annotationAuthor: $("#analysisReviewerFilter")?.value || "",
    reviewStatus: $("#analysisStatusFilter")?.value || "",
    missingEvidence: $("#analysisEvidenceFilter")?.value || "",
    theme: state.reviewAnalysis.theme || "",
    tag: $("#analysisTagFilter")?.value || "",
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
  if ($("#analysisAnnotationFilter")) {
    $("#analysisAnnotationFilter").value = LABELS.includes(filters.annotationLabel)
      ? filters.annotationLabel
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
  state.reviewAnalysis.theme = filters.theme || "";
  if ($("#analysisTagFilter")) {
    const tag = filters.tag || "";
    $("#analysisTagFilter").value =
      !tag ||
      [...$("#analysisTagFilter").options].some((option) => option.value === tag)
        ? tag
        : "";
  }
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
    if (review.annotationLabel) url.searchParams.set("annotation", review.annotationLabel);
    if (review.annotationAuthor) url.searchParams.set("reviewer", review.annotationAuthor);
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
    if (analysis.annotationLabel) url.searchParams.set("annotation", analysis.annotationLabel);
    if (analysis.annotationAuthor) url.searchParams.set("reviewer", analysis.annotationAuthor);
    if (analysis.reviewStatus) url.searchParams.set("status", analysis.reviewStatus);
    if (analysis.missingEvidence) url.searchParams.set("evidence", analysis.missingEvidence);
    if (analysis.theme) url.searchParams.set("theme", analysis.theme);
    if (analysis.tag) url.searchParams.set("tag", analysis.tag);
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function aresStudioUrl(caseData, issueUrl) {
  const tripId = String(caseData?.assets?.capture?.trip_id || caseData?.trip_id || "").trim();
  const issueId = String(caseData?.issue_id || "").trim();
  const timestampMs = Number(
    caseData?.assets?.capture?.timestamp_ms || caseData?.camera?.capture?.timestamp_ms
  );
  if (!issueUrl || !issueId || !tripId || !Number.isFinite(timestampMs) || timestampMs <= 0) return "";
  try {
    const url = new URL("/static/ares-studio/", issueUrl);
    url.searchParams.set("ds", "voy-ws-car");
    url.searchParams.set("ds.issue_id", issueId);
    url.searchParams.set("ds.trip_id", tripId);
    url.searchParams.set("ds.start", String(Math.round(timestampMs - 10000)));
    url.searchParams.set("ds.end", String(Math.round(timestampMs + 10000)));
    url.searchParams.set("entry_last_page", `/issue/${issueId}`);
    return safeUrl(url.href);
  } catch {
    return "";
  }
}

function safeSameOriginAssetUrl(url) {
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const pathname = stripBasePath(parsed.pathname);
    if (parsed.origin !== window.location.origin || !pathname.startsWith("/api/")) return "";
    return `${withBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

function labelBadge(label, fallback = "—") {
  const actual = label || "";
  const className = LABELS.includes(actual) ? `label-${actual}` : "label-empty";
  return `<span class="label-badge ${className}">${escapeHtml(actual || fallback)}</span>`;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function evidenceLabel(key) {
  const value = String(key || "");
  if (value.startsWith("custom:")) return value.slice("custom:".length) || value;
  return state.config?.missing_evidence_catalog?.find((item) => item.key === value)?.label || value;
}

function tagLabel(key) {
  const value = String(key || "");
  if (value.startsWith("custom:")) return value.slice("custom:".length) || value;
  return state.config?.review_tag_catalog?.find((item) => item.key === value)?.label || value;
}

function frameLabel(frame) {
  if (frame.offset_ms !== undefined && frame.offset_ms !== null) {
    const seconds = Math.round(Number(frame.offset_ms) / 1000);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  if (frame.offset_sec !== undefined && frame.offset_sec !== null) {
    const seconds = Number(frame.offset_sec);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  return frame.frame_number !== undefined ? `#${frame.frame_number}` : "帧";
}

function normalizeApiPayloadUrls(value) {
  if (Array.isArray(value)) return value.map((item) => normalizeApiPayloadUrls(item));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (
        typeof item === "string" &&
        (key === "url" || key.endsWith("_url"))
      ) {
        return [key, withBase(item)];
      }
      return [key, normalizeApiPayloadUrls(item)];
    })
  );
}

async function api(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
  if (
    state.session?.read_only &&
    isMutation
  ) {
    throw new Error(
      uiText(
        "当前入口为只读预览；请通过获准的企业 SSO 域名访问。",
        "This endpoint is read-only; use the approved enterprise SSO domain."
      )
    );
  }
  const response = await fetch(withBase(path), {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(isMutation ? { "X-RA-Triage-Request": "browser-v1" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = normalizeApiPayloadUrls(
    await response.json().catch(() => ({}))
  );
  if (!response.ok) throw new Error(payload.detail || `请求失败 (${response.status})`);
  return payload;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden", "error");
  if (isError) toast.classList.add("error");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 4600);
}

function acknowledgeLocalChange(payload) {
  const revision = Number(payload?.change_revision);
  if (Number.isFinite(revision)) state.changeRevision = revision;
  // A poll that started before this mutation can still return the old
  // revision.  Invalidate that response so it cannot reselect the case.
  state.changePollEpoch += 1;
  state.deferredDetailRefresh = false;
}

async function refreshChangedData() {
  if (state.activePage === "review") {
    await Promise.all([
      loadRuns({ preserveEmpty: !state.selectedRunId }),
      loadOverview(),
      loadCases({ keepSelection: true, page: state.casePage }),
      loadClusters(),
      loadReviewers(),
    ]);
    if (state.selectedId) {
      if (
        state.reviewFormDirty ||
        state.savingAnnotation ||
        state.pendingReviewImages.length
      ) {
        if (!state.deferredDetailRefresh) {
          state.deferredDetailRefresh = true;
          showToast("检测到新的协作更新；当前未保存内容已保留，保存后会合并最新数据。");
        }
      } else {
        await selectCase(state.selectedId, { updateRoute: false });
      }
    }
    return;
  }
  if (state.activePage === "analysis") {
    await Promise.all([
      loadRuns({ preserveEmpty: !state.selectedRunId }),
      loadOverview(),
      loadReviewers(),
      loadReviewReasonAnalysis(),
    ]);
    return;
  }
  if (state.activePage === "runs") {
    await Promise.all([loadRuns({ preserveEmpty: true }), loadOverview()]);
    return;
  }
  if (state.activePage === "prediction") {
    await Promise.all([loadPredictionBatches(), loadOverview()]);
    return;
  }
  if (state.activePage === "status") {
    await loadStatus();
  }
}

function scheduleChangePoll(delay = 1800) {
  clearTimeout(state.changePollTimer);
  state.changePollTimer = window.setTimeout(pollChangeRevision, delay);
}

async function pollChangeRevision() {
  if (state.changePollInFlight) return scheduleChangePoll();
  if (document.hidden) return scheduleChangePoll(3000);
  state.changePollInFlight = true;
  const pollEpoch = state.changePollEpoch;
  let delay = 1800;
  try {
    const data = await api("/api/change-revision");
    if (pollEpoch !== state.changePollEpoch) return;
    const revision = Number(data.revision || 0);
    delay = Math.max(1000, Number(data.poll_after_ms || 1800));
    if (state.changeRevision === null) {
      state.changeRevision = revision;
    } else if (revision !== state.changeRevision) {
      await refreshChangedData();
      state.changeRevision = revision;
    }
  } catch (error) {
    delay = 5000;
    console.warn("协作同步暂时不可用", error);
  } finally {
    state.changePollInFlight = false;
    scheduleChangePoll(delay);
  }
}

function startChangePolling() {
  scheduleChangePoll(0);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleChangePoll(0);
  });
}

function applySidebarState() {
  $("#appShell").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  const expanded = String(!state.sidebarCollapsed);
  const title = state.sidebarCollapsed
    ? uiText("展开工具栏", "Expand toolbar")
    : uiText("折叠工具栏", "Collapse toolbar");
  $("#sidebarToggle").setAttribute("aria-expanded", expanded);
  $("#sidebarToggle").title = title;
  $("#sidebarBrandToggle").setAttribute("aria-expanded", expanded);
  $("#sidebarBrandToggle").title = title;
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  localStorage.setItem("ra-triage-sidebar-collapsed", String(state.sidebarCollapsed));
  applySidebarState();
}

function validDisplayName(value) {
  const username = String(value || "").trim();
  return /^[A-Za-z0-9._@-]{1,128}$/.test(username) ? username : "";
}

async function browserLcaUsername() {
  const endpoints =
    window.location.protocol === "https:"
      ? ["https://127.0.0.1:19888/lcainfo"]
      : ["http://127.0.0.1:18888/lcainfo"];
  for (const endpoint of endpoints) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    try {
      const response = await fetch(endpoint, {
        credentials: "omit",
        mode: "cors",
        signal: controller.signal,
      });
      if (!response.ok) continue;
      const payload = await response.json();
      const username = validDisplayName(payload?.LocalUserAccount);
      if (username) return username;
    } catch {
      // LCA is an optional display-name fallback on direct-IP deployments.
    } finally {
      clearTimeout(timer);
    }
  }
  return "";
}

function renderSession() {
  const username = state.session.username;
  const identityPending = Boolean(state.session.identity_pending);
  $("#sessionUserName").textContent = username || (identityPending
    ? uiText("身份识别中…", "Identifying user…")
    : uiText("用户未识别", "User not identified"));
  $("#userAvatar").textContent = username ? username.slice(0, 1).toUpperCase() : "?";
  $("#sessionUserSource").textContent = state.session.read_only
    ? uiText("只读预览", "Read-only preview")
    : state.session.verified
    ? uiText("企业 SSO · 已验证", "Enterprise SSO · verified")
    : identityPending
      ? uiText("页面可先使用", "Page ready")
      : username
      ? uiText("本机 LCA · 未验证", "Local LCA · unverified")
      : uiText("当前会话", "Current session");
  $("#sidebarUser").title = state.session.verified
    ? `可信代理认证：${username}`
    : username
      ? `本机 LCA 用户：${username}（仅作显示与默认标注人）`
      : "当前没有可用的用户名";
  const logoutLink = $("#sessionLogoutLink");
  if (logoutLink) {
    const logoutUrl = String(state.session.logout_url || "");
    logoutLink.hidden = !logoutUrl || identityPending;
    logoutLink.href = logoutUrl || "#";
    logoutLink.textContent = state.session.verified
      ? uiText("退出", "Sign out")
      : uiText("重新登录", "Sign in again");
  }
  document.documentElement.dataset.accessMode = state.session.read_only
    ? "read-only"
    : "write";
  const batchActor = $("#batchActorSummary");
  if (batchActor) {
    batchActor.textContent = state.session.verified
      ? uiText(`当前用户：${username}（企业 SSO 已验证）`, `Current user: ${username} (enterprise SSO verified)`)
      : username
        ? uiText(`当前用户：${username}（本机 LCA，仅作审计显示）`, `Current user: ${username} (local LCA, display only)`)
        : uiText("当前用户未识别；服务器会按实际会话记录请求人。", "User not identified; the server records the actual requester.");
  }
  const importActor = $("#modelImportActorSummary");
  if (importActor) {
    importActor.textContent = state.session.verified
      ? uiText(`本次导入创建人：${username}（企业 SSO 已验证）`, `Import owner: ${username} (enterprise SSO verified)`)
      : username
        ? uiText(`本次导入显示名：${username}（本机 LCA，未验证；不能用于权限）`, `Import display name: ${username} (local LCA, unverified; not for authorization)`)
        : uiText("当前没有可信 SSO；Run 创建人将记为未记录。", "No trusted SSO; the Run creator will be recorded as unknown.");
  }
  if (state.activePage === "prediction") ensurePredictionBatchName();
}

async function loadSession() {
  const serverSession = await api("/api/session");
  if (serverSession.authenticated && validDisplayName(serverSession.username)) {
    state.session = serverSession;
    renderSession();
    return;
  }
  state.session = {
    username: "",
    source: "anonymous",
    identity_pending: Boolean(serverSession.browser_lca_fallback),
    authenticated: false,
    verified: false,
    can_manage_team_default: false,
    can_write: serverSession.can_write !== false,
    read_only: Boolean(serverSession.read_only),
  };
  renderSession();
  if (!serverSession.browser_lca_fallback) return;
  // Local LCA is only a display-name fallback.  It can take up to 1.5s and
  // must never hold the Review gallery or a deep-linked Issue behind it.
  void browserLcaUsername().then((username) => {
    if (state.session.authenticated || state.session.verified) return;
    state.session = {
      ...state.session,
      username,
      source: username ? "browser_lca_unverified" : "anonymous",
      identity_pending: false,
    };
    renderSession();
  }).catch(() => {
    state.session = { ...state.session, identity_pending: false };
    renderSession();
  });
}

function renderConfig() {
  const baseline = state.config?.baseline || {};
  $(".header-metrics")?.setAttribute("title", baseline.message || "0508 baseline GT 只读");
  if ($("#trailScopeCount")) $("#trailScopeCount").textContent = baseline.count ?? "—";
  const trail = state.trailInspection || state.config?.trail_sync || {};
  if ($("#trailViewId")) $("#trailViewId").textContent = trail.view_id ?? "2410";
  renderTrailSyncState();
  renderBatchRuntimeSummary();
  updateFilteredPredictionButton();
  renderAnalysisCatalogFilters();
}

function renderAnalysisCatalogFilters() {
  const evidenceSelect = $("#analysisEvidenceFilter");
  if (evidenceSelect) {
    const previous = evidenceSelect.value;
    evidenceSelect.innerHTML = [
      '<option value="">全部缺失信息</option>',
      ...(state.config?.missing_evidence_catalog || []).map(
        (item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`
      ),
    ].join("");
    evidenceSelect.value = [...evidenceSelect.options].some(
      (option) => option.value === previous
    )
      ? previous
      : "";
  }
  const tagSelect = $("#analysisTagFilter");
  if (tagSelect) {
    const previous = tagSelect.value;
    tagSelect.innerHTML = [
      '<option value="">全部场景 Tags</option>',
      ...(state.config?.review_tag_catalog || []).map(
        (item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`
      ),
    ].join("");
    tagSelect.value = [...tagSelect.options].some(
      (option) => option.value === previous
    )
      ? previous
      : "";
  }
}

function renderTrailSyncState() {
  const target = $("#trailSyncState");
  if (!target) return;
  const trail = state.trailInspection || state.config?.trail_sync || {};
  const status = trail.status || "not_started";
  const visibleFields = trail.fields_visible?.length
    ? trail.fields_visible.join("、")
    : "尚未发现模型字段";
  const coverage =
    trail.usable_predictions === undefined
      ? ""
      : ` · 可用 ${trail.usable_predictions} / ${trail.queried_issues ?? "—"}`;
  target.className = `trail-sync-state ${
    ["preview_ready", "ready"].includes(status)
      ? "ok"
      : ["failed", "unavailable", "empty"].includes(status)
        ? "warn"
        : "pending"
  }`;
  target.innerHTML = `
    <strong>${escapeHtml(trail.message || "尚未检查 Trail 模型字段。")}</strong>
    <span>字段：${escapeHtml(visibleFields)}${escapeHtml(coverage)}</span>`;
  const checkButton = $("#checkTrailButton");
  const createButton = $("#syncTrailButton");
  const running = status === "running";
  if (checkButton) checkButton.disabled = running;
  if (createButton) {
    createButton.disabled = running || !trail.can_create;
    createButton.title = trail.can_create
      ? "创建或复用本地不可变快照；不会改变团队默认 Run"
      : "请先检查字段；所有 baseline issue 分片必须完整返回，结果本身可为部分覆盖";
  }
}

async function loadConfig() {
  state.config = await api("/api/dashboard-config");
  renderConfig();
}

function renderOverview(data) {
  $("#statIssues").textContent = data.issues ?? "—";
  $("#statFailures").textContent = data.model_failures ?? "—";
  $("#statReviewed").textContent = data.reviewed_failures ?? data.labelled ?? "—";
  $("#statPredictions").textContent = data.predictions ?? "—";
  renderActiveRun(data);
}

async function loadOverview() {
  const query = state.selectedRunId ? `?model_run_id=${encodeURIComponent(state.selectedRunId)}` : "";
  renderOverview(await api(`/api/overview${query}`));
}

function formatStatusDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days) return uiText(`${days} 天 ${hours} 小时`, `${days}d ${hours}h`);
  if (hours) return uiText(`${hours} 小时 ${minutes} 分`, `${hours}h ${minutes}m`);
  return uiText(`${minutes} 分钟`, `${minutes}m`);
}

function formatStatusBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = index >= 3 ? 1 : index ? 1 : 0;
  return `${size.toFixed(digits)} ${units[index]}`;
}

function systemStatusChip(label, tone = "ok") {
  return `<span class="status-chip ${tone}">${escapeHtml(label)}</span>`;
}

function systemStatusRows(items) {
  return `<div class="system-status-rows">${items
    .map(
      ([label, value]) => `<div class="system-status-row"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`
    )
    .join("")}</div>`;
}

function systemStatusCard({ title, chip, tone = "ok", rows, extra = "" }) {
  return `<article class="system-status-card">
    <div class="system-status-card-head"><h3>${escapeHtml(title)}</h3>${systemStatusChip(chip, tone)}</div>
    ${systemStatusRows(rows)}${extra}
  </article>`;
}

function renderSystemStatus() {
  const hero = $("#systemStatusHero");
  const grid = $("#systemStatusGrid");
  if (!hero || !grid) return;
  const data = state.systemStatus;
  if (!data) return;
  const database = data.database || {};
  const backups = data.backups || {};
  const volume = data.volume || {};
  const baseline = data.baseline || {};
  const trail = data.trail_sync || {};
  const gateway = data.model_gateway || {};
  const application = data.application || {};
  const overall = data.overall || { status: "degraded", problems: [] };
  const healthy = overall.status === "healthy";
  const problemLabels = {
    database_unavailable: uiText("数据库不可用", "Database unavailable"),
    database_not_persistent: uiText("数据库未使用持久卷", "Database is not persistent"),
    baseline_unavailable: uiText("基线不可用", "Baseline unavailable"),
    backup_missing: uiText("缺少数据库备份", "Database backup missing"),
    backup_checksum_missing: uiText("备份缺少校验文件", "Backup checksum missing"),
    backup_stale: uiText("最近备份已过期", "Latest backup is stale"),
    backup_schedule_unregistered: uiText("备份计划未登记", "Backup schedule unregistered"),
    disk_space_low: uiText("磁盘剩余空间不足", "Disk space is low"),
  };
  const problems = (overall.problems || []).map((key) => problemLabels[key] || key);
  hero.classList.toggle("degraded", !healthy);
  hero.innerHTML = `
    <div class="system-status-summary">
      <div class="system-status-indicator" aria-hidden="true">${healthy ? "✓" : "!"}</div>
      <div>
        <h2>${escapeHtml(healthy ? uiText("关键系统运行正常", "Core systems are healthy") : uiText("系统有项目需要关注", "System needs attention"))}</h2>
        <p>${escapeHtml(healthy ? uiText("服务、持久化数据库与备份保护均已就绪。", "Service, persistent database, and backup protection are ready.") : problems.join(" · ") || uiText("请查看下方状态卡。", "Review the status cards below."))}</p>
      </div>
    </div>
    <div class="system-status-build"><span>${escapeHtml(uiText("部署版本", "Build"))}</span><code>${escapeHtml(application.build_commit || data.build_commit || "unverified")}</code></div>`;

  const backupAge = backups.latest_age_seconds == null
    ? "—"
    : formatStatusDuration(backups.latest_age_seconds);
  const backupReady = Boolean(
    backups.available && backups.latest_checksum_present && backups.schedule_registered
  );
  const databaseReady = Boolean(database.ok && (database.backend !== "postgresql" || database.persistent_data));
  const baselineReady = baseline.status === "ready" && Number(baseline.count || 0) > 0;
  const assetsReady = Boolean(
    data.ra_auto_triage_root_available && data.ares_manifest_available && data.camera_cache_root_available
  );
  const gatewayReady = Boolean(gateway.configured);
  const usedPercent = Math.max(0, Math.min(100, Number(volume.used_percent) || 0));
  grid.innerHTML = [
    systemStatusCard({
      title: uiText("应用服务", "Application"),
      chip: uiText("在线", "Online"),
      rows: [
        [uiText("运行时间", "Uptime"), formatStatusDuration(application.uptime_seconds)],
        [uiText("启动时间", "Started"), formatTime(application.started_at)],
        [uiText("共享数据版本", "Shared revision"), String(database.revision ?? "—")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据库", "Database"),
      chip: databaseReady ? uiText("正常", "Healthy") : uiText("异常", "Issue"),
      tone: databaseReady ? "ok" : "fail",
      rows: [
        [uiText("存储引擎", "Backend"), database.backend === "postgresql" ? "PostgreSQL" : "SQLite"],
        [uiText("持久化", "Persistence"), database.persistent_data ? uiText("/volume 持久卷", "/volume persistent") : uiText("本地存储", "Local storage")],
        [uiText("连接延迟", "Latency"), database.latency_ms == null ? "—" : `${database.latency_ms} ms`],
        [uiText("版本 / Migration", "Version / migrations"), `${database.server_version || "—"} · ${database.migration_count ?? 0}`],
        [uiText("连接池上限", "Pool limit"), String(database.pool_max_size || "—")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据库备份", "Database backups"),
      chip: backupReady ? uiText("已保护", "Protected") : uiText("需关注", "Attention"),
      tone: backupReady ? "ok" : "warn",
      rows: [
        [uiText("最近备份", "Latest backup"), backups.latest_created_at ? formatTime(backups.latest_created_at) : "—"],
        [uiText("备份距今", "Backup age"), backupAge],
        [uiText("大小 / 份数", "Size / copies"), `${formatStatusBytes(backups.latest_size_bytes)} · ${backups.count || 0}`],
        [uiText("SHA-256 文件", "SHA-256 file"), backups.latest_checksum_present ? uiText("已生成", "Present") : uiText("缺失", "Missing")],
        [uiText("自动计划", "Schedule"), backups.schedule_registered ? `${backups.schedule} · ${uiText("服务器时间", "server time")}` : uiText("未登记", "Not registered")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据与媒体", "Dataset & media"),
      chip: baselineReady && assetsReady ? uiText("就绪", "Ready") : uiText("部分可用", "Partial"),
      tone: baselineReady && assetsReady ? "ok" : "warn",
      rows: [
        [uiText("0508 基线", "0508 baseline"), `${baseline.count ?? 0} · ${baseline.status || "—"}`],
        [uiText("基线范围", "Baseline scope"), baseline.scope || "—"],
        [uiText("Ares BEV", "Ares BEV"), data.ares_manifest_available ? `${data.ares_indexed_issues || 0} Issues` : uiText("不可用", "Unavailable")],
        [uiText("Camera 缓存", "Camera cache"), data.camera_cache_root_available ? uiText("可用", "Available") : uiText("不可用", "Unavailable")],
        [uiText("BEV 视频", "BEV video"), data.ares_video_root_available ? uiText("可用", "Available") : uiText("不可用", "Unavailable")],
      ],
    }),
    systemStatusCard({
      title: uiText("模型与集成", "Models & integrations"),
      chip: gatewayReady ? uiText("网关就绪", "Gateway ready") : uiText("网关未配置", "Gateway unavailable"),
      tone: gatewayReady ? "ok" : "warn",
      rows: [
        [uiText("运行模式", "Deployment mode"), data.application?.deployment_mode === "production" ? uiText("生产", "Production") : uiText("开发", "Development")],
        [uiText("模型网关", "Model gateway"), gateway.configured ? uiText("服务端凭证已配置", "Server credential configured") : uiText("未配置", "Not configured")],
        [uiText("Batch 预测", "Batch prediction"), data.batch_prediction_enabled ? uiText("已启用", "Enabled") : uiText("已关闭", "Disabled")],
        [uiText("AutoTriage 推送", "AutoTriage publish"), data.autotriage_push_enabled ? uiText("已启用", "Enabled") : uiText("关闭（安全默认）", "Off (safe default)")],
        [uiText("Trail 字段", "Trail fields"), ["ready", "preview_ready"].includes(trail.status) ? uiText("可用", "Available") : uiText("当前不可用", "Currently unavailable")],
      ],
      extra: trail.message ? `<p class="system-status-note">${escapeHtml(trail.message)}</p>` : "",
    }),
    systemStatusCard({
      title: uiText("持久卷容量", "Persistent volume"),
      chip: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? uiText("空间充足", "Capacity OK") : uiText("空间不足", "Low space"),
      tone: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? "ok" : "fail",
      rows: [
        [uiText("已使用", "Used"), `${formatStatusBytes(volume.used_bytes)} · ${usedPercent}%`],
        [uiText("剩余", "Free"), formatStatusBytes(volume.free_bytes)],
        [uiText("总容量", "Total"), formatStatusBytes(volume.total_bytes)],
      ],
      extra: `<div class="system-capacity"><div class="system-capacity-track"><span class="${usedPercent >= 95 ? "warn" : ""}" style="width:${usedPercent}%"></span></div></div>`,
    }),
  ].join("");
  const updated = $("#systemStatusUpdatedAt");
  if (updated) {
    updated.textContent = `${uiText("更新于", "Updated")} ${formatTime(data.generated_at)}`;
  }
}

async function loadStatus() {
  const data = await api("/api/status");
  state.systemStatus = data;
  if (data.baseline || data.trail_sync) {
    state.config = {
      ...(state.config || {}),
      baseline: data.baseline || state.config?.baseline,
      trail_sync: data.trail_sync || state.config?.trail_sync,
    };
    renderConfig();
  }
  renderSystemStatus();
}

async function loadReviewers() {
  const data = await api("/api/reviewers");
  state.reviewers = data.items || [];
  ["#reviewerFilter", "#analysisReviewerFilter"].forEach((selector) => {
    const select = $(selector);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = `<option value="">全部复核人</option>${state.reviewers
      .map(
        (item) => {
          const trust =
            item.verified_count > 0 && item.unverified_count > 0
              ? " · 混合身份"
              : item.verified
                ? " · SSO"
                : "";
          return `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${item.review_count} 条${trust}</option>`;
        }
      )
      .join("")}`;
    select.value = state.reviewers.some((item) => item.name === previous) ? previous : "";
  });
}

function checkedAnalysisComparisonStatus() {
  return normalizedAnalysisComparisonStatus(
    $("#analysisComparisonFilter")?.value,
    state.reviewAnalysis.comparisonStatus || "all"
  );
}

function setAnalysisComparisonStatus(
  comparisonStatus,
  { hasRun = Boolean($("#analysisRunFilter")?.value) } = {}
) {
  let nextStatus = normalizedAnalysisComparisonStatus(comparisonStatus);
  if (!hasRun && nextStatus !== "all") nextStatus = "all";
  state.reviewAnalysis.comparisonStatus = nextStatus;
  const select = $("#analysisComparisonFilter");
  if (select) {
    select.disabled = !hasRun;
    select.value = nextStatus;
  }
  return nextStatus;
}

function renderAnalysisRunFilter() {
  const select = $("#analysisRunFilter");
  if (!select) return;
  select.innerHTML = `<option value="">不叠加模型输出</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  select.value = state.modelRuns.some((run) => run.id === state.selectedRunId)
    ? state.selectedRunId
    : "";
  setAnalysisComparisonStatus(state.reviewAnalysis.comparisonStatus, {
    hasRun: Boolean(select.value),
  });
}

async function loadRuns({ preferDefault = false, preserveEmpty = false } = {}) {
  const data = await api("/api/model-runs");
  state.modelRuns = data.items || [];
  const select = $("#modelRunFilter");
  const previousRunId = state.selectedRunId;
  const preferredRunId =
    data.default_model_run_id ||
    state.config?.default_model_run_id ||
    (preferDefault ? state.modelRuns[0]?.id || "" : "");
  const candidate = preferDefault
    ? preferredRunId
    : preserveEmpty
      ? state.selectedRunId
      : state.selectedRunId || data.default_model_run_id || state.config?.default_model_run_id || "";
  select.innerHTML = `<option value="">未选择模型 run</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  state.selectedRunId = state.modelRuns.some((run) => run.id === candidate) ? candidate : "";
  select.value = state.selectedRunId;
  if (preferDefault && !previousRunId && state.selectedRunId) {
    state.reviewComparisonStatus = "mismatch";
  }
  if (!state.selectedRunId) state.reviewComparisonStatus = "all";
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  renderAnalysisRunFilter();
  renderRunFilters();
  renderRunSourceSummary();
  renderActiveRun();
  renderRunManager();
}

const RUN_SOURCE_META = Object.freeze({
  upload: {
    label: "文件模型结果",
    description: "JSON / CSV / XLSX",
    className: "source-upload",
    countId: "runSourceCountUpload",
  },
  trail_snapshot: {
    label: "Trail 快照",
    description: "Trail 只读字段",
    className: "source-trail",
    countId: "runSourceCountTrail",
  },
  autotriage_snapshot: {
    label: "AutoTriage 快照",
    description: "平台只读结果",
    className: "source-autotriage",
    countId: "runSourceCountAutotriage",
  },
  manual_batch: {
    label: "网页 Batch 预测",
    description: "服务器模型推理",
    className: "source-batch",
  },
});

function runSourceMeta(runOrKind) {
  const kind = typeof runOrKind === "string" ? runOrKind : runOrKind?.kind;
  return RUN_SOURCE_META[kind] || {
    label: kind || "未知来源",
    description: "未记录来源",
    className: "source-unknown",
  };
}

function runSourceReference(run) {
  const metadata = run?.metadata && typeof run.metadata === "object" ? run.metadata : {};
  const recordUrl = safeUrl(metadata.record_url || metadata.records_url || "");
  if (recordUrl) {
    return `<a class="run-source-link" href="${escapeHtml(recordUrl)}" target="_blank" rel="noreferrer">原始 records</a>`;
  }
  if (run?.kind === "trail_snapshot") {
    const viewId = metadata.view_id || metadata.trail_view_id || String(run.source_name || "").match(/\d+/)?.[0] || "2410";
    return `<span class="run-source-ref">Trail view ${escapeHtml(viewId)}</span>`;
  }
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const sourceName = String(source.filename || run?.source_name || "").split(/[\\/]/).pop() || "文件名未记录";
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  const downloadUrl = safeSameOriginAssetUrl(source.download_url);
  const reconstructed = source.reconstructed
    ? '<span class="run-source-reconstructed">Run 重建</span>'
    : "";
  const previewAction = source.preview_supported
    ? `<button class="run-source-preview" type="button" data-preview-run="${escapeHtml(run?.id || "")}">预览</button>`
    : previewUrl
      ? `<a class="run-source-link" href="${escapeHtml(previewUrl)}" target="_blank" rel="noreferrer">打开</a>`
      : "";
  const actions = source.available && (previewUrl || downloadUrl)
    ? `<span class="run-source-actions">${previewAction}${downloadUrl ? `<a class="run-source-link" href="${escapeHtml(downloadUrl)}" download>下载</a>` : ""}</span>${reconstructed}`
    : `<span class="run-source-unavailable">未归档</span>`;
  return `<span class="run-source-ref" title="${escapeHtml(run?.source_name || sourceName)}">原始文件 · ${escapeHtml(sourceName)} ${actions}</span>`;
}

function renderRunSourceSummary() {
  Object.entries(RUN_SOURCE_META).forEach(([kind, meta]) => {
    if (!meta.countId) return;
    const target = $(`#${meta.countId}`);
    if (target) {
      target.textContent = String(state.modelRuns.filter((run) => run.kind === kind).length);
    }
  });
}

function runOwner(run) {
  return run.created_by || run.declared_author || "";
}

function runPeople() {
  const values = new Set();
  state.modelRuns.forEach((run) => {
    const owner = runOwner(run);
    if (owner) values.add(owner);
  });
  return [...values].sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function runBatchName(run) {
  const experiment = run.metadata?.experiment || {};
  const platformBatch = run.metadata?.platform_batch || {};
  const sourceFile = String(run.source_name || "").split(/[\\/]/).pop() || "";
  return (
    platformBatch.batch_name ||
    experiment.run_id ||
    experiment.experiment_id ||
    sourceFile.replace(/\.(json|csv|xlsx|xlsm)$/i, "") ||
    "未命名批次"
  );
}

function renderRunFilters() {
  const select = $("#runPersonFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  const people = runPeople();
  select.innerHTML = [
    '<option value="">全部人员</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...people.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
  ].join("");
  select.value =
    previous === "__me__" || people.includes(previous)
      ? previous
      : "";
}

function activeRun() {
  return state.modelRuns.find((run) => run.id === state.selectedRunId);
}

function renderActiveRun(overview = null) {
  const run = activeRun();
  const activeName = $("#activeRunName");
  const activeMeta = $("#activeRunMeta");
  if (activeName) activeName.textContent = run?.name || "尚未选择模型 Run";
  const runSelect = $("#modelRunFilter");
  if (runSelect) {
    runSelect.title = run
      ? `${run.name} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}`
      : "尚未选择模型 Run";
  }
  if (!run) {
    if (activeMeta) {
      activeMeta.textContent =
        state.config?.trail_sync?.message ||
        "选择团队 Run、创建 Trail 只读快照，或导入 JSON / CSV / XLSX";
    }
    return;
  }
  const coverage = overview?.predictions ?? run.baseline_prediction_count ?? 0;
  const failures = overview?.model_failures ?? run.failure_count ?? 0;
  const reviewed = overview?.reviewed_failures;
  const sourceLabel = runSourceMeta(run).label;
  if (activeMeta) {
    activeMeta.textContent =
      `${coverage} / ${state.config?.baseline?.count || "—"} 覆盖 · ${failures} 条判断失败` +
      `${reviewed === undefined ? "" : ` · ${reviewed} 条已复核`}` +
      ` · ${sourceLabel}`;
  }
}

function renderRunManager() {
  const list = $("#modelRunList");
  if (!list) return;
  const search = ($("#runSearchInput")?.value || "").trim().toLowerCase();
  const personValue = $("#runPersonFilter")?.value || "";
  const person = personValue === "__me__" ? state.session.username : personValue;
  const kind = $("#runKindFilter")?.value || "";
  const filteredRuns = state.modelRuns.filter((run) => {
    const personMatch = !person || runOwner(run) === person;
    const searchText = [
      run.name,
      runBatchName(run),
      run.source_name,
      run.created_by,
      run.declared_author,
      run.metadata?.model_name,
      run.metadata?.prompt_version,
      run.metadata?.external_username,
    ]
      .join(" ")
      .toLowerCase();
    return personMatch && (!kind || run.kind === kind) && (!search || searchText.includes(search));
  });
  const totalCoverage = filteredRuns.reduce(
    (sum, run) => sum + Number(run.baseline_prediction_count || 0),
    0
  );
  $("#runManagerSummary").textContent =
    `${filteredRuns.length} / ${state.modelRuns.length} 个 Run · ${totalCoverage} 条预测`;
  if (!filteredRuns.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有 Run。</div>';
    return;
  }
  const baselineCount = Number(state.config?.baseline?.count || 0);
  list.innerHTML = filteredRuns
    .map(
      (run) => {
        const coverage = Number(run.baseline_prediction_count || 0);
        const coverageLabel =
          baselineCount && coverage >= baselineCount ? "全量覆盖" : "部分覆盖";
        const owner = runOwner(run) || "未记录";
        const batch = runBatchName(run);
        const modelName = run.metadata?.model_name || run.metadata?.experiment?.model_name || "";
        const promptVersion = run.metadata?.prompt_version || run.metadata?.experiment?.prompt_version || "";
        const externalUser = run.metadata?.external_username || "";
        const sourceMeta = runSourceMeta(run);
        const ownerTitle = run.created_by
          ? `提交人：${run.created_by}${run.declared_author && run.declared_author !== run.created_by ? `；结果包作者：${run.declared_author}` : ""}`
          : run.declared_author
            ? `结果包作者：${run.declared_author}`
            : "人员信息未记录";
        return `<article class="run-row ${run.id === state.selectedRunId ? "active" : ""}">
        <div class="run-row-main">
          <div class="run-row-title">
            <strong>${escapeHtml(run.name)}</strong>
            <span class="run-source-badge ${sourceMeta.className}" title="${escapeHtml(sourceMeta.description)}">${escapeHtml(sourceMeta.label)}</span>
            <span class="run-coverage-badge">${coverageLabel}</span>
          </div>
          <div class="run-row-meta">
            <span title="${escapeHtml(ownerTitle)}">人员 · <b class="run-meta-value">${escapeHtml(owner)}</b></span>
            <span title="${escapeHtml(run.source_name || "")}">批次 · <b class="run-meta-value">${escapeHtml(batch)}</b></span>
            ${modelName ? `<span>模型 · ${escapeHtml(modelName)}</span>` : ""}
            ${promptVersion ? `<span>Prompt · ${escapeHtml(promptVersion)}</span>` : ""}
            ${externalUser && externalUser !== owner ? `<span>平台用户 · ${escapeHtml(externalUser)}</span>` : ""}
            <span>${runSourceReference(run)}</span>
            <span>${coverage} / ${state.config?.baseline?.count || "—"} 条</span>
            <span class="run-failure-count">错误 ${run.failure_count ?? 0}</span>
            <span>${formatTime(run.created_at)}</span>
          </div>
        </div>
        <div class="run-row-actions">
          <button class="button ${run.id === state.selectedRunId ? "button-primary" : "button-quiet"}" type="button" data-use-run="${escapeHtml(run.id)}">${run.id === state.selectedRunId ? "当前 Review" : "打开 Review"}</button>
          ${run.is_default ? '<button class="button button-quiet" type="button" disabled title="先切换团队默认 Run 才能删除">默认 Run</button>' : `<button class="button button-danger" type="button" data-delete-run="${escapeHtml(run.id)}">删除</button>`}
        </div>
      </article>`;
      }
    )
    .join("");
  list.querySelectorAll("[data-use-run]").forEach((button) => {
    button.addEventListener("click", () => useModelRun(button.dataset.useRun));
  });
  list.querySelectorAll("[data-preview-run]").forEach((button) => {
    button.addEventListener("click", () => openSourcePreview(button.dataset.previewRun));
  });
  list.querySelectorAll("[data-delete-run]").forEach((button) => {
    button.addEventListener("click", () => deleteModelRun(button.dataset.deleteRun));
  });
}

async function useModelRun(runId) {
  if (!state.modelRuns.some((run) => run.id === runId)) return;
  state.selectedRunId = runId;
  state.reviewComparisonStatus = "mismatch";
  state.failureOnly = true;
  state.selectedId = "";
  state.casePage = 1;
  state.galleryScrollY = 0;
  $("#modelRunFilter").value = runId;
  setReviewComparisonStatus("mismatch", { hasRun: true });
  renderActiveRun();
  renderRunManager();
  await Promise.all([loadCases({ keepSelection: false, page: 1 }), loadClusters(), loadOverview()]);
  navigatePage("review");
}

async function deleteModelRun(runId) {
  const run = state.modelRuns.find((item) => item.id === runId);
  if (!run) return;
  if (run.is_default) {
    showToast("当前团队默认 Run 不能删除，请先切换默认 Run。", true);
    return;
  }
  const confirmed = window.confirm(
    `确认删除模型 Run「${run.name}」？\n\n该操作会删除该 Run 的模型输出和来源归档，不会删除 0508 GT、Issue 或人工 review，且不可恢复。`
  );
  if (!confirmed) return;
  const button = document.querySelector(`[data-delete-run="${CSS.escape(runId)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = "删除中…";
  }
  try {
    const result = await api(`/api/model-runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (state.selectedRunId === runId) {
      state.selectedRunId = "";
      state.reviewComparisonStatus = "all";
      state.failureOnly = false;
    }
    await Promise.all([loadRuns({ preserveEmpty: true }), loadOverview(), loadCases(), loadClusters()]);
    showToast(`已删除 Run「${result.deleted?.name || run.name}」${result.source_deleted ? "及来源文件" : ""}。`);
  } catch (error) {
    showToast(error.message, true);
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = "删除";
    }
  }
}

function reviewComparisonStatusForItem(item) {
  if (!state.selectedRunId) return "";
  const prediction = item?.prediction || {};
  if (!prediction.model_run_id) return "none";
  if (!LABELS.includes(prediction.label)) return "none";
  return prediction.mismatch ? "mismatch" : "match";
}

function issueCard(item) {
  const isSelected = item.issue_id === state.selectedId;
  const rawTitle = String(item.title || item.scenario || "").trim();
  const title =
    rawTitle && !LABELS.includes(rawTitle) && rawTitle !== item.gt_label ? rawTitle : "";
  const annotation = item.annotation?.label;
  const prediction = item.prediction?.label;
  const comparisonStatus = reviewComparisonStatusForItem(item);
  const comparisonMeta = REVIEW_COMPARISON_META[comparisonStatus];
  const mismatch = comparisonStatus === "mismatch";
  const thumbnailUrl = safeSameOriginAssetUrl(item.thumbnail?.url);
  const thumbnailLabel = String(
    item.thumbnail?.label || (thumbnailUrl ? "BEV 关键帧" : "暂无缩略图")
  );
  const issueUrl = safeUrl(item.voyager_issue_url);
  return `
    <article class="issue-card ${isSelected ? "selected" : ""}" data-issue-id="${escapeHtml(item.issue_id)}">
      <button class="issue-card-open" type="button" data-open-issue="${escapeHtml(item.issue_id)}" aria-label="打开 ${escapeHtml(item.issue_id)} Review"></button>
      <div class="issue-thumbnail">
        <div class="issue-thumbnail-placeholder" aria-hidden="true"><span>RA</span><small>暂无 BEV 缩略图</small></div>
        ${thumbnailUrl ? `<img src="${escapeHtml(thumbnailUrl)}" alt="${escapeHtml(item.issue_id)} ${escapeHtml(thumbnailLabel)}" loading="lazy" decoding="async" data-case-thumbnail />` : ""}
        <span class="issue-thumbnail-label">${escapeHtml(thumbnailLabel)}</span>
        <button class="issue-media-preview" type="button" data-case-media-preview="${escapeHtml(item.issue_id)}" aria-label="预览 ${escapeHtml(item.issue_id)} 的 BEV、Camera 和视频">媒体预览</button>
        ${comparisonMeta ? `<span class="comparison-chip comparison-${comparisonStatus} issue-thumbnail-status">${escapeHtml(comparisonMeta.label)}</span>` : ""}
      </div>
      <div class="issue-card-body">
        <div class="issue-card-heading">
          ${issueUrl ? `<a class="issue-id" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" data-card-link title="打开 Voyager Issue">${escapeHtml(item.issue_id)}</a>` : `<span class="issue-id">${escapeHtml(item.issue_id)}</span>`}
          ${!mismatch ? labelBadge(annotation, "待 review") : ""}
        </div>
        ${title ? `<div class="issue-title">${escapeHtml(title)}</div>` : ""}
        <div class="issue-card-labels">
          <span class="issue-label-pair"><small>GT</small>${labelBadge(item.gt_label, "—")}</span>
          <span class="issue-label-pair"><small>模型</small>${prediction ? labelBadge(prediction, "—") : labelBadge("", "—")}</span>
        </div>
        ${item.annotation?.author ? `<div class="issue-reviewer">复核 · ${escapeHtml(item.annotation.author)}${item.annotation.author_verified ? " · SSO" : ""}</div>` : ""}
        ${item.annotation?.missing_evidence?.length ? `<div class="row-evidence">${item.annotation.missing_evidence.map((key) => `<span>${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
      </div>
    </article>`;
}

function caseGallerySignature(items) {
  return JSON.stringify({
    selectedId: state.selectedId,
    items: (items || []).map((item) => ({
      issue_id: item.issue_id,
      title: item.title || item.scenario || "",
      gt_label: item.gt_label || "",
      prediction: item.prediction
        ? {
            label: item.prediction.label || "",
            model_run_id: item.prediction.model_run_id || "",
          }
        : null,
      annotation: item.annotation
        ? {
            label: item.annotation.label || "",
            author: item.annotation.author || "",
            author_verified: Boolean(item.annotation.author_verified),
            missing_evidence: item.annotation.missing_evidence || [],
          }
        : null,
      thumbnail: item.thumbnail?.url || "",
      voyager_issue_url: item.voyager_issue_url || "",
    })),
  });
}

function reuseGalleryThumbnails(list, previousThumbnails) {
  if (!list || !previousThumbnails?.size) return;
  list.querySelectorAll("article[data-issue-id]").forEach((card) => {
    const nextImage = card.querySelector("img[data-case-thumbnail]");
    const previous = previousThumbnails.get(card.dataset.issueId);
    if (
      !nextImage ||
      !previous ||
      previous.image === nextImage ||
      previous.url !== nextImage.src ||
      !previous.image.complete ||
      previous.image.naturalWidth <= 0
    ) {
      return;
    }
    nextImage.replaceWith(previous.image);
  });
}

function totalCasePages() {
  return Math.max(1, Math.ceil(Number(state.caseTotal || 0) / state.casePageSize));
}

function renderCasePagination() {
  const totalPages = totalCasePages();
  const previous = $("#casePagePrevious");
  const next = $("#casePageNext");
  const summary = $("#casePageSummary");
  const pageSize = $("#casePageSize");
  const result = $("#galleryResultSummary");
  if (previous) previous.disabled = state.casePage <= 1 || !state.caseTotal;
  if (next) next.disabled = state.casePage >= totalPages || !state.caseTotal;
  if (summary) summary.textContent = state.caseTotal ? `${state.casePage} / ${totalPages}` : "0 / 0";
  if (pageSize) pageSize.value = String(state.casePageSize);
  if (result) {
    const start = state.caseTotal ? (state.casePage - 1) * state.casePageSize + 1 : 0;
    const end = Math.min(state.casePage * state.casePageSize, state.caseTotal);
    result.textContent = state.caseTotal
      ? `当前 ${start}–${end} / 共 ${state.caseTotal} 条`
      : "当前没有匹配的 Issue";
  }
}

function renderCaseNavigation() {
  const index = state.cases.findIndex((item) => item.issue_id === state.selectedId);
  const previous = $("#previousIssueButton");
  const next = $("#nextIssueButton");
  const position = $("#detailQueuePosition");
  const hasPrevious = index > 0 || (index === 0 && state.casePage > 1);
  const hasNext =
    index >= 0 &&
    (index < state.cases.length - 1 ||
      state.casePage * state.casePageSize < state.caseTotal);
  if (previous) previous.disabled = !hasPrevious;
  if (next) next.disabled = !hasNext;
  if (position) {
    position.textContent =
      index >= 0
        ? `${(state.casePage - 1) * state.casePageSize + index + 1} / ${state.caseTotal}`
        : "不在当前筛选页";
  }
}

async function changeCasePage(delta) {
  const targetPage = state.casePage + delta;
  if (targetPage < 1 || targetPage > totalCasePages()) return;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  await loadCases({ keepSelection: false, page: targetPage });
  showPage("review", { historyMode: "push", issue: "" });
}

async function changeCasePageSize(value) {
  const nextPageSize = CASE_PAGE_SIZES.includes(Number(value))
    ? Number(value)
    : DEFAULT_CASE_PAGE_SIZE;
  if (nextPageSize === state.casePageSize) return;
  state.casePageSize = nextPageSize;
  state.casePage = 1;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  await loadCases({ keepSelection: false, page: 1 });
  showPage("review", { historyMode: "push", issue: "" });
}

function returnToReviewGallery() {
  clearPendingReviewImages();
  if (window.history.state?.openedFromGallery) {
    window.history.back();
    return;
  }
  clearDetail({ showGallery: true });
  showPage("review", { historyMode: "replace", issue: "" });
}

function renderCases(data) {
  state.cases = data.items || [];
  state.caseTotal = Number(data.total ?? state.cases.length);
  $("#caseCount").textContent = state.caseTotal;
  updateFilteredPredictionButton();
  renderCasePagination();
  renderCaseNavigation();
  const list = $("#issueList");
  const signature = caseGallerySignature(state.cases);
  if (list.dataset.gallerySignature === signature) {
    return;
  }
  const previousThumbnails = new Map();
  list.querySelectorAll("article[data-issue-id]").forEach((card) => {
    const image = card.querySelector("img[data-case-thumbnail]");
    if (image) previousThumbnails.set(card.dataset.issueId, { image, url: image.src });
  });
  list.dataset.gallerySignature = signature;
  if (!state.cases.length) {
    const comparisonStatus = state.reviewComparisonStatus;
    const comparisonMeta = REVIEW_COMPARISON_META[comparisonStatus];
    const hint = comparisonStatus !== "all"
      ? `没有符合 ${comparisonMeta?.label || comparisonStatus} 的 Issue，可切换模型判断结果筛选。`
      : "没有匹配的 Issue。";
    list.innerHTML = `<div class="no-asset issue-grid-empty">${hint}</div>`;
    return;
  }
  list.innerHTML = state.cases.map(issueCard).join("");
  reuseGalleryThumbnails(list, previousThumbnails);
  list.querySelectorAll("[data-open-issue]").forEach((button) => {
    button.addEventListener("click", () => selectCase(button.dataset.openIssue));
  });
  list.querySelectorAll("[data-case-media-preview]").forEach((button) => {
    button.addEventListener("click", () => {
      openCaseMediaPreview(button.dataset.caseMediaPreview, button).catch((error) => {
        showToast(error.message, true);
      });
    });
  });
  list.querySelectorAll("[data-case-thumbnail]").forEach((image) => {
    image.addEventListener("error", () => {
      const thumbnail = image.closest(".issue-thumbnail");
      thumbnail?.classList.add("thumbnail-missing");
      const label = thumbnail?.querySelector(".issue-thumbnail-label");
      if (label) label.textContent = "缩略图加载失败";
      image.remove();
    });
  });
}

function predictionBatchLimit() {
  return Math.min(
    50,
    Number(
      state.config?.prediction_batch?.max_issues ||
        state.config?.batch_prediction?.max_issues ||
        50
    )
  );
}

function updateFilteredPredictionButton() {
  const button = $("#predictFilteredButton");
  if (!button) return;
  const total = Number(state.caseTotal || 0);
  const limit = predictionBatchLimit();
  button.disabled = total === 0 || state.config?.batch_prediction?.enabled === false;
  button.textContent = total ? `预测当前筛选 · ${total}` : "预测当前筛选";
  button.title =
    total > limit
      ? `单批最多 ${limit} 个 Issue，请继续收窄筛选后再发起。`
      : `把当前 ${total} 个筛选结果带入 Batch 页面；不会立即运行或自动推送。`;
  button.classList.toggle("button-limit-warning", total > limit);
}

function openBatchDraft(issueIds, source = "") {
  const ids = [
    ...new Set(
      (issueIds || [])
        .map((issueId) => String(issueId || "").trim())
        .filter((issueId) => /^[A-Za-z0-9_-]{3,128}$/.test(issueId))
    ),
  ];
  if (!ids.length) {
    showToast("当前没有可加入 Batch 的 Issue。", true);
    return;
  }
  const limit = predictionBatchLimit();
  if (ids.length > limit) {
    showToast(`当前筛选有 ${ids.length} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`, true);
    return;
  }
  navigatePage("prediction", { issues: ids, source });
}

function predictionActorSlug() {
  const username = String(state.session.username || "triage").trim();
  const safe = username.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return (safe || "triage").slice(0, 48);
}

function defaultPredictionBatchName() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${predictionActorSlug()}_${date}_${time}`;
}

function ensurePredictionBatchName() {
  const input = $("#predictionBatchName");
  if (!input) return;
  const current = input.value.trim();
  if (current && current !== state.batchDefaultName) return;
  const next = defaultPredictionBatchName();
  input.value = next;
  state.batchDefaultName = next;
}

function renderPredictionSourceSummary() {
  const target = $("#predictionSourceSummary");
  if (!target) return;
  const count = predictionIssueIds();
  if (!state.batchDraftSource || !count.length) {
    target.classList.add("hidden");
    target.textContent = "";
    return;
  }
  target.classList.remove("hidden");
  target.textContent =
    state.batchDraftSource === "filtered"
      ? `已从 Review 当前筛选带入 ${count.length} 个 Issue；请核对模型和列表后再开始。`
      : `已从 Review 当前 Case 带入 ${count.length} 个 Issue；仍按 Batch 任务保存为独立 Model Run。`;
}

async function loadCases({
  keepSelection = true,
  page = state.casePage,
} = {}) {
  const requestSeq = ++state.caseListRequestSeq;
  state.casePage = Math.max(1, Number(page) || 1);
  const params = new URLSearchParams();
  const search = $("#searchInput").value.trim();
  const gtLabel = $("#gtFilter").value;
  const annotationLabel = $("#annotationFilter").value;
  const annotationAuthor = $("#reviewerFilter").value;
  state.selectedRunId = $("#modelRunFilter").value;
  state.reviewComparisonStatus = selectedReviewComparisonStatus();
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  if (search) params.set("search", search);
  if (gtLabel) params.set("gt_label", gtLabel);
  if (annotationLabel) params.set("annotation_label", annotationLabel);
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  if (state.selectedRunId && state.reviewComparisonStatus !== "all") {
    params.set("comparison", state.reviewComparisonStatus);
  }
  if (state.clusterKey) params.set("missing_evidence", state.clusterKey);
  params.set("page", String(state.casePage));
  params.set("page_size", String(state.casePageSize));
  params.set("include_thumbnail", "true");
  const data = await api(`/api/cases?${params.toString()}`);
  if (requestSeq !== state.caseListRequestSeq) return;
  const totalPages = Math.max(
    1,
    Math.ceil(Number(data.total || 0) / state.casePageSize)
  );
  if (state.casePage > totalPages) {
    state.casePage = totalPages;
    return loadCases({ keepSelection, page: totalPages });
  }
  renderCases(data);
  state.reviewQueueStale = false;
  if (!keepSelection) {
    clearDetail({ showGallery: state.activePage === "review" });
  }
}

async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = $("#reviewerFilter")?.value;
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  const list = $("#clusterList");
  if (!list) return;
  const data = await api(`/api/review-clusters?${params.toString()}`);
  if (!(data.items || []).length) {
    list.innerHTML = '<span class="muted">标注缺失信息后，这里会按错误模式自动聚类。</span>';
    return;
  }
  list.innerHTML = data.items
    .map(
      (item) => `<button type="button" class="cluster-chip ${state.clusterKey === item.key ? "active" : ""}" data-cluster-key="${escapeHtml(item.key)}">
        <span>${escapeHtml(evidenceLabel(item.key))}</span><b>${item.count}</b>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-cluster-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.clusterKey = button.dataset.clusterKey === state.clusterKey ? "" : button.dataset.clusterKey;
      await reloadReviewGallery({ includeOverview: false });
    });
  });
}

function safeSameOriginReviewUrl(url) {
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const pathname = stripBasePath(parsed.pathname);
    if (parsed.origin !== window.location.origin || pathname !== "/review") return "";
    return `${withBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

function reviewStatusLabel(status) {
  return (
    {
      pending: "待复核",
      reviewed: "已 Review",
      needs_gt_review: "GT 待复核",
    }[status] || status || "未记录"
  );
}

function analysisRequestOptions() {
  const runId = $("#analysisRunFilter")?.value || "";
  return currentAnalysisRouteOptions({
    runId,
    comparisonStatus: runId ? checkedAnalysisComparisonStatus() : "all",
  });
}

function renderAnalysisClusterList(items, targetSelector, kind) {
  const target = $(targetSelector);
  if (!target) return;
  if (!items.length) {
    target.innerHTML =
      '<div class="analysis-empty">当前筛选范围内还没有可统计的聚类。</div>';
    return;
  }
  const activeValue =
    kind === "evidence"
      ? $("#analysisEvidenceFilter")?.value || ""
      : state.reviewAnalysis.theme || "";
  target.innerHTML = items
    .map((item) => {
      const percentage = Math.round(Number(item.share || 0) * 1000) / 10;
      const width = Math.max(2, Math.min(100, percentage));
      return `<button class="analysis-cluster-row ${activeValue === item.key ? "active" : ""}" type="button"
          data-analysis-cluster-kind="${kind}" data-analysis-cluster-key="${escapeHtml(item.key)}"
          title="${escapeHtml(item.description || item.label)}">
        <span class="analysis-cluster-copy">
          <strong>${escapeHtml(item.label)}</strong>
          <small>${escapeHtml(item.description || "")}</small>
        </span>
        <span class="analysis-cluster-value"><b>${item.count}</b><small>${percentage}%</small></span>
        <span class="analysis-bar-track" aria-hidden="true"><span style="width:${width}%"></span></span>
      </button>`;
    })
    .join("");
  target.querySelectorAll("[data-analysis-cluster-key]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.analysisClusterKind === "evidence") {
        const select = $("#analysisEvidenceFilter");
        select.value = select.value === button.dataset.analysisClusterKey
          ? ""
          : button.dataset.analysisClusterKey;
      } else {
        state.reviewAnalysis.theme =
          state.reviewAnalysis.theme === button.dataset.analysisClusterKey
            ? ""
            : button.dataset.analysisClusterKey;
      }
      state.reviewAnalysis.page = 1;
      showPage("analysis", { historyMode: "push" });
      loadReviewReasonAnalysis().catch((error) => showToast(error.message, true));
    });
  });
}

function renderAnalysisConfusion(data) {
  const target = $("#analysisConfusionMatrix");
  const summary = $("#analysisConfusionSummary");
  if (!target || !summary) return;
  const run = data.scope?.model_run;
  const confusion = data.confusion || {};
  if (!run) {
    summary.textContent = "选择 Model Run 后显示混淆统计";
    target.innerHTML = '<div class="analysis-empty">尚未选择可比较的 Model Run。</div>';
    return;
  }
  summary.textContent =
    `${run.name} · ` +
    `MATCH ${confusion.matches || 0} · ` +
    `MISMATCH ${confusion.mismatches || 0} · ` +
    `NONE ${confusion.none || 0}`;
  const labels = confusion.model_labels || confusion.labels || LABELS;
  if (!confusion.total) {
    target.innerHTML =
      '<div class="analysis-empty">当前 Review 切片没有可统计的模型判断结果。</div>';
    return;
  }
  target.innerHTML = `<table class="analysis-confusion-table">
    <thead><tr><th>GT ↓ / 模型 →</th>${labels
      .map((label) => `<th>${escapeHtml(label)}</th>`)
      .join("")}<th>合计</th></tr></thead>
    <tbody>${(confusion.rows || [])
      .map(
        (row) => `<tr>
          <th>${escapeHtml(row.gt_label)}</th>
          ${(row.cells || [])
            .map(
              (cell) => {
                const cellClass =
                  cell.model_label === "NONE"
                    ? "confusion-none"
                    : cell.model_label === row.gt_label
                      ? "confusion-match"
                      : cell.count
                        ? "confusion-mismatch"
                        : "";
                return `<td class="${cellClass}">${cell.count}</td>`;
              }
            )
            .join("")}
          <td class="confusion-total">${row.total}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

function renderAnalysisCases(data) {
  const target = $("#analysisCaseList");
  const items = data.items || [];
  $("#analysisCaseSummary").textContent =
    `${data.total || 0} 条最新 Review · 当前显示 ${items.length} 条`;
  if (!items.length) {
    target.innerHTML =
      '<div class="analysis-empty">当前筛选下没有 Review 原因明细。</div>';
  } else {
    target.innerHTML = items
      .map((item) => {
        const annotation = item.annotation || {};
        const prediction = item.prediction || {};
        const reasonThemes = item.reason_themes || [];
        const reviewUrl = safeSameOriginReviewUrl(item.review_url);
        const voyagerUrl = safeUrl(item.voyager_issue_url);
        const issueId = escapeHtml(item.issue_id);
        const sceneLabel = item.title || item.scenario || "未填写场景";
        const issueIdMarkup = voyagerUrl
          ? `<a class="analysis-issue-link" href="${escapeHtml(voyagerUrl)}" target="_blank" rel="noreferrer" title="在 Voyager 中打开 ${issueId}">${issueId}</a>`
          : `<strong>${issueId}</strong>`;
        const comparisonStatus = normalizedAnalysisComparisonStatus(
          item.comparison_status,
          ""
        );
        const comparisonMeta = ANALYSIS_COMPARISON_META[comparisonStatus];
        const comparisonBadge = comparisonMeta
          ? `<span class="analysis-comparison-badge comparison-${comparisonStatus}" title="${escapeHtml(comparisonMeta.description)}">${escapeHtml(comparisonMeta.label)}${
              comparisonStatus === "none" ? " · 未预测" : ""
            }</span>`
          : "";
        const confidence =
          prediction.confidence === null || prediction.confidence === undefined
            ? ""
            : ` · ${(Number(prediction.confidence) * 100).toFixed(1)}%`;
        const evidenceChips = (annotation.missing_evidence || [])
          .map(
            (key) =>
              `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`
          )
          .join("");
        const themeChips = reasonThemes
          .map(
            (theme) =>
              `<span class="analysis-chip theme-chip" title="命中：${escapeHtml((theme.matched_keywords || []).join("、"))}">${escapeHtml(theme.label)}</span>`
          )
          .join("");
        return `<article class="analysis-case-row">
          <div class="analysis-case-identity">
            ${issueIdMarkup}
            <span title="${escapeHtml(sceneLabel)}">${escapeHtml(sceneLabel)}</span>
          </div>
          <div class="analysis-case-labels">
            ${comparisonBadge}
            <span title="0508 baseline GT">GT ${labelBadge(item.gt_label)}</span>
            <button class="analysis-model-history-button" type="button"
              data-analysis-model-history="${issueId}"
              title="查看此 Issue 的全部评测 Run 输出历史"
              aria-label="查看 ${issueId} 的评测 Run 输出历史">
              <span>模型</span>${labelBadge(prediction.label, "未输出")}${escapeHtml(confidence)}
            </button>
          </div>
          <div class="analysis-case-reason">
            <strong class="${annotation.note ? "" : "reason-empty"}">${escapeHtml(annotation.note || "未填写“模型为什么判错”")}</strong>
            ${prediction.reason ? `<p>模型说明：${escapeHtml(prediction.reason)}</p>` : ""}
            <div class="analysis-chip-list">${themeChips}${evidenceChips}</div>
          </div>
          <div class="analysis-case-meta">
            <span>${escapeHtml(annotation.author || "未记录复核人")}${annotation.author_verified ? " · SSO" : ""}</span>
            <span>${escapeHtml(reviewStatusLabel(annotation.review_status))} · ${formatTime(annotation.created_at)}</span>
            <span class="analysis-case-actions">
              ${reviewUrl ? `<a class="text-link" href="${escapeHtml(reviewUrl)}" title="打开问题详情与 Review">问题详情</a>` : ""}
            </span>
          </div>
        </article>`;
      })
      .join("");
    target.querySelectorAll("[data-analysis-model-history]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (button.getAttribute("aria-busy") === "true") return;
        button.setAttribute("aria-busy", "true");
        try {
          const caseData = await api(
            `/api/cases/${encodeURIComponent(button.dataset.analysisModelHistory)}`
          );
          openHistoryDialog("model", caseData);
        } catch (error) {
          showToast(error.message, true);
        } finally {
          button.removeAttribute("aria-busy");
        }
      });
    });
  }
  const page = Number(data.page || 1);
  const pageCount = Number(data.page_count || 1);
  $("#analysisPageSummary").textContent = `${page} / ${pageCount}`;
  $("#analysisPagePrevious").disabled = page <= 1;
  $("#analysisPageNext").disabled = page >= pageCount;
}

function renderReviewReasonAnalysis(data) {
  const summary = data.summary || {};
  state.reviewAnalysis.page = Number(data.page || 1);
  $("#analysisReviewCount").textContent = summary.latest_reviews ?? 0;
  $("#analysisReasonCount").textContent = summary.with_reason ?? 0;
  $("#analysisEmptyReasonCount").textContent = `${summary.empty_reason ?? 0} 条未填写`;
  $("#analysisEvidenceCount").textContent = summary.with_structured_evidence ?? 0;
  $("#analysisUnclusteredCount").textContent = summary.unclustered_reason ?? 0;
  const run = data.scope?.model_run;
  const comparisonStatus = normalizedAnalysisComparisonStatus(
    data.scope?.comparison_status,
    "all"
  );
  const comparisonMeta = ANALYSIS_COMPARISON_META[comparisonStatus];
  $("#analysisReviewScope").textContent = run
    ? `${run.name}${comparisonStatus === "all" ? "" : ` · ${comparisonMeta.label}`}`
    : "全部最新 Review";
  renderAnalysisClusterList(
    data.evidence_clusters || [],
    "#analysisEvidenceClusters",
    "evidence"
  );
  renderAnalysisClusterList(
    data.reason_clusters || [],
    "#analysisReasonClusters",
    "theme"
  );
  renderAnalysisConfusion(data);
  renderAnalysisCases(data);
}

async function loadReviewReasonAnalysis() {
  const requestSeq = ++state.reviewAnalysis.requestSeq;
  const options = analysisRequestOptions();
  const params = new URLSearchParams();
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? normalizedAnalysisComparisonStatus(options.comparisonStatus)
      : "all"
  );
  if (options.annotationAuthor) params.set("annotation_author", options.annotationAuthor);
  if (options.reviewStatus) params.set("review_status", options.reviewStatus);
  if (options.gtLabel) params.set("gt_label", options.gtLabel);
  if (options.annotationLabel) params.set("annotation_label", options.annotationLabel);
  if (options.missingEvidence) params.set("missing_evidence", options.missingEvidence);
  if (options.theme) params.set("theme", options.theme);
  if (options.tag) params.set("tag", options.tag);
  if (options.search) params.set("search", options.search);
  params.set("page", String(Math.max(1, Number(options.page) || 1)));
  params.set("page_size", String(state.reviewAnalysis.pageSize));
  $("#analysisCaseSummary").textContent = "正在加载最新 Review…";
  const data = await api(`/api/review-reason-analysis?${params.toString()}`);
  if (requestSeq !== state.reviewAnalysis.requestSeq) return;
  state.reviewAnalysis.data = data;
  renderReviewReasonAnalysis(data);
}

function downloadReviewAnalysis(format) {
  const options = analysisRequestOptions();
  const params = new URLSearchParams({ format });
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? normalizedAnalysisComparisonStatus(options.comparisonStatus)
      : "all"
  );
  if (options.annotationAuthor) params.set("annotation_author", options.annotationAuthor);
  if (options.reviewStatus) params.set("review_status", options.reviewStatus);
  if (options.gtLabel) params.set("gt_label", options.gtLabel);
  if (options.annotationLabel) params.set("annotation_label", options.annotationLabel);
  if (options.missingEvidence) params.set("missing_evidence", options.missingEvidence);
  if (options.theme) params.set("theme", options.theme);
  if (options.tag) params.set("tag", options.tag);
  if (options.search) params.set("search", options.search);
  const link = document.createElement("a");
  link.href = withBase(`/api/review-reason-analysis/export?${params.toString()}`);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function applyAnalysisComparisonSelection() {
  const previousRunId = state.selectedRunId;
  const previousFailureOnly = state.failureOnly;
  const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
  const runId = $("#analysisRunFilter").value;
  state.selectedRunId = state.modelRuns.some((run) => run.id === runId) ? runId : "";
  state.reviewAnalysis.comparisonStatus = state.selectedRunId
    ? checkedAnalysisComparisonStatus()
    : "all";
  state.failureOnly = Boolean(
    state.selectedRunId &&
      state.reviewAnalysis.comparisonStatus === "mismatch"
  );
  if (
    previousRunId !== state.selectedRunId ||
    previousFailureOnly !== state.failureOnly ||
    previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
  ) {
    state.reviewQueueStale = true;
  }
  $("#modelRunFilter").value = state.selectedRunId;
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  renderActiveRun();
  renderRunManager();
}

async function reloadReviewAnalysis({ historyMode = "push" } = {}) {
  applyAnalysisComparisonSelection();
  showPage("analysis", { historyMode });
  await Promise.all([loadReviewReasonAnalysis(), loadOverview()]);
}

async function changeAnalysisPage(delta) {
  const data = state.reviewAnalysis.data || {};
  const target = Math.max(
    1,
    Math.min(Number(data.page_count || 1), state.reviewAnalysis.page + delta)
  );
  if (target === state.reviewAnalysis.page) return;
  state.reviewAnalysis.page = target;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

function clearDetail({ showGallery = true } = {}) {
  state.selectedId = "";
  state.selectedCase = null;
  state.caseRequestSeq += 1;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>正在准备 Issue 详情</h2>
      <p>从筛选结果中打开一个 Issue 后，这里会显示 BEV / Camera 与模型输出。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
  renderCaseNavigation();
  if (showGallery) setReviewView("");
}

function heroFrameIndex(frames) {
  const exact = frames.findIndex((frame) => Number(frame.offset_ms ?? frame.offset_sec * 1000) === 0);
  if (exact >= 0) return exact;
  return Math.floor(frames.length / 2);
}

function videoPlayerMarkup(video, { zoomable = true, compact = false, posterUrl = "" } = {}) {
  const durationSec = Math.max(0, Number(video?.duration_ms || 0) / 1000);
  const startOffsetSec = Number(video?.start_offset_sec ?? 0);
  const eventTimeSec = Number(video?.event_time_sec ?? Math.max(0, -startOffsetSec));
  const frameStepSec = Math.max(0.01, Number(video?.frame_step_ms || 100) / 1000);
  const stepOptions = [...new Set([frameStepSec, 0.5, 1, 5])]
    .sort((left, right) => left - right)
    .map((step) => `<option value="${escapeHtml(step)}" ${step === 1 ? "selected" : ""}>${escapeHtml(step)}s${step === frameStepSec ? "（1 帧）" : ""}</option>`)
    .join("");
  const posterAttribute = posterUrl ? ` poster="${escapeHtml(posterUrl)}"` : "";
  const videoMarkup = `<video src="${escapeHtml(video.url)}"${posterAttribute} preload="metadata" playsinline draggable="false" aria-label="Ares Studio BEV 视频"></video>`;
  const mediaMarkup = zoomable
    ? `<div class="media-viewport media-video-viewport" data-video-viewport><div class="media-canvas media-video-canvas" data-video-canvas>${videoMarkup}</div></div>`
    : `<div class="hero-media-button hero-media-video">${videoMarkup}</div>`;
  return `<div class="hero-video-player ${compact ? "is-compact" : ""}" data-bev-video-player
      data-start-offset-sec="${escapeHtml(startOffsetSec)}"
      data-event-time-sec="${escapeHtml(eventTimeSec)}"
      data-duration-sec="${escapeHtml(durationSec)}"
      data-frame-step-sec="${escapeHtml(frameStepSec)}">
    ${mediaMarkup}
    <div class="bev-video-controls" aria-label="BEV 视频控制">
      <div class="bev-video-control-row">
        <button class="button button-quiet" type="button" data-video-play>播放</button>
        <button class="button button-quiet" type="button" data-video-jump="-1"><span data-video-jump-label>−1s</span></button>
        <button class="button button-quiet" type="button" data-video-t0>回到 t0</button>
        <button class="button button-quiet" type="button" data-video-jump="1"><span data-video-jump-label>+1s</span></button>
        <label>跳转步长
          <select data-video-step>
            ${stepOptions}
          </select>
        </label>
        <label>倍速
          <select data-video-rate>
            <option value="0.5">0.5×</option>
            <option value="1" selected>1×</option>
            <option value="1.5">1.5×</option>
            <option value="2">2×</option>
          </select>
        </label>
      </div>
      <div class="bev-video-progress-row">
        <span data-video-relative-start>${escapeHtml(formatSignedSeconds(startOffsetSec))}</span>
        <input data-video-seek type="range" min="0" max="${escapeHtml(durationSec || 40)}" value="0" step="0.01" aria-label="视频进度" />
        <span data-video-time>${escapeHtml(formatSignedSeconds(startOffsetSec))} / ${escapeHtml(formatSignedSeconds(startOffsetSec + durationSec))}</span>
      </div>
    </div>
  </div>`;
}

function formatSignedSeconds(value) {
  const seconds = Number(value || 0);
  if (Math.abs(seconds) < 0.05) return "t0";
  return `${seconds > 0 ? "+" : ""}${seconds.toFixed(1)}s`;
}

function bindBevVideoPlayers(root) {
  root.querySelectorAll("[data-bev-video-player]").forEach((player) => {
    const video = player.querySelector("video");
    const playButton = player.querySelector("[data-video-play]");
    const seek = player.querySelector("[data-video-seek]");
    const stepSelect = player.querySelector("[data-video-step]");
    const rateSelect = player.querySelector("[data-video-rate]");
    const timeLabel = player.querySelector("[data-video-time]");
    const startLabel = player.querySelector("[data-video-relative-start]");
    const startOffsetSec = Number(player.dataset.startOffsetSec || 0);
    const eventTimeSec = Number(player.dataset.eventTimeSec || 0);
    const configuredDuration = Number(player.dataset.durationSec || 0);
    const duration = () => Number.isFinite(video.duration) ? video.duration : configuredDuration;
    const update = () => {
      const total = Math.max(0, duration());
      seek.max = String(total || configuredDuration || 40);
      seek.value = String(Math.min(Number(seek.max), Math.max(0, video.currentTime || 0)));
      startLabel.textContent = formatSignedSeconds(startOffsetSec);
      timeLabel.textContent = `${formatSignedSeconds(startOffsetSec + (video.currentTime || 0))} / ${formatSignedSeconds(startOffsetSec + total)}`;
      playButton.textContent = video.paused ? "播放" : "暂停";
    };
    const jump = (direction) => {
      const step = Math.max(0.01, Number(stepSelect.value || 1));
      video.currentTime = Math.min(
        Math.max(0, duration()),
        Math.max(0, video.currentTime + direction * step)
      );
      update();
    };
    const togglePlayback = () => {
      if (video.paused) {
        video.play().catch((error) => showToast(`视频播放失败：${error.message}`, true));
      } else {
        video.pause();
      }
    };
    playButton.addEventListener("click", togglePlayback);
    video.addEventListener("click", togglePlayback);
    player.querySelectorAll("[data-video-jump]").forEach((button) => {
      button.addEventListener("click", () => jump(Number(button.dataset.videoJump)));
    });
    player.querySelector("[data-video-t0]").addEventListener("click", () => {
      video.currentTime = Math.min(Math.max(0, duration()), Math.max(0, eventTimeSec));
      update();
    });
    stepSelect.addEventListener("change", () => {
      const step = Number(stepSelect.value || 1);
      player.querySelectorAll("[data-video-jump]").forEach((button) => {
        const sign = Number(button.dataset.videoJump) < 0 ? "−" : "+";
        button.querySelector("[data-video-jump-label]").textContent = `${sign}${step}s`;
      });
    });
    rateSelect.addEventListener("change", () => {
      video.playbackRate = Number(rateSelect.value || 1);
    });
    seek.addEventListener("input", () => {
      video.currentTime = Number(seek.value || 0);
      update();
    });
    ["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended"].forEach(
      (eventName) => video.addEventListener(eventName, update)
    );
    player.addEventListener("keydown", (event) => {
      if (event.target.matches("select, input")) {
        event.stopPropagation();
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        event.stopPropagation();
        jump(event.key === "ArrowLeft" ? -1 : 1);
      } else if (event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        togglePlayback();
      }
    });
    player.tabIndex = 0;
    update();
  });
}

function ensureDetailMediaState(caseData) {
  const issueId = String(caseData?.issue_id || "");
  const available = {
    bev: Boolean(caseData?.assets?.frames?.length),
    camera: Boolean(caseData?.camera?.frames?.length),
    video: Boolean(caseData?.assets?.video?.url),
  };
  if (state.detailMedia.issueId !== issueId) {
    state.detailMedia = {
      issueId,
      kind: preferredMediaKind(caseData),
      indexes: {
        bev: heroFrameIndex(caseData?.assets?.frames || []),
        camera: heroFrameIndex(caseData?.camera?.frames || []),
      },
      loadSeq: 0,
    };
  }
  if (!available[state.detailMedia.kind]) state.detailMedia.kind = preferredMediaKind(caseData);
  return available;
}

function heroMediaSection(caseData) {
  const frames = caseData?.assets?.frames || [];
  const video = caseData?.assets?.video;
  const camera = caseData?.camera?.frames || [];
  if (!frames.length && !camera.length && !video?.url) {
    return '<section class="hero-media"><div class="no-asset hero-media-placeholder"><span>当前没有可预览的 BEV、Camera 或视频。</span></div></section>';
  }
  ensureDetailMediaState(caseData);
  const kind = state.detailMedia.kind;
  const activeFrames = kind === "camera" ? camera : frames;
  const index = Math.max(0, Math.min(
    Number(state.detailMedia.indexes[kind] || 0),
    Math.max(activeFrames.length - 1, 0)
  ));
  if (kind !== "video") state.detailMedia.indexes[kind] = index;
  const frame = activeFrames[index];
  const content = kind === "video" && video?.url
    ? videoPlayerMarkup(video, {
        zoomable: false,
        compact: true,
        posterUrl: frames[heroFrameIndex(frames)]?.url || "",
      })
    : `<button type="button" class="hero-media-button" data-detail-media-expand aria-label="展开${kind === "camera" ? " Camera" : " BEV"}媒体预览">
        <img class="detail-media-image" src="${escapeHtml(frame?.url || "")}" alt="${kind === "camera" ? "Camera" : "Ares Capture BEV"} ${escapeHtml(frameLabel(frame || {}))}" />
        <span class="hero-media-overlay">${escapeHtml(frameLabel(frame || {}))} · 点击展开</span>
      </button>`;
  const frameControls = kind === "video" ? "" : `
    <div class="detail-media-frame-controls" aria-label="图片帧切换">
      <button class="button button-quiet" id="detailMediaPreviousButton" type="button" aria-label="上一帧">←</button>
      <span class="detail-media-position" id="detailMediaPosition">${activeFrames.length ? `${index + 1} / ${activeFrames.length}` : "—"}</span>
      <button class="button button-quiet" id="detailMediaNextButton" type="button" aria-label="下一帧">→</button>
    </div>`;
  return `
    <section class="hero-media detail-hero-media" id="detailHeroMedia" tabindex="0" aria-label="Issue 媒体">
      <div class="detail-media-content">${content}</div>
      ${frameControls}
      <p class="detail-media-help">B / C / V 切换媒体 · ${kind === "video" ? "空格播放/暂停 · ←/→ 跳转" : "←/→ 切帧"} · F 展开查看</p>
    </section>`;
}

function preloadDetailImage(caseData, kind, index, root, onReady) {
  const issueId = String(caseData?.issue_id || "");
  const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
  const frame = frames[index];
  const url = frame?.url;
  if (!issueId || !url || !root) return;
  const requestSeq = Number(state.detailMedia.loadSeq || 0) + 1;
  state.detailMedia.loadSeq = requestSeq;
  root.setAttribute("aria-busy", "true");
  root.querySelectorAll("#detailMediaPreviousButton, #detailMediaNextButton").forEach((control) => {
    control.disabled = true;
  });
  const image = new Image();
  image.decoding = "async";
  let settled = false;
  const isCurrent = () => (
    requestSeq === state.detailMedia.loadSeq &&
    root.isConnected &&
    state.detailMedia.issueId === issueId &&
    state.selectedId === issueId &&
    String(state.selectedCase?.issue_id || "") === issueId
  );
  const finish = (loaded) => {
    if (settled) return;
    settled = true;
    if (!isCurrent()) return;
    root.removeAttribute("aria-busy");
    root.querySelectorAll("#detailMediaPreviousButton, #detailMediaNextButton").forEach((control) => {
      control.disabled = false;
    });
    if (loaded) onReady(image);
    else showToast("媒体图片加载失败，已保留当前画面。", true);
  };
  image.onload = () => {
    let decoded;
    try {
      decoded = typeof image.decode === "function" ? image.decode() : Promise.resolve();
    } catch {
      decoded = Promise.resolve();
    }
    Promise.resolve(decoded).catch(() => {}).then(() => finish(true));
  };
  image.onerror = () => finish(false);
  image.src = url;
}

function applyDetailImageFrame(root, caseData, kind, index, loadedImage = null) {
  const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
  const frame = frames[index];
  const image = root?.querySelector(".detail-media-image");
  const button = root?.querySelector("[data-detail-media-expand]");
  const overlay = root?.querySelector(".hero-media-overlay");
  if (!frame?.url || !image || !button || !overlay) return false;
  const nextImage = loadedImage || image;
  nextImage.className = "detail-media-image";
  nextImage.alt = `${kind === "camera" ? "Camera" : "Ares Capture BEV"} ${frameLabel(frame)}`;
  nextImage.decoding = "async";
  nextImage.draggable = false;
  nextImage.style.transition = "none";
  nextImage.style.animation = "none";
  nextImage.style.opacity = "1";
  if (nextImage !== image) {
    // Keep the current frame above the already-decoded next frame until the
    // browser has had two rendering opportunities.  One requestAnimationFrame
    // callback runs before paint and is not a guarantee that a large image has
    // reached the compositor yet.
    nextImage.style.position = "absolute";
    nextImage.style.inset = "0";
    nextImage.style.zIndex = "0";
    nextImage.style.visibility = "visible";
    image.style.position = "absolute";
    image.style.inset = "0";
    image.style.zIndex = "1";
    overlay.style.zIndex = "2";
    image.before(nextImage);
    const commit = () => {
      if (!nextImage.isConnected) return;
      nextImage.style.zIndex = "1";
      image.remove();
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => window.requestAnimationFrame(commit));
    } else commit();
  } else {
    nextImage.src = frame.url;
  }
  button.setAttribute("aria-label", `展开${kind === "camera" ? " Camera" : " BEV"}媒体预览`);
  overlay.textContent = `${frameLabel(frame)} · 点击展开`;
  const position = root.querySelector("#detailMediaPosition");
  if (position) position.textContent = `${index + 1} / ${frames.length}`;
  const kindSelect = root.querySelector("#detailMediaKindSelect");
  if (kindSelect) kindSelect.value = kind;
  return true;
}

function detailMediaCommandMarkup(caseData) {
  const available = ensureDetailMediaState(caseData);
  const kind = state.detailMedia.kind;
  return `<div class="detail-media-command" aria-label="详情媒体控制">
    <select class="detail-media-select" id="detailMediaKindSelect" aria-label="媒体类型">
      <option value="bev" ${available.bev ? "" : "disabled"} ${kind === "bev" ? "selected" : ""}>BEV 图片 · ${caseData?.assets?.frames?.length || 0}</option>
      <option value="camera" ${available.camera ? "" : "disabled"} ${kind === "camera" ? "selected" : ""}>Camera 图片 · ${caseData?.camera?.frames?.length || 0}</option>
      <option value="video" ${available.video ? "" : "disabled"} ${kind === "video" ? "selected" : ""}>Ares Studio 视频 · ${available.video ? 1 : 0}</option>
    </select>
    <button class="button button-quiet detail-media-expand" id="detailMediaExpandButton" type="button">展开查看</button>
  </div>`;
}

function bindDetailMedia(caseData) {
  const root = $("#detailHeroMedia");
  if (!root) return;
  const render = () => {
    root.outerHTML = heroMediaSection(caseData);
    bindDetailMedia(caseData);
  };
  const switchKind = (kind) => {
    const available = kind === "video"
      ? Boolean(caseData?.assets?.video?.url)
      : Boolean((kind === "camera" ? caseData?.camera?.frames : caseData?.assets?.frames)?.length);
    if (!available || state.detailMedia.kind === kind) return;
    root.querySelector("video")?.pause();
    if (kind === "video") {
      state.detailMedia.loadSeq += 1;
      state.detailMedia.kind = kind;
      render();
      return;
    }
    const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    const index = Math.max(0, Math.min(
      Number(state.detailMedia.indexes[kind] || 0),
      Math.max(frames.length - 1, 0)
    ));
    preloadDetailImage(caseData, kind, index, root, (loadedImage) => {
      state.detailMedia.kind = kind;
      state.detailMedia.indexes[kind] = index;
      if (!applyDetailImageFrame(root, caseData, kind, index, loadedImage)) render();
    });
  };
  const move = (delta) => {
    const kind = state.detailMedia.kind;
    if (kind === "video") return;
    const frames = kind === "camera" ? caseData?.camera?.frames || [] : caseData?.assets?.frames || [];
    if (!frames.length) return;
    const nextIndex = (Number(state.detailMedia.indexes[kind] || 0) + delta + frames.length) % frames.length;
    preloadDetailImage(caseData, kind, nextIndex, root, (loadedImage) => {
      state.detailMedia.indexes[kind] = nextIndex;
      if (!applyDetailImageFrame(root, caseData, kind, nextIndex, loadedImage)) render();
    });
  };
  const expand = () => openMedia(
    state.detailMedia.kind,
    state.detailMedia.kind === "video" ? 0 : state.detailMedia.indexes[state.detailMedia.kind],
    { caseData }
  );
  const kindSelect = $("#detailMediaKindSelect");
  if (kindSelect) {
    kindSelect.value = state.detailMedia.kind;
    kindSelect.onchange = () => switchKind(kindSelect.value);
  }
  const previousButton = $("#detailMediaPreviousButton");
  const nextButton = $("#detailMediaNextButton");
  const position = $("#detailMediaPosition");
  const videoMode = state.detailMedia.kind === "video";
  if (previousButton) {
    previousButton.hidden = videoMode;
    previousButton.onclick = () => move(-1);
  }
  if (nextButton) {
    nextButton.hidden = videoMode;
    nextButton.onclick = () => move(1);
  }
  if (position) {
    const activeFrames = state.detailMedia.kind === "camera"
      ? caseData?.camera?.frames || []
      : caseData?.assets?.frames || [];
    const activeIndex = Number(state.detailMedia.indexes[state.detailMedia.kind] || 0);
    position.hidden = videoMode;
    position.textContent = activeFrames.length ? `${activeIndex + 1} / ${activeFrames.length}` : "—";
  }
  const expandButton = $("#detailMediaExpandButton");
  if (expandButton) expandButton.onclick = expand;
  root.querySelectorAll("[data-detail-media-expand]").forEach((button) => button.addEventListener("click", expand));
  bindBevVideoPlayers(root);
}

function predictionCards(caseData) {
  const predictions = caseData.predictions || [];
  if (!predictions.length) {
    return '<div class="no-asset">当前 case 没有 Run 模型输出。可创建 Trail 只读快照、上传批量结果，或等待 Batch 预测生成新的 Run。</div>';
  }
  return `<div class="model-list">${predictions
    .map((prediction) => {
      const selected = prediction.model_run_id === state.selectedRunId;
      const extra = prediction.model_extra?.ra_stuck_auto_result_info;
      const detail = prediction.model_reason || (typeof extra === "object" ? extra.text || "" : "") || "模型未返回解释。";
      return `<article class="model-card ${selected ? "active" : ""}">
        <div class="model-card-head"><div><h3>${escapeHtml(prediction.run_name || "模型输出")}</h3></div>${labelBadge(prediction.model_label, "未输出")}</div>
        <p>${escapeHtml(detail)}</p>
        <div class="model-card-meta">${prediction.model_confidence ?? "—"} confidence · ${formatTime(prediction.created_at)}${prediction.run_created_by ? ` · 创建人 ${escapeHtml(prediction.run_created_by)}` : ""}</div>
      </article>`;
    })
    .join("")}</div>`;
}

function openHistoryDialog(kind, caseData) {
  if (!caseData) return;
  const isModel = kind === "model";
  const predictions = caseData.predictions || [];
  const annotations = caseData.annotations || [];
  $("#historyDialogTitle").textContent = isModel ? "评测 Run 输出历史" : "Review 历史";
  $("#historyDialogMeta").textContent = isModel
    ? `${predictions.length} 个模型 Run · 当前 Review Run 会高亮`
    : `${annotations.length} 条历史 Review · 追加式，不覆盖旧记录`;
  $("#historyDialogContent").innerHTML = isModel
    ? predictionCards(caseData)
    : annotationHistory(annotations);
  if (!isModel) bindAnnotationHistory($("#historyDialogContent"), caseData);
  openDialog("historyDialog");
}

function formatRaEventTimestamp(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "—";
  const date = new Date(numeric);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { hour12: false });
}

function renderRaEventRows(events, query = "") {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  const rows = (Array.isArray(events) ? events : []).filter((item) => {
    if (!normalizedQuery) return true;
    return [item?.event, item?.value]
      .map((value) => String(value ?? "").toLowerCase())
      .some((value) => value.includes(normalizedQuery));
  });
  const body = $("#raEventTableBody");
  if (body) {
    body.innerHTML = rows
      .map((item) => {
        const timestamp = item?.timestamp;
        return `<tr>
          <td>${escapeHtml(item?.event || "—")}</td>
          <td>${escapeHtml(item?.value ?? "—")}</td>
          <td class="ra-event-timestamp">${escapeHtml(timestamp ?? "—")}</td>
          <td>${escapeHtml(formatRaEventTimestamp(timestamp))}</td>
        </tr>`;
      })
      .join("");
  }
  const empty = $("#raEventEmpty");
  if (empty) empty.hidden = rows.length > 0;
  return rows.length;
}

function openRaEventDialog(caseData) {
  if (!caseData) return;
  const externalLinks = caseData.external_links || {};
  const events = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  state.raEventDialog = {
    issueId: String(caseData.issue_id || ""),
    events,
    trailUrl: safeUrl(externalLinks.ra_event_url),
  };
  const input = $("#raEventSearchInput");
  if (input) input.value = "";
  const meta = $("#raEventDialogMeta");
  if (meta) meta.textContent = `${events.length} 条 · ${caseData.issue_id || "当前 Issue"}`;
  const trailLink = $("#raEventTrailLink");
  if (trailLink) {
    trailLink.hidden = !state.raEventDialog.trailUrl;
    trailLink.href = state.raEventDialog.trailUrl || "#";
  }
  renderRaEventRows(events);
  openDialog("raEventDialog");
}

function detailExternalLinksMarkup(caseData) {
  const issueUrl = safeUrl(caseData?.voyager_issue_url || caseData?.trail_url);
  const aresUrl = aresStudioUrl(caseData, issueUrl);
  const externalLinks = caseData?.external_links || {};
  const raRecordingUrl = safeUrl(externalLinks.ra_recording_url);
  const raEventUrl = safeUrl(externalLinks.ra_event_url);
  const raEvents = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  const aresLinkMarkup = aresUrl
    ? "<a class=\"detail-id detail-id-link detail-ares-link\" href=\"" + escapeHtml(aresUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Ares Studio 中打开事件前后各 10 秒\">Ares Studio ↗</a>"
    : "";
  const raRecordingLinkMarkup = raRecordingUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raRecordingUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开 RA 录屏" + (externalLinks.ra_task_id ? "：" + escapeHtml(externalLinks.ra_task_id) : "") + "\">RA 录屏 ↗</a>"
    : "";
  const raEventLinkMarkup = raEvents.length
    ? "<button class=\"detail-id detail-id-link detail-external-link detail-inline-button\" type=\"button\" data-open-ra-event title=\"查看 RA Event（" + raEvents.length + " 条）\">RA Event · " + raEvents.length + "</button>"
    : raEventUrl
      ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raEventUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Trail Issue 中查看 RA Event（" + Number(externalLinks.ra_event_count || 0) + " 条）\">RA Event ↗</a>"
      : "";
  const pending = caseData?.trail_metadata_status === "pending" && !raRecordingUrl && !raEventUrl;
  const pendingMarkup = pending
    ? '<span class="detail-external-status" data-trail-metadata-pending>Trail 信息加载中…</span>'
    : "";
  return aresLinkMarkup + raRecordingLinkMarkup + raEventLinkMarkup + pendingMarkup;
}

function bindDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  root?.querySelector("[data-open-ra-event]")?.addEventListener("click", () => {
    openRaEventDialog(caseData);
  });
}

function renderDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  if (!root) return;
  root.innerHTML = detailExternalLinksMarkup(caseData);
  bindDetailExternalLinks(caseData);
}

async function loadTrailDetailMetadata(issueId, requestSeq) {
  try {
    const result = await api(
      "/api/cases/" + encodeURIComponent(issueId) + "/trail-metadata"
    );
    if (
      requestSeq !== state.caseRequestSeq ||
      state.selectedId !== issueId ||
      !state.selectedCase
    ) {
      return;
    }
    state.selectedCase.external_links = result.external_links || {};
    state.selectedCase.trail_metadata_status = result.status || "unavailable";
    renderDetailExternalLinks(state.selectedCase);
  } catch {
    if (
      requestSeq !== state.caseRequestSeq ||
      state.selectedId !== issueId ||
      !state.selectedCase
    ) {
      return;
    }
    state.selectedCase.trail_metadata_status = "unavailable";
    renderDetailExternalLinks(state.selectedCase);
  }
}

function scheduleTrailDetailMetadata(issueId, requestSeq) {
  const start = () => {
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) {
      return;
    }
    void loadTrailDetailMetadata(issueId, requestSeq);
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(start, { timeout: 1500 });
  } else {
    window.setTimeout(start, 180);
  }
}

function renderDetail(caseData) {
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdMarkup = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  ensureDetailMediaState(caseData);
  const modelHistoryButton = `<button class="history-inline-button" type="button" data-open-history="model">评测 Run 历史 · ${(caseData.predictions || []).length} 条</button>`;
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title-group">
          <div class="detail-title"><h2><span class="ui-lang-zh">问题详情</span><span class="ui-lang-en">Issue Details</span></h2>${issueIdMarkup}<span id="detailExternalLinks" class="detail-external-links">${detailExternalLinksMarkup(caseData)}</span></div>
        </div>
        <div class="detail-navigation">
          <div class="case-detail-pager">
            <button class="button button-quiet" id="previousIssueButton" type="button">← 上一 Issue</button>
            <span id="detailQueuePosition">— / —</span>
            <button class="button button-quiet" id="nextIssueButton" type="button">下一 Issue →</button>
          </div>
        </div>
      </div>
      <div class="detail-context-row">
        <div class="comparison-summary" aria-label="GT 与当前模型对比">
          <span>GT</span>${labelBadge(caseData.gt_label, "缺失")}
          <b aria-hidden="true">→</b>
          <span>当前模型</span>${labelBadge(primary?.model_label, "未输出")}
          <strong class="${primary?.model_label && primary.model_label !== caseData.gt_label ? "comparison-fail" : "comparison-neutral"}">${primary?.model_label ? primary.model_label === caseData.gt_label ? "一致" : "不一致" : "不可比较"}</strong>
        </div>
        <button class="button button-quiet detail-back-button" id="backToGalleryButton" type="button">← 返回筛选结果</button>
        ${caseData.summary ? `<p class="detail-summary">${escapeHtml(caseData.summary)}</p>` : ""}
        <div class="detail-context-actions">
          ${detailMediaCommandMarkup(caseData)}
          <div class="detail-actions">
            <button class="button button-quiet" type="button" data-predict-current-case>API 推理</button>
            ${modelHistoryButton}
          </div>
        </div>
      </div>
      ${caseData.review_note ? `<details class="review-note-details"><summary>查看历史备注</summary><div class="review-note"><span>历史备注</span>${escapeHtml(caseData.review_note)}</div></details>` : ""}
    </div>
    ${heroMediaSection(caseData)}`;
  $("#detailPane").querySelector("[data-predict-current-case]")?.addEventListener("click", () => {
    openBatchDraft([caseData.issue_id], "single");
  });
  $("#detailPane").querySelector("[data-open-history='model']")?.addEventListener("click", () => {
    openHistoryDialog("model", caseData);
  });
  bindDetailExternalLinks(caseData);
  $("#detailPane").querySelector("#backToGalleryButton")?.addEventListener("click", returnToReviewGallery);
  $("#detailPane").querySelector("#previousIssueButton")?.addEventListener("click", () => {
    navigateAdjacentCase(-1).catch((error) => showToast(error.message, true));
  });
  $("#detailPane").querySelector("#nextIssueButton")?.addEventListener("click", () => {
    navigateAdjacentCase(1).catch((error) => showToast(error.message, true));
  });
  renderCaseNavigation();
  bindDetailMedia(caseData);
}

function annotationHistory(annotations) {
  if (!annotations?.length) return '<p class="muted history-empty">尚无人工 review；保存后会保留旧版本。</p>';
  return annotations
    .map(
      (annotation) => `<article class="history-row">
        <div class="history-head">
          ${labelBadge(annotation.label, annotation.review_status === "needs_gt_review" ? "GT 待复核" : "已记录")}
          <span class="history-reviewer" title="${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}` : "复核人：历史记录未填写")}">${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO" : " · 未验证"}` : "复核人：未记录")}</span>
          <span class="history-actions"><span class="history-time">${formatTime(annotation.created_at)}</span><button class="history-delete-button" type="button" data-delete-annotation="${escapeHtml(annotation.id)}" title="删除这条 Review 版本" aria-label="删除 ${escapeHtml(formatTime(annotation.created_at))} 的 Review 版本"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 3h4l1 2H7zM6 6l.7 11h6.6L14 6M8.5 9v5m3-5v5"/></svg></button></span>
        </div>
        ${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map((key) => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
        ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map((tag) => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>` : ""}
        ${annotation.attachments?.length ? `<div class="history-attachments">${annotation.attachments.map((attachment, index) => `<a href="${escapeHtml(attachment.url)}" target="_blank" rel="noreferrer" title="打开补充截图 ${index + 1}"><img src="${escapeHtml(attachment.url)}" alt="补充截图 ${index + 1}" loading="lazy" /></a>`).join("")}</div>` : ""}
        ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}
      </article>`)
    .join("");
}

function bindAnnotationHistory(root, caseData) {
  if (!root || !caseData) return;
  root.querySelectorAll("[data-delete-annotation]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteAnnotationVersion(caseData, button.dataset.deleteAnnotation, button);
    });
  });
}

function updateReviewHistory(caseData) {
  if (!caseData || state.selectedId !== caseData.issue_id) return;
  const annotations = caseData.annotations || [];
  const reviewPane = $("#reviewPane");
  const content = reviewPane?.querySelector(".review-history-content");
  const count = reviewPane?.querySelector(".history-launch-meta");
  if (content) {
    content.innerHTML = annotationHistory(annotations);
    bindAnnotationHistory(content, caseData);
  }
  if (count) count.textContent = `${annotations.length} 条`;
  const dialog = $("#historyDialog");
  const dialogContent = $("#historyDialogContent");
  if (
    dialog?.open &&
    dialogContent &&
    $("#historyDialogTitle")?.textContent === "Review 历史"
  ) {
    dialogContent.innerHTML = annotationHistory(annotations);
    bindAnnotationHistory(dialogContent, caseData);
  }
}

function refreshReviewDerivedData() {
  void Promise.allSettled([
    loadOverview(),
    loadClusters(),
    loadCases(),
    loadReviewers(),
  ]);
}

function syncReviewFormFromCase(caseData) {
  const reviewPane = $("#reviewPane");
  if (!reviewPane?.querySelector("#annotationForm")) {
    renderReview(caseData);
    return;
  }
  const previous = caseData.annotations?.[0] || {};
  const hasPreviousReview = Boolean(caseData.annotations?.length);
  const chosenEvidence = new Set(
    hasPreviousReview ? previous.missing_evidence || [] : ["routing_direction"]
  );
  const chosenTags = new Set(previous.tags || []);
  const evidenceCatalog = state.config?.missing_evidence_catalog || [];
  const tagCatalog = state.config?.review_tag_catalog || [];
  const evidenceKeys = new Set(evidenceCatalog.map((item) => item.key));
  const tagKeys = new Set(tagCatalog.map((item) => item.key));

  reviewPane.querySelectorAll(".custom-evidence-option").forEach((node) => node.remove());
  reviewPane.querySelectorAll(".custom-tag-option").forEach((node) => node.remove());
  const evidenceCreator = $("#customEvidenceCreator");
  for (const key of chosenEvidence) {
    if (evidenceKeys.has(key) || !evidenceCreator) continue;
    const option = document.createElement("label");
    option.className = "evidence-option custom-evidence-option";
    option.title = "本条 Review 新建的缺失信息";
    option.innerHTML = `<input type="checkbox" name="missingEvidence" value="${escapeHtml(key)}" checked /><span><strong>${escapeHtml(evidenceLabel(key))}</strong><small>本条 Review 新建的缺失信息</small></span>`;
    evidenceCreator.before(option);
    option.querySelector("input")?.addEventListener("change", updateEvidenceSummary);
  }
  const tagCreator = $("#customTagCreator");
  for (const key of chosenTags) {
    if (tagKeys.has(key) || !tagCreator) continue;
    const option = document.createElement("label");
    option.className = "tag-option custom-tag-option";
    option.innerHTML = `<input type="checkbox" name="reviewTags" value="${escapeHtml(key)}" checked /><span>${escapeHtml(tagLabel(key))}</span>`;
    tagCreator.before(option);
    option.querySelector("input")?.addEventListener("change", updateTagSummary);
  }
  reviewPane.querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.checked = chosenEvidence.has(input.value);
  });
  reviewPane.querySelectorAll('input[name="reviewTags"]').forEach((input) => {
    input.checked = chosenTags.has(input.value);
  });
  const status = $("#reviewStatusInput");
  if (status) {
    status.value = previous.review_status === "needs_gt_review"
      ? "needs_gt_review"
      : previous.review_status === "pending"
        ? "pending"
        : "reviewed";
  }
  const note = $("#annotationNote");
  if (note) note.value = previous.note || "";
  const author = $("#annotationAuthor");
  if (author && !(state.session.verified && state.session.username)) {
    author.value = state.session.username || previous.author || "";
  }
  state.selectedAnnotationLabel = previous.label || "";
  state.reviewFormDirty = false;
  state.deferredDetailRefresh = false;
  clearPendingReviewImages();
  updateEvidenceSummary();
  updateTagSummary();
  updateReviewHistory(caseData);
}

async function deleteAnnotationVersion(caseData, annotationId, button) {
  if (state.savingAnnotation) return;
  const annotation = (caseData.annotations || []).find(
    (item) => String(item.id) === String(annotationId)
  );
  if (!annotation) return;
  const deletingLatest = String(caseData.annotations?.[0]?.id) === String(annotationId);
  const unsavedWarning = deletingLatest && state.reviewFormDirty
    ? "\n当前表单有未保存编辑，删除后会恢复上一版本并丢弃这些编辑。"
    : "";
  const confirmed = window.confirm(
    `确认删除 ${formatTime(annotation.created_at)} 保存的 Review 版本？\n\n复核人：${annotation.author || "未记录"}\n该操作不可恢复；如果删除当前版本，会自动恢复上一版本为当前 Review。${unsavedWarning}`
  );
  if (!confirmed) return;
  state.savingAnnotation = true;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    const result = await api(
      `/api/cases/${encodeURIComponent(caseData.issue_id)}/annotations/${encodeURIComponent(annotationId)}`,
      { method: "DELETE" }
    );
    acknowledgeLocalChange(result);
    caseData.annotations = (caseData.annotations || []).filter(
      (item) => String(item.id) !== String(annotationId)
    );
    if (state.selectedCase?.issue_id === caseData.issue_id && deletingLatest) {
      state.selectedCase = caseData;
      syncReviewFormFromCase(caseData);
    } else {
      updateReviewHistory(caseData);
    }
    showToast("已删除该 Review 版本。");
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
    if (button.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  } finally {
    state.savingAnnotation = false;
  }
}

function renderReview(caseData) {
  const previous = caseData.annotations?.[0] || {};
  state.reviewFormDirty = false;
  state.deferredDetailRefresh = false;
  state.selectedAnnotationLabel = previous.label || "";
  const catalog = state.config?.missing_evidence_catalog || [];
  const tagCatalog = state.config?.review_tag_catalog || [];
  const hasPreviousReview = Boolean(caseData.annotations?.length);
  const chosenEvidence = new Set(
    hasPreviousReview ? previous.missing_evidence || [] : ["routing_direction"]
  );
  const catalogKeys = new Set(catalog.map((item) => item.key));
  const customEvidenceKeys = [...chosenEvidence].filter((key) => !catalogKeys.has(key));
  const chosenTags = new Set(previous.tags || []);
  const tagCatalogKeys = new Set(tagCatalog.map((item) => item.key));
  const customTagKeys = [...chosenTags].filter((tag) => !tagCatalogKeys.has(tag));
  const author = state.session.username || previous.author || "";
  const authorLocked = Boolean(state.session.verified && state.session.username);
  const reviewStatus = previous.review_status === "needs_gt_review"
    ? "needs_gt_review"
    : previous.review_status === "pending"
      ? "pending"
      : "reviewed";
  const evidenceOption = (item, selected) => `<label class="evidence-option" title="${escapeHtml(item.hint || "")}"><input type="checkbox" name="missingEvidence" value="${escapeHtml(item.key)}" ${selected ? "checked" : ""} /><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.hint || "")}</small></span></label>`;
  const customEvidenceOptions = customEvidenceKeys
    .map((key) => evidenceOption({ key, label: evidenceLabel(key), hint: "本条 Review 新建的缺失信息" }, true))
    .join("");
  const tagOption = (key, label, selected) => `<label class="tag-option"><input type="checkbox" name="reviewTags" value="${escapeHtml(key)}" ${selected ? "checked" : ""} /><span>${escapeHtml(label)}</span></label>`;
  const customTagOptions = customTagKeys
    .map((key) => tagOption(key, tagLabel(key), true))
    .join("");
  $("#reviewPane").innerHTML = `
    <div class="review-title"><div><h2>模型判错原因</h2><small class="review-scope-note">按 Issue 记录，模型输出仍按 Run 区分</small></div><span class="review-issue">${escapeHtml(caseData.issue_id)}</span></div>
    <form class="review-form" id="annotationForm">
      <label class="review-status-field"><span>复核状态</span><select id="reviewStatusInput"><option value="reviewed" ${reviewStatus === "reviewed" ? "selected" : ""}>已 Review</option><option value="pending" ${reviewStatus === "pending" ? "selected" : ""}>待补充</option><option value="needs_gt_review" ${reviewStatus === "needs_gt_review" ? "selected" : ""}>GT 需复核</option></select></label>
      <label class="review-reason">
        <span>模型为什么判错？</span>
        <textarea id="annotationNote" rows="4" placeholder="简要说明模型漏掉的关键证据，例如 routing、绕行空间或时序。">${escapeHtml(previous.note || "")}</textarea>
      </label>
      <details class="evidence-dropdown review-dropdown">
        <summary>缺失信息（多选）<span class="evidence-summary-count" id="evidenceSummaryCount">已选 ${chosenEvidence.size} 项</span></summary>
        <div class="evidence-options" id="missingEvidenceOptions">${catalog.map((item) => evidenceOption(item, chosenEvidence.has(item.key))).join("")}${customEvidenceOptions}<div class="custom-evidence-create" id="customEvidenceCreator"><input id="newMissingEvidence" maxlength="48" placeholder="输入新的缺失信息" autocomplete="off" /><button class="button button-quiet" id="addMissingEvidenceButton" type="button">新建标签</button></div></div>
      </details>
      <details class="evidence-dropdown review-dropdown tag-dropdown">
        <summary>场景 Tags（可选）<span class="evidence-summary-count" id="tagSummaryCount">已选 ${chosenTags.size} 项</span></summary>
        <div class="tag-options" id="reviewTagOptions">${tagCatalog.map((item) => tagOption(item.key, item.label, chosenTags.has(item.key))).join("")}${customTagOptions}<div class="custom-tag-create" id="customTagCreator"><input id="newSceneTag" maxlength="48" placeholder="输入新的场景 Tag" autocomplete="off" /><button class="button button-quiet" id="addSceneTagButton" type="button">新建标签</button></div></div>
      </details>
      <div class="review-attachment-field">
        <span>补充截图（可选）</span>
        <div class="screenshot-paste-zone" id="screenshotPasteZone" tabindex="0" role="group" aria-label="粘贴补充截图">
          <strong>粘贴截图</strong>
          <small>点击后 Ctrl / ⌘ + V；最多 4 张。</small>
          <button class="screenshot-browse-button" id="reviewScreenshotBrowse" type="button">选择图片</button>
        </div>
        <input class="hidden" id="reviewScreenshotInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
        <div class="pending-screenshot-list" id="pendingScreenshotList"></div>
      </div>
      <label><span>复核人${authorLocked ? "（SSO）" : "（必填）"}</span><input id="annotationAuthor" value="${escapeHtml(author)}" placeholder="姓名或工号" autocomplete="off" required ${authorLocked ? "readonly" : ""} /></label>
      <button class="button button-primary full-width" type="submit">保存新的 review 版本</button>
    </form>
    <details class="review-history-toggle" open>
      <summary><span><strong>Review 历史</strong></span><span class="history-launch-meta">${(caseData.annotations || []).length} 条</span></summary>
      <div class="review-history-content">${annotationHistory(caseData.annotations)}</div>
    </details>`;
  $("#reviewPane").querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.addEventListener("change", updateEvidenceSummary);
  });
  $("#reviewPane").querySelectorAll('input[name="reviewTags"]').forEach((input) => {
    input.addEventListener("change", updateTagSummary);
  });
  $("#reviewPane").querySelectorAll(".review-dropdown").forEach((dropdown) => {
    dropdown.addEventListener("toggle", () => {
      if (!dropdown.open) return;
      $("#reviewPane").querySelectorAll(".review-dropdown").forEach((other) => {
        if (other !== dropdown) other.open = false;
      });
    });
  });
  $("#addMissingEvidenceButton")?.addEventListener("click", () => {
    const input = $("#newMissingEvidence");
    const value = String(input?.value || "").trim();
    if (!value) return showToast("请输入新的缺失信息。", true);
    if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) return showToast("缺失信息长度或字符不合法。", true);
    const key = `custom:${value}`;
    const exists = [...document.querySelectorAll('input[name="missingEvidence"]')].some((item) => item.value === key);
    if (exists) return showToast("该缺失信息已经添加。", true);
    const option = document.createElement("label");
    option.className = "evidence-option custom-evidence-option";
    option.innerHTML = `<input type="checkbox" name="missingEvidence" value="${escapeHtml(key)}" checked /><span><strong>${escapeHtml(value)}</strong><small>本条 Review 新建的缺失信息</small></span>`;
    const creator = $("#customEvidenceCreator");
    creator?.before(option);
    option.querySelector("input")?.addEventListener("change", updateEvidenceSummary);
    if (input) input.value = "";
    state.reviewFormDirty = true;
    updateEvidenceSummary();
  });
  $("#addSceneTagButton")?.addEventListener("click", () => {
    const input = $("#newSceneTag");
    const value = String(input?.value || "").trim();
    if (!value) return showToast("请输入新的场景 Tag。", true);
    if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) return showToast("场景 Tag 长度或字符不合法。", true);
    const key = `custom:${value}`;
    const exists = [...document.querySelectorAll('input[name="reviewTags"]')].some((item) => item.value === key);
    if (exists) return showToast("该场景 Tag 已经添加。", true);
    const option = document.createElement("label");
    option.className = "tag-option custom-tag-option";
    option.innerHTML = `<input type="checkbox" name="reviewTags" value="${escapeHtml(key)}" checked /><span>${escapeHtml(value)}</span>`;
    $("#customTagCreator")?.before(option);
    option.querySelector("input")?.addEventListener("change", updateTagSummary);
    if (input) input.value = "";
    state.reviewFormDirty = true;
    updateTagSummary();
  });
  const pasteZone = $("#screenshotPasteZone");
  const screenshotInput = $("#reviewScreenshotInput");
  const screenshotBrowse = $("#reviewScreenshotBrowse");
  pasteZone.addEventListener("click", (event) => {
    if (event.target !== screenshotBrowse) pasteZone.focus();
  });
  screenshotBrowse.addEventListener("click", (event) => {
    event.stopPropagation();
    screenshotInput.click();
  });
  pasteZone.addEventListener("paste", (event) => {
    const files = [...(event.clipboardData?.items || [])]
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      event.preventDefault();
      addPendingReviewImages(files);
    }
  });
  screenshotInput.addEventListener("change", () => {
    addPendingReviewImages([...screenshotInput.files]);
    screenshotInput.value = "";
  });
  renderPendingReviewImages();
  const annotationForm = $("#annotationForm");
  annotationForm.addEventListener("input", () => {
    state.reviewFormDirty = true;
  });
  annotationForm.addEventListener("change", () => {
    state.reviewFormDirty = true;
  });
  annotationForm.addEventListener("submit", saveAnnotation);
  bindAnnotationHistory($("#reviewPane"), caseData);
}

function updateEvidenceSummary() {
  const count = document.querySelectorAll('input[name="missingEvidence"]:checked').length;
  const target = $("#evidenceSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
}

function updateTagSummary() {
  const count = document.querySelectorAll('input[name="reviewTags"]:checked').length;
  const target = $("#tagSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
}

function releasePreviewUrlLater(previewUrl) {
  window.setTimeout(() => URL.revokeObjectURL(previewUrl), 5000);
}

function clearPendingReviewImages() {
  const previewUrls = state.pendingReviewImages.map((item) => item.previewUrl);
  state.pendingReviewImages = [];
  renderPendingReviewImages();
  previewUrls.forEach(releasePreviewUrlLater);
}

function addPendingReviewImages(files) {
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = "";
  const previousCount = state.pendingReviewImages.length;
  files.forEach((file) => {
    if (state.pendingReviewImages.length >= maxCount) {
      rejected = `最多只能添加 ${maxCount} 张截图。`;
      return;
    }
    if (!allowed.has(file.type)) {
      rejected = "仅支持 PNG、JPEG 或 WebP 图片。";
      return;
    }
    if (file.size > maxBytes) {
      rejected = "单张截图不能超过 8 MB。";
      return;
    }
    const currentBytes = state.pendingReviewImages.reduce(
      (sum, item) => sum + item.file.size,
      0
    );
    if (currentBytes + file.size > maxTotalBytes) {
      rejected = "本次截图总大小不能超过 24 MB。";
      return;
    }
    state.pendingReviewImages.push({
      id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
    });
  });
  if (state.pendingReviewImages.length !== previousCount) {
    state.reviewFormDirty = true;
  }
  renderPendingReviewImages();
  if (rejected) showToast(rejected, true);
}

function renderPendingReviewImages() {
  const target = $("#pendingScreenshotList");
  if (!target) return;
  if (!state.pendingReviewImages.length) {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = state.pendingReviewImages
    .map(
      (item) => `<div class="pending-screenshot">
        <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || "待上传截图")}" />
        <button type="button" data-remove-screenshot="${escapeHtml(item.id)}" aria-label="移除截图">×</button>
      </div>`
    )
    .join("");
  target.querySelectorAll("[data-remove-screenshot]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = state.pendingReviewImages.findIndex(
        (item) => item.id === button.dataset.removeScreenshot
      );
      if (index < 0) return;
      const previewUrl = state.pendingReviewImages[index].previewUrl;
      state.pendingReviewImages.splice(index, 1);
      state.reviewFormDirty = true;
      renderPendingReviewImages();
      releasePreviewUrlLater(previewUrl);
    });
  });
}

async function selectCase(
  issueId,
  { updateRoute = true, historyMode = "push" } = {}
) {
  if (!issueId) return;
  const gallery = $("#reviewGalleryView");
  if (gallery && !gallery.classList.contains("hidden")) {
    state.galleryScrollY = window.scrollY;
  }
  if (state.selectedId && state.selectedId !== issueId) clearPendingReviewImages();
  const hadDetail = Boolean(state.selectedCase);
  state.selectedId = issueId;
  state.selectedCase = null;
  const requestSeq = ++state.caseRequestSeq;
  renderCaseNavigation();
  let loadingTimer = null;
  if (!hadDetail) {
    loadingTimer = window.setTimeout(() => {
      if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
      $("#detailPane").innerHTML = `
        <div class="empty-state detail-loading-state">
          <div class="empty-glyph" aria-hidden="true">…</div>
          <h2>正在加载 ${escapeHtml(issueId)}</h2>
          <p>正在读取 Issue 媒体与模型输出。</p>
        </div>`;
      $("#reviewPane").innerHTML = `
        <div class="review-placeholder"><h2>正在加载标注</h2><p>Issue 数据返回后即可继续 Review。</p></div>`;
    }, 140);
  }
  if (updateRoute && state.activePage === "review") {
    const nextUrl = pageUrl("review", { issue: issueId });
    if (`${window.location.pathname}${window.location.search}` !== nextUrl) {
      showPage("review", { historyMode, issue: issueId });
    } else {
      setReviewView(issueId);
    }
  } else {
    setReviewView(issueId);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  try {
    const data = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    scheduleTrailDetailMetadata(issueId, requestSeq);
  } catch (error) {
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    $("#detailPane").innerHTML = `
      <div class="empty-state">
        <div class="empty-glyph" aria-hidden="true">!</div>
        <h2>Issue 加载失败</h2>
        <p>${escapeHtml(error.message)}</p>
      </div>`;
    showToast(error.message, true);
  }
}

async function navigateAdjacentCase(delta) {
  if (!state.selectedId || ![-1, 1].includes(delta)) return;
  let index = state.cases.findIndex((item) => item.issue_id === state.selectedId);
  if (index < 0) return;
  let targetIndex = index + delta;
  if (targetIndex < 0 && state.casePage > 1) {
    await loadCases({ keepSelection: true, page: state.casePage - 1 });
    targetIndex = state.cases.length - 1;
  } else if (
    targetIndex >= state.cases.length &&
    state.casePage * state.casePageSize < state.caseTotal
  ) {
    await loadCases({ keepSelection: true, page: state.casePage + 1 });
    targetIndex = 0;
  }
  const target = state.cases[targetIndex];
  if (target) await selectCase(target.issue_id, { historyMode: "replace" });
}

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId || state.savingAnnotation) return;
  state.savingAnnotation = true;
  const submitButton = event.submitter || $("#annotationForm button[type='submit']");
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
  }
  const payload = {
    label: state.selectedAnnotationLabel,
    review_status: $("#reviewStatusInput").value,
    tags: [...document.querySelectorAll('input[name="reviewTags"]:checked')].map(
      (input) => input.value
    ),
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote").value,
    author: $("#annotationAuthor").value,
  };
  try {
    let result;
    if (state.pendingReviewImages.length) {
      const form = new FormData();
      form.append("payload", JSON.stringify(payload));
      state.pendingReviewImages.forEach((item, index) => {
        form.append(
          "attachments",
          item.file,
          item.file.name || `clipboard-${index + 1}.png`
        );
      });
      result = await api(
        `/api/cases/${encodeURIComponent(state.selectedId)}/annotations-with-attachments`,
        {
          method: "POST",
          body: form,
          headers: { "X-RA-Triage-Request": "review-v1" },
        }
      );
    } else {
      result = await api(`/api/cases/${encodeURIComponent(state.selectedId)}/annotations`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    acknowledgeLocalChange(result);
    const screenshotCount = state.pendingReviewImages.length;
    state.reviewFormDirty = false;
    state.deferredDetailRefresh = false;
    clearPendingReviewImages();
    if (result?.annotation && state.selectedCase?.issue_id === state.selectedId) {
      state.selectedCase.annotations = [
        result.annotation,
        ...(state.selectedCase.annotations || []).filter(
          (item) => String(item.id) !== String(result.annotation.id)
        ),
      ];
      updateReviewHistory(state.selectedCase);
    }
    showToast(
      `已保存新的 review 版本${screenshotCount ? `和 ${screenshotCount} 张截图` : ""}。`
    );
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.savingAnnotation = false;
    if (submitButton?.isConnected) {
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  }
}

function mediaFrames(kind) {
  return kind === "bev"
    ? state.media.snapshot?.bev || []
    : state.media.snapshot?.camera || [];
}

function mediaVideo() {
  return state.media.snapshot?.video?.url ? state.media.snapshot.video : null;
}

function preferredMediaKind(caseData) {
  if (caseData?.assets?.video?.url) return "video";
  if (caseData?.assets?.frames?.length) return "bev";
  if (caseData?.camera?.frames?.length) return "camera";
  return "";
}

async function openCaseMediaPreview(issueId, button = null) {
  if (!issueId) return;
  const requestSeq = ++state.media.requestSeq;
  const previousLabel = button?.textContent || "媒体预览";
  if (button) {
    button.disabled = true;
    button.textContent = "加载中…";
  }
  try {
    const caseData = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    if (requestSeq !== state.media.requestSeq) return;
    const kind = preferredMediaKind(caseData);
    if (!kind) {
      showToast(`${issueId} 暂无 BEV、Camera 或视频。`, true);
      return;
    }
    const index = kind === "bev" ? heroFrameIndex(caseData.assets?.frames || []) : 0;
    openMedia(kind, index, { caseData });
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = previousLabel;
    }
  }
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog && !dialog.open) dialog.showModal();
}

function cleanupMediaDialog() {
  const dialog = $("#mediaDialog");
  state.media.drag = null;
  state.media.snapshot = null;
  document.querySelectorAll("#mediaDialog .media-viewport").forEach((viewport) => {
    viewport.classList.remove("is-dragging");
  });
  $("#mediaVideoStage")?.querySelector("video")?.pause();
  if ($("#mediaVideoStage")) {
    $("#mediaVideoStage").innerHTML = "";
    delete $("#mediaVideoStage").dataset.videoUrl;
  }
  dialog?.classList.remove("media-fallback-fullscreen");
  if (document.fullscreenElement && dialog?.contains(document.fullscreenElement)) {
    document.exitFullscreen().catch(() => {});
  }
}

function closeDialog(id) {
  const dialog = $(`#${id}`);
  if (id === "mediaDialog") cleanupMediaDialog();
  if (dialog?.open) dialog.close();
}

function renderSourcePreview(data) {
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  const columns = Array.isArray(data?.columns) ? data.columns : [];
  const metadata = data?.metadata && typeof data.metadata === "object" ? data.metadata : {};
  const rowCount = Number(data?.total_rows || rows.length);
  const page = Number(data?.page || 1);
  const pageCount = Number(data?.page_count || 1);
  const offset = Number(data?.offset || 0);
  state.sourcePreview.page = page;
  state.sourcePreview.pageCount = pageCount;
  $("#sourcePreviewTitle").textContent = data?.filename || "文件预览";
  $("#sourcePreviewMeta").textContent = `${rowCount} 条结果 · 第 ${page} / ${pageCount} 页${data?.reconstructed ? " · Run 重建副本" : ""}`;
  $("#sourcePreviewPageLabel").textContent = `第 ${page} / ${pageCount} 页`;
  $("#sourcePreviewPrevious").disabled = !data?.has_previous;
  $("#sourcePreviewNext").disabled = !data?.has_next;
  const notice = data?.reconstructed
    ? '<div class="source-preview-notice">原始上传文件未归档；当前内容由 Run 中已保存的脱敏预测行重建，仅用于复核。</div>'
    : "";
  const metadataBlock = Object.keys(metadata).length
    ? `<details class="source-preview-metadata"><summary>文件元数据</summary><pre class="source-preview-json">${escapeHtml(JSON.stringify(metadata, null, 2))}</pre></details>`
    : "";
  if (!rows.length || !columns.length) {
    $("#sourcePreviewContent").innerHTML = `${notice}${metadataBlock}<div class="no-asset">文件中没有可展示的结果行。</div>`;
    return;
  }
  const header = columns.map((column) => `<th scope="col">${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row, index) => {
      const cells = columns
        .map((column) => `<td>${escapeHtml(row?.[column] ?? "")}</td>`)
        .join("");
      return `<tr><td>${offset + index + 1}</td>${cells}</tr>`;
    })
    .join("");
  $("#sourcePreviewContent").innerHTML = `${notice}${metadataBlock}<table class="source-preview-table"><thead><tr><th scope="col">#</th>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function loadSourcePreviewPage(runId, page = 1) {
  const run = state.modelRuns.find((item) => item.id === runId);
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  if (!run || !source.available || !source.preview_supported || !previewUrl) {
    throw new Error("该 Run 没有可用的 CSV / JSON 页面预览。");
  }
  const separator = previewUrl.includes("?") ? "&" : "?";
  const data = await api(`${previewUrl}${separator}page=${encodeURIComponent(Math.max(1, page))}&page_size=${state.sourcePreview.pageSize}`);
  state.sourcePreview.runId = runId;
  renderSourcePreview(data);
}

async function openSourcePreview(runId) {
  const run = state.modelRuns.find((item) => item.id === runId);
  const source = run?.source_file && typeof run.source_file === "object" ? run.source_file : {};
  const previewUrl = safeSameOriginAssetUrl(source.preview_url);
  if (!run || !source.available || !source.preview_supported || !previewUrl) {
    showToast("该 Run 没有可用的 CSV / JSON 页面预览，请重新上传原文件。", true);
    return;
  }
  $("#sourcePreviewTitle").textContent = source.filename || "文件预览";
  $("#sourcePreviewMeta").textContent = "正在读取…";
  $("#sourcePreviewPageLabel").textContent = "第 1 / … 页";
  $("#sourcePreviewPrevious").disabled = true;
  $("#sourcePreviewNext").disabled = true;
  $("#sourcePreviewContent").innerHTML = '<div class="no-asset">正在生成预览…</div>';
  openDialog("sourcePreviewDialog");
  try {
    state.sourcePreview = { runId, page: 1, pageSize: 100, pageCount: 1 };
    await loadSourcePreviewPage(runId, 1);
  } catch (error) {
    $("#sourcePreviewMeta").textContent = "预览失败";
    $("#sourcePreviewContent").innerHTML = `<div class="no-asset">${escapeHtml(error.message)}</div>`;
  }
}

const MEDIA_ZOOM_MIN = 0.5;
const MEDIA_ZOOM_BASE_MAX = 4;
const MEDIA_ZOOM_STEP = 0.25;

function activeMediaViewport() {
  return state.media.kind === "video"
    ? $("#mediaVideoStage")?.querySelector("[data-video-viewport]")
    : $("#mediaViewport");
}

function activeMediaCanvas() {
  return state.media.kind === "video"
    ? $("#mediaVideoStage")?.querySelector("[data-video-canvas]")
    : $("#mediaCanvas");
}

function activeMediaDimensions() {
  if (state.media.kind === "video") {
    const video = $("#mediaVideoStage")?.querySelector("video");
    return { width: Number(video?.videoWidth || 0), height: Number(video?.videoHeight || 0) };
  }
  const image = $("#mediaPreviewImage");
  return { width: Number(image?.naturalWidth || 0), height: Number(image?.naturalHeight || 0) };
}

function mediaOriginalZoom() {
  const viewport = activeMediaViewport();
  const dimensions = activeMediaDimensions();
  if (!viewport?.clientWidth || !viewport?.clientHeight || !dimensions.width || !dimensions.height) {
    return null;
  }
  const fitScale = Math.min(
    viewport.clientWidth / dimensions.width,
    viewport.clientHeight / dimensions.height
  );
  return fitScale > 0 ? 1 / fitScale : null;
}

function mediaZoomMax() {
  return Math.max(MEDIA_ZOOM_BASE_MAX, mediaOriginalZoom() || 1);
}

function mediaZoomMin() {
  return Math.min(MEDIA_ZOOM_MIN, mediaOriginalZoom() || 1);
}

function updateMediaPanState(viewport = activeMediaViewport()) {
  if (!viewport) return;
  const pannable =
    viewport.scrollWidth > viewport.clientWidth + 1 ||
    viewport.scrollHeight > viewport.clientHeight + 1;
  viewport.classList.toggle("is-pannable", pannable);
  if (!pannable) {
    state.media.drag = null;
    viewport.classList.remove("is-dragging");
  }
}

function mediaFullscreenActive() {
  const dialog = $("#mediaDialog");
  const card = dialog?.querySelector(".media-dialog-card");
  return Boolean(document.fullscreenElement === card || dialog?.classList.contains("media-fallback-fullscreen"));
}

function updateMediaViewControls() {
  const zoom = Math.min(mediaZoomMax(), Math.max(mediaZoomMin(), Number(state.media.zoom) || 1));
  state.media.zoom = zoom;
  $("#mediaZoomResetButton").textContent = `${Math.round(zoom * 100)}%`;
  $("#mediaZoomOutButton").disabled = zoom <= mediaZoomMin();
  $("#mediaZoomInButton").disabled = zoom >= mediaZoomMax();
  const originalZoom = mediaOriginalZoom();
  const originalButton = $("#mediaOriginalSizeButton");
  originalButton.disabled = !originalZoom;
  originalButton.classList.toggle(
    "active",
    Boolean(originalZoom && Math.abs(zoom - originalZoom) < 0.01)
  );
  const dimensions = activeMediaDimensions();
  originalButton.title = originalZoom
    ? `按媒体原始像素 1:1 显示（${dimensions.width} × ${dimensions.height}）`
    : "媒体尺寸读取中";
  const fullscreen = mediaFullscreenActive();
  $("#mediaFullscreenButton").textContent = fullscreen ? "⤢" : "⛶";
  $("#mediaFullscreenButton").setAttribute("aria-label", fullscreen ? "退出全屏" : "进入全屏");
  $("#mediaFullscreenButton").title = fullscreen ? "退出全屏（F）" : "进入全屏（F）";
}

function setMediaZoom(nextZoom, { resetScroll = false } = {}) {
  const viewport = activeMediaViewport();
  const canvas = activeMediaCanvas();
  if (!viewport || !canvas) return;
  const centerRatioX = viewport.scrollWidth > 0
    ? (viewport.scrollLeft + viewport.clientWidth / 2) / viewport.scrollWidth
    : 0.5;
  const centerRatioY = viewport.scrollHeight > 0
    ? (viewport.scrollTop + viewport.clientHeight / 2) / viewport.scrollHeight
    : 0.5;
  state.media.zoom = Math.min(mediaZoomMax(), Math.max(mediaZoomMin(), Number(nextZoom) || 1));
  const size = `${state.media.zoom * 100}%`;
  canvas.style.width = size;
  canvas.style.height = size;
  updateMediaViewControls();
  window.requestAnimationFrame(() => {
    if (resetScroll) {
      viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
      viewport.scrollTop = Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2);
      updateMediaPanState();
      return;
    }
    viewport.scrollLeft = Math.max(0, centerRatioX * viewport.scrollWidth - viewport.clientWidth / 2);
    viewport.scrollTop = Math.max(0, centerRatioY * viewport.scrollHeight - viewport.clientHeight / 2);
    updateMediaPanState();
  });
}

function showMediaAtOriginalSize() {
  const originalZoom = mediaOriginalZoom();
  if (!originalZoom) return;
  setMediaZoom(originalZoom, { resetScroll: true });
}

async function toggleMediaFullscreen() {
  const dialog = $("#mediaDialog");
  const card = dialog?.querySelector(".media-dialog-card");
  if (!dialog || !card) return;
  try {
    if (document.fullscreenElement === card) {
      await document.exitFullscreen();
    } else if (document.fullscreenElement) {
      await document.exitFullscreen();
      await card.requestFullscreen();
    } else if (card.requestFullscreen) {
      await card.requestFullscreen();
    } else {
      dialog.classList.toggle("media-fallback-fullscreen");
    }
  } catch (error) {
    showToast(`无法切换全屏：${error.message}`, true);
  }
  updateMediaViewControls();
  window.requestAnimationFrame(updateMediaPanState);
}

function switchMediaKind(kind) {
  const available = kind === "video" ? Boolean(mediaVideo()) : Boolean(mediaFrames(kind).length);
  if (!available) {
      showToast(`${kind === "video" ? "Ares Studio 视频" : `${kind.toUpperCase()} 图片`} 当前不可用。`, true);
    return;
  }
  if (state.media.kind === "video" && kind !== "video") {
    $("#mediaVideoStage")?.querySelector("video")?.pause();
  }
  state.media.kind = kind;
  state.media.index = 0;
  state.media.zoom = 1;
  renderMediaDialog();
}

function bindMediaPanViewport(viewport) {
  if (!viewport || viewport.dataset.mediaPanBound === "true") return;
  viewport.dataset.mediaPanBound = "true";
  viewport.addEventListener("pointerdown", (event) => {
    if (
      !viewport.classList.contains("is-pannable") ||
      (event.pointerType === "mouse" && event.button !== 0)
    ) return;
    event.preventDefault();
    state.media.drag = {
      viewport,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    const drag = state.media.drag;
    if (!drag || drag.viewport !== viewport || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    viewport.scrollLeft = drag.scrollLeft - (event.clientX - drag.startX);
    viewport.scrollTop = drag.scrollTop - (event.clientY - drag.startY);
  });
  const endDrag = (event) => {
    const drag = state.media.drag;
    if (!drag || drag.viewport !== viewport || drag.pointerId !== event.pointerId) return;
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    state.media.drag = null;
    viewport.classList.remove("is-dragging");
  };
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", endDrag);
  viewport.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setMediaZoom(state.media.zoom + (event.deltaY < 0 ? MEDIA_ZOOM_STEP : -MEDIA_ZOOM_STEP));
  }, { passive: false });
}

function preloadMediaDialogImage(url, onReady) {
  const requestSeq = Number(state.media.imageRequestSeq || 0) + 1;
  state.media.imageRequestSeq = requestSeq;
  const image = new Image();
  image.decoding = "async";
  image.onload = () => {
    let decoded;
    try {
      decoded = typeof image.decode === "function" ? image.decode() : Promise.resolve();
    } catch {
      decoded = Promise.resolve();
    }
    Promise.resolve(decoded).catch(() => {}).then(() => {
      if (requestSeq === state.media.imageRequestSeq) onReady();
    });
  };
  image.onerror = () => {
    if (requestSeq === state.media.imageRequestSeq) showToast("媒体图片加载失败，已保留当前画面。", true);
  };
  image.src = url;
}

function renderMediaDialog() {
  const snapshot = state.media.snapshot;
  const bev = mediaFrames("bev");
  const camera = mediaFrames("camera");
  const video = mediaVideo();
  const availableKinds = [
    bev.length ? "bev" : "",
    camera.length ? "camera" : "",
    video ? "video" : "",
  ].filter(Boolean);
  if (!availableKinds.includes(state.media.kind)) state.media.kind = availableKinds[0] || "bev";
  const videoMode = state.media.kind === "video";
  const gtLabel = snapshot?.gtLabel || "";
  const modelLabel = snapshot?.modelLabel || "";
  const comparisonText = modelLabel ? (modelLabel === gtLabel ? "一致" : "不一致") : "未输出";
  const comparisonClass = modelLabel && modelLabel !== gtLabel ? "comparison-fail" : "comparison-neutral";
  $("#mediaDecisionSummary").innerHTML = `
    <span>GT</span>${labelBadge(gtLabel, "缺失")}
    <b aria-hidden="true">→</b>
    <span>模型</span>${labelBadge(modelLabel, "未输出")}
    <strong class="${comparisonClass}">${comparisonText}</strong>`;
  const imageStage = $("#mediaImageStage");
  const videoStage = $("#mediaVideoStage");
  imageStage.hidden = videoMode;
  videoStage.hidden = !videoMode;
  $("#mediaTimeline").hidden = videoMode;
  $("#mediaModeTabs").innerHTML = `
    <button type="button" class="media-mode ${state.media.kind === "bev" ? "active" : ""}" data-media-mode="bev" ${bev.length ? "" : "disabled"}>BEV 图片 <span>${bev.length}</span></button>
    <button type="button" class="media-mode ${state.media.kind === "camera" ? "active" : ""}" data-media-mode="camera" ${camera.length ? "" : "disabled"}>Camera 图片 <span>${camera.length}</span></button>
    <button type="button" class="media-mode ${videoMode ? "active" : ""}" data-media-mode="video" ${video ? "" : "disabled"}>Ares Studio 视频 <span>${video ? "1" : "0"}</span></button>`;
  $("#mediaModeTabs").querySelectorAll("[data-media-mode]").forEach((button) => {
    button.addEventListener("click", () => switchMediaKind(button.dataset.mediaMode));
  });

  if (videoMode && video) {
    state.media.imageRequestSeq += 1;
    if (videoStage.dataset.videoUrl !== video.url) {
      videoStage.dataset.videoUrl = video.url;
      videoStage.innerHTML = videoPlayerMarkup(video, {
        posterUrl: bev[heroFrameIndex(bev)]?.url || "",
      });
      bindBevVideoPlayers(videoStage);
      const viewport = videoStage.querySelector("[data-video-viewport]");
      const videoElement = videoStage.querySelector("video");
      bindMediaPanViewport(viewport);
      videoElement.addEventListener("loadedmetadata", () => {
        setMediaZoom(state.media.zoom, { resetScroll: true });
      });
    }
    $("#mediaTitle").textContent = `${snapshot?.issueId || ""} · Ares Studio 视频`;
    $("#mediaTimeline").innerHTML = "";
    $("#mediaHelp").textContent = "← / → 按所选步长跳转 · 空格播放/暂停 · B/C/V 切媒体 · +/− 缩放 · 0 适配 · 放大后拖拽平移 · F 全屏 · Esc 退出";
    setMediaZoom(state.media.zoom, { resetScroll: state.media.zoom === 1 });
    return;
  }

  const frames = mediaFrames(state.media.kind);
  state.media.index = Math.max(0, Math.min(state.media.index, Math.max(frames.length - 1, 0)));
  const current = frames[state.media.index];
  if (!current) return;
  $("#mediaTitle").textContent = `${snapshot?.issueId || ""} · ${frameLabel(current)} · ${state.media.index + 1}/${frames.length}`;
  const previewImage = $("#mediaPreviewImage");
  const targetUrl = String(current.url || "");
  const targetKind = state.media.kind;
  const targetIndex = state.media.index;
  const targetIssueId = String(snapshot?.issueId || "");
  state.media.imageRequestSeq += 1;
  const applyImage = () => {
    if (
      state.media.kind !== targetKind ||
      state.media.index !== targetIndex ||
      String(state.media.snapshot?.issueId || "") !== targetIssueId
    ) return;
    previewImage.src = targetUrl;
    previewImage.alt = `${targetKind} ${frameLabel(current)}`;
    previewImage.dataset.mediaUrl = targetUrl;
    setMediaZoom(state.media.zoom);
  };
  if (previewImage.dataset.mediaUrl === targetUrl) {
    previewImage.alt = `${targetKind} ${frameLabel(current)}`;
    setMediaZoom(state.media.zoom);
  } else if (targetUrl) {
    preloadMediaDialogImage(targetUrl, applyImage);
  }
  $("#mediaHelp").textContent = "← / ↑ 上一帧 · → / ↓ 下一帧 · B/C/V 切媒体 · +/− 缩放 · 0 复位 · 放大后拖拽平移 · F 全屏 · Esc 退出";
  $("#mediaTimeline").innerHTML = frames.map((frame, index) => `<button type="button" class="timeline-dot ${index === state.media.index ? "active" : ""}" data-media-frame="${index}" title="${escapeHtml(frameLabel(frame))}">${escapeHtml(frameLabel(frame))}</button>`).join("");
  $("#mediaTimeline").querySelectorAll("[data-media-frame]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.index = Number(button.dataset.mediaFrame);
      renderMediaDialog();
    });
  });
}

function openMedia(kind, index, { caseData = state.selectedCase } = {}) {
  const selectedPrediction = (caseData?.predictions || []).find(
    (item) => item.model_run_id === state.selectedRunId
  ) || caseData?.predictions?.[0];
  state.media.snapshot = {
    issueId: String(caseData?.issue_id || ""),
    gtLabel: String(caseData?.gt_label || ""),
    modelLabel: String(selectedPrediction?.model_label || ""),
    bev: [...(caseData?.assets?.frames || [])],
    camera: [...(caseData?.camera?.frames || [])],
    video: caseData?.assets?.video?.url ? { ...caseData.assets.video } : null,
  };
  const requestedAvailable = kind === "video" ? Boolean(mediaVideo()) : Boolean(mediaFrames(kind).length);
  if (!requestedAvailable) kind = preferredMediaKind(caseData);
  if (!kind) return;
  state.media.kind = kind;
  state.media.index = Number.isFinite(Number(index)) ? Number(index) : 0;
  state.media.zoom = 1;
  renderMediaDialog();
  openDialog("mediaDialog");
  setMediaZoom(1, { resetScroll: true });
}

function moveMedia(delta) {
  if (state.media.kind === "video") {
    $("#mediaVideoStage")
      ?.querySelector(`[data-video-jump="${delta < 0 ? -1 : 1}"]`)
      ?.click();
    return;
  }
  const frames = mediaFrames(state.media.kind);
  if (!frames.length) return;
  state.media.index = (state.media.index + delta + frames.length) % frames.length;
  renderMediaDialog();
}

function predictionIssueIds() {
  return [
    ...new Set(
      String($("#predictionBatchIssues")?.value || "")
        .split(/[\s,，;；]+/)
        .map((value) => value.trim())
        .filter(Boolean)
    ),
  ];
}

function updatePredictionBatchCount() {
  const target = $("#predictionBatchIssueCount");
  if (!target) return;
  const ids = predictionIssueIds();
  const invalid = ids.filter((issueId) => !/^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const maxIssues = Number(state.config?.prediction_batch?.max_issues || 0);
  const overLimit = maxIssues > 0 && ids.length > maxIssues;
  target.textContent =
    `${ids.length} 个${maxIssues ? ` · 单批最多 ${maxIssues} 个` : ""}` +
    `${invalid.length ? ` · ${invalid.length} 个格式不合法` : ""}`;
  target.classList.toggle("input-warning", Boolean(invalid.length || overLimit));
}

function renderGatewayProviders() {
  const target = $("#gatewayProviderSelect");
  if (!target) return;
  const catalog = state.config?.prediction_batch?.providers || {};
  const providers = Array.isArray(catalog.providers) ? catalog.providers : [];
  if (!providers.length) {
    target.innerHTML = '<option value="">未发现服务端 Provider 配置</option>';
    target.disabled = true;
    return;
  }
  const configuredSelected = state.selectedGatewayProviderId || catalog.active_provider_id;
  const selectedId = providers.some((item) => item.id === configuredSelected && item.enabled)
    ? configuredSelected
    : providers.find((item) => item.enabled)?.id || providers[0].id;
  state.selectedGatewayProviderId = selectedId;
  target.innerHTML = providers
    .map((provider) => {
      const selectable = Boolean(provider.enabled && provider.supports_batch);
      const status = selectable ? "可用" : provider.credential_configured ? "暂不可用" : "未配置凭证";
      return `<option value="${escapeHtml(provider.id)}" ${selectable ? "" : "disabled"}>${escapeHtml(provider.display_name || provider.id)} · ${escapeHtml(status)}</option>`;
    })
    .join("");
  target.value = selectedId;
  target.disabled = false;
  target.onchange = () => {
    const nextId = target.value || selectedId;
    if (nextId === state.selectedGatewayProviderId) return;
    state.selectedGatewayProviderId = nextId;
    state.selectedGatewayModelId = "";
    const modelSelect = $("#predictionModelSelect");
    if (modelSelect) modelSelect.value = "";
    renderGatewayProviders();
    loadGatewayModels({ providerId: state.selectedGatewayProviderId }).catch((error) => {
      showToast(error.message, true);
    });
  };
}

function renderGatewayModels() {
  const select = $("#predictionModelSelect");
  const statusTarget = $("#gatewayModelStatus");
  const endpointTarget = $("#gatewayModelsEndpoint");
  const listTarget = $("#gatewayModelList");
  const createButton = $("#createPredictionBatchButton");
  if (!select || !statusTarget || !endpointTarget) return;
  const catalog = state.gatewayModelStatus || {};
  const previous = state.selectedGatewayModelId || select.value;
  const visibleModels = state.gatewayModels;
  const defaultId = catalog.ui_default_model_id || catalog.default_model_id || "";
  const selectedModel = previous
    ? state.gatewayModels.find((item) => item.id === previous) || null
    : state.gatewayModels.find((item) => item.id === defaultId) ||
      state.gatewayModels[0] ||
      null;
  const unavailableSelection = Boolean(previous && !selectedModel);
  const displayModels = [...visibleModels];
  if (unavailableSelection) {
    displayModels.unshift({
      id: previous,
      display_name: `${previous} · 当前选择已不可用`,
      unavailable: true,
    });
  }
  endpointTarget.textContent =
    catalog.catalog_label ||
    state.config?.prediction_batch?.model_gateway?.catalog_label ||
    "ra-model · /v1/models";
  select.innerHTML = displayModels.length
    ? displayModels
        .map(
          (model) => {
            const tier = model.unavailable
              ? "不可用"
              : model.validation_status === "validated"
                ? "已验证"
                : "实验";
            return `<option value="${escapeHtml(model.id)}">[${tier}] ${escapeHtml(model.display_name || model.id)}</option>`;
          }
        )
        .join("")
    : '<option value="">没有匹配的模型</option>';
  select.value = unavailableSelection ? previous : selectedModel?.id || "";
  state.selectedGatewayModelId = select.value;
  if (listTarget) {
    listTarget.innerHTML = displayModels.length
      ? displayModels
          .map((model) => {
            const unavailable = Boolean(model.unavailable);
            const active = !unavailable && model.id === state.selectedGatewayModelId;
            const tier = unavailable
              ? "不可用"
              : model.validation_status === "validated"
                ? "已验证"
                : "实验";
            const resolved = model.resolved_model_id && model.resolved_model_id !== model.id
              ? model.resolved_model_id
              : model.id;
            return `<button class="gateway-model-option ${active ? "active" : ""} ${unavailable ? "unavailable" : ""}" type="button" data-gateway-model="${escapeHtml(model.id)}" ${unavailable ? "disabled" : ""}>
              <span class="gateway-model-option-head">
                <strong>${escapeHtml(model.display_name || model.id)}</strong>
                <em>${tier}</em>
              </span>
              <small>${escapeHtml(resolved)}</small>
            </button>`;
          })
          .join("")
      : '<div class="muted">没有匹配的模型。</div>';
    listTarget.querySelectorAll("[data-gateway-model]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        state.selectedGatewayModelId = button.dataset.gatewayModel || "";
        select.value = state.selectedGatewayModelId;
        renderGatewayModels();
      });
    });
  }
  const selectedIsOnline = state.gatewayModels.some(
    (item) => item.id === state.selectedGatewayModelId
  );
  const ready =
    catalog.status === "ready" &&
    !catalog.stale &&
    Boolean(select.value) &&
    selectedIsOnline;
  statusTarget.className = `gateway-model-status ${ready ? "ok" : "warn"}`;
  statusTarget.textContent = unavailableSelection
    ? `当前选择 ${previous} 已不在当前 Provider 在线目录；请选择其他模型后再提交。`
    : ready
      ? `已验证 ${state.gatewayModels.filter((model) => model.validation_status === "validated").length} · 实验模型 ${state.gatewayModels.filter((model) => model.validation_status !== "validated").length} · 当前显示 ${visibleModels.length}`
      : catalog.message || "模型目录尚未就绪。";
  if (createButton) createButton.disabled = !ready;
  renderBatchCatalogFilters();
  renderBatchRuntimeSummary();
}

async function loadGatewayModels({ refresh = false, providerId = "" } = {}) {
  const requestSeq = ++state.gatewayModelRequestSeq;
  const statusTarget = $("#gatewayModelStatus");
  if (statusTarget) {
    statusTarget.className = "gateway-model-status";
    statusTarget.textContent = refresh ? "正在刷新模型目录…" : "正在自动获取模型目录…";
  }
  try {
    const selectedProviderId = providerId || state.selectedGatewayProviderId || "kylin";
    const params = new URLSearchParams({ provider_id: selectedProviderId });
    if (refresh) params.set("refresh", "true");
    const data = await api(`/api/prediction-batches/models?${params.toString()}`);
    if (requestSeq !== state.gatewayModelRequestSeq) return;
    const models = data.models || [];
    const autoModel = models.find((model) => model.id === "auto");
    state.gatewayModelStatus = {
      ...data,
      ui_default_model_id: autoModel?.resolved_model_id || data.default_model_id,
    };
    state.gatewayModels = models.filter((model) => model.id !== "auto");
    renderGatewayModels();
  } catch (error) {
    if (requestSeq !== state.gatewayModelRequestSeq) return;
    state.gatewayModelStatus = {
      status: "failed",
      stale: false,
      message: error.message,
      catalog_label:
        state.config?.prediction_batch?.model_gateway?.catalog_label ||
        "ra-model · /v1/models",
      provider_id: providerId || state.selectedGatewayProviderId || "kylin",
    };
    state.gatewayModels = [];
    renderGatewayModels();
    throw error;
  }
}

function selectedBatchPrompt() {
  const promptId = $("#predictionPromptSelect")?.value || "";
  return state.batchPrompts.find((item) => item.id === promptId) || null;
}

function updatePromptEditorSummary() {
  const target = $("#predictionPromptSummary");
  const editor = $("#predictionPromptTemplate");
  if (!target || !editor) return;
  const selected = selectedBatchPrompt();
  const changed = Boolean(selected && editor.value.trim() !== String(selected.template || "").trim());
  const bytes = new TextEncoder().encode(editor.value).length;
  target.textContent =
    `${bytes} bytes · ${changed ? "已修改，将保存 custom Prompt 快照" : "服务器模板原文"}` +
    (selected?.sha256 ? ` · 基线 SHA ${selected.sha256.slice(0, 12)}…` : "");
  target.classList.toggle("input-warning", bytes === 0 || bytes > 128 * 1024);
  renderBatchRuntimeSummary();
}

function loadSelectedPromptTemplate() {
  const selected = selectedBatchPrompt();
  const editor = $("#predictionPromptTemplate");
  if (!editor) return;
  editor.value = selected?.template || "";
  editor.dataset.promptId = selected?.id || "";
  updatePromptEditorSummary();
}

function renderBatchPrompts() {
  const select = $("#predictionPromptSelect");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = state.batchPrompts.length
    ? state.batchPrompts
        .map((prompt) => `<option value="${escapeHtml(prompt.id)}">${escapeHtml(prompt.display_name || prompt.id)}${prompt.is_default ? " · 默认" : ""}</option>`)
        .join("")
    : '<option value="">暂无可用三分类 Prompt</option>';
  const defaultId = state.batchPromptStatus?.default_prompt_id || "";
  select.value = state.batchPrompts.some((item) => item.id === previous)
    ? previous
    : state.batchPrompts.some((item) => item.id === defaultId)
      ? defaultId
      : state.batchPrompts[0]?.id || "";
  if ($("#predictionPromptTemplate")?.dataset.promptId !== select.value) {
    loadSelectedPromptTemplate();
  }
  renderBatchCatalogFilters();
}

async function loadBatchPrompts() {
  const data = await api("/api/prediction-batches/prompts");
  state.batchPromptStatus = data;
  state.batchPrompts = data.items || [];
  renderBatchPrompts();
}

function batchInputPresets() {
  return (
    state.config?.prediction_batch?.input_policy?.profiles || [
      {
        id: "camera_ra_event",
        frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
        use_ra_event: true,
        use_ra_options: false,
      },
      {
        id: "camera_ra_options",
        frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
        use_ra_event: true,
        use_ra_options: true,
      },
      {
        id: "camera_only",
        frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
        use_ra_event: false,
        use_ra_options: false,
      },
    ]
  );
}

function applyBatchInputPreset() {
  const profileId = $("#predictionInputProfile")?.value || "camera_ra_event";
  const preset = batchInputPresets().find((item) => item.id === profileId);
  if (!preset) return;
  $("#predictionFrameOffsets").value = (preset.frame_offsets_ms || []).join(",");
  $("#predictionUseRaEvent").checked = Boolean(preset.use_ra_event);
  $("#predictionUseRaOptions").checked = Boolean(preset.use_ra_options);
  syncCameraFramePreset();
  renderBatchRuntimeSummary();
}

function cameraFramePresets() {
  return [
    {
      id: "camera_9_frames",
      frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
    },
    {
      id: "camera_three_moments",
      frame_offsets_ms: [-3000, 0, 3000],
    },
    {
      id: "camera_single_frame",
      frame_offsets_ms: [0],
    },
  ];
}

function syncCameraFramePreset() {
  const select = $("#predictionCameraPreset");
  const input = $("#predictionFrameOffsets");
  if (!select || !input) return;
  const offsets = String(input.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean)
    .map((value) => Number(value));
  const matched = cameraFramePresets().find((preset) =>
    preset.frame_offsets_ms.length === offsets.length &&
    preset.frame_offsets_ms.every((value, index) => value === offsets[index])
  );
  select.value = matched?.id || "custom";
}

function applyCameraFramePreset() {
  const select = $("#predictionCameraPreset");
  const preset = cameraFramePresets().find(
    (item) => item.id === select?.value
  );
  if (!preset) return;
  $("#predictionFrameOffsets").value = preset.frame_offsets_ms.join(",");
  renderBatchRuntimeSummary();
}

function batchPromptFacetValue({ version = "", mode = "", sha256 = "" } = {}) {
  return JSON.stringify([String(version), String(mode), String(sha256)]);
}

function parseBatchPromptFacetValue(value) {
  if (!value) return { version: "", mode: "", sha256: "" };
  try {
    const [version = "", mode = "", sha256 = ""] = JSON.parse(value);
    return {
      version: String(version),
      mode: String(mode),
      sha256: String(sha256),
    };
  } catch {
    return { version: String(value), mode: "", sha256: "" };
  }
}

function renderBatchCatalogFilters() {
  const modelFilter = $("#batchModelFilter");
  if (modelFilter) {
    const previous = modelFilter.value;
    const modelOptions = new Map(
      state.gatewayModels.map((model) => [
        model.id,
        {
          id: model.id,
          label: model.display_name || model.id,
          count: null,
        },
      ])
    );
    (state.batchFacets.models || []).forEach((model) => {
      const existing = modelOptions.get(model.id);
      modelOptions.set(model.id, {
        id: model.id,
        label: existing?.label || `${model.id} · 历史`,
        count: model.job_count,
      });
    });
    modelFilter.innerHTML = [
      '<option value="">全部模型</option>',
      ...[...modelOptions.values()].map(
        (model) =>
          `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}${model.count != null ? ` · ${model.count}` : ""}</option>`
      ),
    ].join("");
    modelFilter.value = modelOptions.has(previous) ? previous : "";
  }
  const promptFilter = $("#batchPromptFilter");
  if (promptFilter) {
    const previous = promptFilter.value;
    const promptOptions = new Map();
    state.batchPrompts.forEach((prompt) => {
      const facet = {
        version: prompt.id,
        mode: "catalog",
        sha256: prompt.sha256 || "",
      };
      const value = batchPromptFacetValue(facet);
      promptOptions.set(value, {
        ...facet,
        value,
        label: `${prompt.display_name || prompt.id} · 当前模板`,
        count: null,
      });
    });
    (state.batchFacets.prompts || []).forEach((prompt) => {
      const value = batchPromptFacetValue(prompt);
      const shaLabel = prompt.sha256 ? ` · ${prompt.sha256.slice(0, 10)}…` : "";
      const modeLabel =
        prompt.mode === "custom"
          ? "custom"
          : prompt.mode === "catalog"
            ? "catalog"
            : "legacy";
      const existing = promptOptions.get(value);
      promptOptions.set(value, {
        ...prompt,
        value,
        label:
          existing?.label ||
          `${prompt.version} · ${modeLabel}${shaLabel}`,
        count: prompt.job_count,
      });
    });
    promptFilter.innerHTML = [
      '<option value="">全部 Prompt</option>',
      ...[...promptOptions.values()].map(
        (prompt) =>
          `<option value="${escapeHtml(prompt.value)}">${escapeHtml(prompt.label)}${prompt.count != null ? ` · ${prompt.count}` : ""}</option>`
      ),
    ].join("");
    promptFilter.value = promptOptions.has(previous) ? previous : "";
  }
  const inputFilter = $("#batchInputFilter");
  if (inputFilter) {
    const previous = inputFilter.value;
    const inputLabels = {
      camera_ra_event: "Camera + RA Events",
      camera_ra_options: "Camera + RA/SWAG Options",
      camera_only: "Camera only",
      custom: "Custom",
    };
    const inputOptions = new Map(
      Object.entries(inputLabels).map(([id, label]) => [
        id,
        { id, label, count: null },
      ])
    );
    (state.batchFacets.input_profiles || []).forEach((profile) => {
      inputOptions.set(profile.id, {
        id: profile.id,
        label: inputLabels[profile.id] || `${profile.id} · 历史`,
        count: profile.job_count,
      });
    });
    inputFilter.innerHTML = [
      '<option value="">全部输入</option>',
      ...[...inputOptions.values()].map(
        (profile) =>
          `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.label)}${profile.count != null ? ` · ${profile.count}` : ""}</option>`
      ),
    ].join("");
    inputFilter.value = inputOptions.has(previous) ? previous : "";
  }
}

function renderBatchRuntimeSummary() {
  const target = $("#batchModelSummary");
  if (!target) return;
  const selectedGatewayModel = state.gatewayModels.find(
    (item) => item.id === $("#predictionModelSelect")?.value
  );
  const configured =
    state.batchDefaultModel ||
    state.config?.prediction_batch?.safe_experiment ||
    state.config?.prediction_batch?.default_model ||
    state.config?.batch_prediction?.safe_experiment ||
    state.config?.batch_prediction?.default_model ||
    state.config?.batch_prediction ||
    {};
  const model =
    selectedGatewayModel?.display_name ||
    (typeof configured === "string"
      ? configured
      : configured.model_name || configured.name || configured.model);
  const prompt =
    selectedBatchPrompt()?.id ||
    (typeof configured === "object"
      ? configured.prompt_version || configured.prompt || state.config?.prediction_batch?.prompt_version
      : "");
  const source = selectedGatewayModel
    ? `${state.selectedGatewayProviderId || selectedGatewayModel.provider || "kylin"} · ${selectedGatewayModel.resolved_model_id}`
    : typeof configured === "object"
      ? configured.experiment_source || configured.runtime || configured.source
      : "";
  const frameCount = String($("#predictionFrameOffsets")?.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean).length;
  const media = frameCount
    ? `Camera ${frameCount} 帧 · Ares Animation ${$("#predictionUseBev")?.checked ? "开启" : "关闭"}`
    : "";
  target.innerHTML = `
    <strong>${escapeHtml(model || "服务器模型网关")}</strong>
    <span>${prompt ? `Prompt · ${escapeHtml(prompt)}` : "尚未选择 Prompt"} · 输入 ${escapeHtml($("#predictionInputProfile")?.value || "camera_ra_event")}</span>
    <small>${escapeHtml([source, media].filter(Boolean).join(" · ") || "模型地址与密钥由服务器管理；Prompt 和输入按 Batch 固化")}</small>`;
}

function batchStatusLabel(status) {
  return (
    {
      queued: "排队中",
      running: "运行中",
      succeeded: "成功",
      completed: "成功",
      partial: "部分成功",
      partially_succeeded: "部分成功",
      failed: "失败",
      cancelled: "已取消",
    }[status] || status || "未知"
  );
}

function batchPublishLabel(status) {
  return (
    {
      not_requested: "未推送",
      not_published: "未推送",
      pending: "未推送",
      running: "推送中",
      publishing: "推送中",
      succeeded: "已推送",
      published: "已推送",
      partial: "部分推送",
      failed: "推送失败",
    }[status] || status || "未推送"
  );
}

function batchCounts(batch) {
  const items = batch.items || [];
  return {
    total: Number(batch.total_count ?? batch.requested_count ?? items.length ?? 0),
    completed: Number(batch.completed_count ?? 0),
    success: Number(batch.success_count ?? batch.succeeded_count ?? 0),
    failed: Number(batch.failed_count ?? 0),
  };
}

function batchSummaryText(batch) {
  if (batch.error_text) return batch.error_text;
  if (typeof batch.summary === "string") return batch.summary;
  if (batch.model_run_id) return `已生成模型 Run · ${batch.model_run_id}`;
  return "";
}

function renderBatchRequesterFilter() {
  const select = $("#batchRequesterFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  select.innerHTML = [
    '<option value="">全部请求人</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...state.predictionRequesters.map((item) => {
      const name = item.name || item.requested_by || "";
      const count = item.job_count ?? item.batch_count ?? item.count ?? 0;
      const trust =
        item.verified_count > 0 && item.unverified_count > 0
          ? " · 混合身份"
          : item.verified
            ? " · SSO"
            : "";
      return name
        ? `<option value="${escapeHtml(name)}">${escapeHtml(name)} · ${count} 个${trust}</option>`
        : "";
    }),
  ].join("");
  const names = state.predictionRequesters.map((item) => item.name || item.requested_by);
  select.value = previous === "__me__" || names.includes(previous) ? previous : "";
}

function batchInputSummary(batch) {
  const input = batch.input_config || {};
  const offsets = Array.isArray(input.frame_offsets_ms)
    ? input.frame_offsets_ms.join(", ")
    : "";
  return [
    batch.input_profile ? `Profile ${batch.input_profile}` : "",
    offsets ? `Camera ${input.frame_offsets_ms.length} 帧 · ${offsets} ms` : "",
    input.use_ra_event ? "RA Events" : "无 RA Events",
    input.use_ra_options ? "RA / SWAG Options" : "",
    input.use_bev_animation ? "Ares Animation · API 默认" : "Ares Animation 关闭",
  ].filter(Boolean);
}

function batchOutputLines(batch) {
  const summary = batch.summary && typeof batch.summary === "object"
    ? batch.summary
    : {};
  return [
    summary.ra_repo_commit ? `ra_auto_triage commit · ${summary.ra_repo_commit}` : "",
    summary.trail_view_id ? `Trail view · ${summary.trail_view_id}` : "",
    summary.model_run_duplicate ? "复用已有模型 Run" : "",
    summary.bag_cache_read_only ? "Bag cache · read-only" : "",
    summary.trail_write_enabled === false ? "Trail 写入 · 关闭" : "",
    batch.error_text ? `任务错误 · ${batch.error_text}` : "",
  ].filter(Boolean);
}

function renderPredictionBatchDetail(batch) {
  if (!batch) {
    return `<div class="batch-history-detail" data-batch-detail="loading"><span class="muted">正在读取运行输出…</span></div>`;
  }
  const counts = batchCounts(batch);
  const items = Array.isArray(batch.items) ? batch.items : [];
  const outputLines = batchOutputLines(batch);
  return `<div class="batch-history-detail" data-batch-detail="${escapeHtml(batch.id || "")}">
    <div class="batch-detail-heading">
      <div>
        <strong>运行输出 · ${escapeHtml(batch.name || batch.batch_name || batch.id || "")}</strong>
      </div>
      <span>${escapeHtml(batchStatusLabel(batch.status))} · ${counts.completed}/${counts.total} 完成 · 成功 ${counts.success} · 失败 ${counts.failed}</span>
    </div>
    <div class="batch-detail-meta">
      <span>${escapeHtml(batch.provider_id || "kylin")} · 模型 ${escapeHtml(batch.resolved_model_id || batch.model_name || "—")}${batch.model_validation_status === "experimental" ? " · 实验" : ""}</span>
      <span>Prompt ${escapeHtml(batch.prompt_version || "—")}${batch.prompt_mode === "custom" ? " · custom" : ""}</span>
      ${batchInputSummary(batch).map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
      ${batch.model_run_id ? `<span>Model Run ${escapeHtml(batch.model_run_id)}</span>` : ""}
      ${batch.finished_at ? `<span>结束 ${formatTime(batch.finished_at)}</span>` : ""}
    </div>
    ${outputLines.length ? `<div class="batch-output-lines">${outputLines.map((line) => `<code>${escapeHtml(line)}</code>`).join("")}</div>` : ""}
    ${
      items.length
        ? `<div class="batch-result-items">${items
            .map((item) => {
              const detail = item.result?.result || item.result || {};
              const issueUrl = safeUrl(item.voyager_issue_url || "");
              return `<div class="batch-result-item">
                <strong>${escapeHtml(item.issue_id)}</strong>
                <span class="job-status status-${escapeHtml(item.status)}">${escapeHtml(batchStatusLabel(item.status))}</span>
                ${detail.model_label ? labelBadge(detail.model_label, "—") : ""}
                ${issueUrl ? `<a href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer">打开 Voyager Issue</a>` : ""}
                ${detail.model_confidence != null ? `<small>confidence ${escapeHtml(detail.model_confidence)}</small>` : ""}
                ${detail.model_reason ? `<small class="batch-item-reason">${escapeHtml(detail.model_reason)}</small>` : ""}
                ${item.error_text ? `<small>${escapeHtml(item.error_text)}</small>` : ""}
              </div>`;
            })
            .join("")}</div>`
        : '<div class="muted">任务明细尚未生成。</div>'
    }
  </div>`;
}

function renderPredictionBatches(total = state.predictionBatches.length) {
  const list = $("#predictionBatchList");
  if (!list) return;
  $("#batchHistorySummary").textContent =
    `显示 ${state.predictionBatches.length} / ${total} 个 Batch` +
    " · 预测完成后需人工显式推送 AutoTriage";
  if (!state.predictionBatches.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有 Batch 预测任务。</div>';
    return;
  }
  const terminal = new Set(["succeeded", "completed", "partial", "partially_succeeded"]);
  list.innerHTML = state.predictionBatches
    .map((batch) => {
      const counts = batchCounts(batch);
      const publishEnabled = Boolean(
        state.config?.prediction_batch?.autotriage_push_enabled ??
          state.config?.batch_prediction?.autotriage_push_enabled
      );
      const publishStatus =
        batch.publish_status ||
        (batch.autotriage_batch_id || batch.platform_batch_id ? "published" : "not_published");
      const canPublish =
        terminal.has(batch.status) &&
        counts.success > 0 &&
        Boolean(batch.model_run_id) &&
        Boolean(batch.prompt_template_sha256) &&
        Boolean(batch.input_profile) &&
        ["not_requested", "not_published", "pending", "failed"].includes(publishStatus);
      const batchUrl = safeUrl(
        batch.autotriage_record_url ||
          batch.record_url ||
          batch.autotriage_url ||
          batch.records_url ||
          ""
      );
      const summaryText = batchSummaryText(batch);
      const expanded = state.expandedPredictionBatchId === batch.id;
      const detail = state.predictionBatchDetails[batch.id];
      return `<article class="job-history-row batch-history-row">
        <div class="job-history-main">
          <div class="run-row-title">
            <strong>${escapeHtml(batch.name || batch.batch_name || batch.id)}</strong>
            <span class="job-status status-${escapeHtml(batch.status)}">${escapeHtml(batchStatusLabel(batch.status))}</span>
            <span class="publish-status publish-${escapeHtml(publishStatus)}">${escapeHtml(batchPublishLabel(publishStatus))}</span>
          </div>
          <div class="run-row-meta">
            <span>Provider ${escapeHtml(batch.provider_id || "kylin")}</span>
            <span>${escapeHtml(
              batch.requested_model_id && batch.requested_model_id !== batch.model_name
                ? `${batch.requested_model_id} → ${batch.model_name || batch.resolved_model_id}`
                : batch.model_name || batch.resolved_model_id || "服务器模型网关"
            )}</span>
            ${batch.model_validation_status === "experimental" ? "<span>实验模型</span>" : ""}
            ${batch.prompt_version ? `<span>Prompt ${escapeHtml(batch.prompt_version)}${batch.prompt_mode === "custom" ? ` · custom${batch.prompt_template_sha256 ? ` · ${escapeHtml(batch.prompt_template_sha256.slice(0, 10))}…` : ""}` : ""}</span>` : ""}
            ${batch.input_profile ? `<span>输入 ${escapeHtml(batch.input_profile)}</span>` : ""}
            <span>${counts.completed} / ${counts.total} 完成</span>
            <span class="batch-success-count">成功 ${counts.success}</span>
            <span class="run-failure-count">失败 ${counts.failed}</span>
            <span>${batch.requested_by ? `请求人 ${escapeHtml(batch.requested_by)}${batch.requested_by_verified ? " · SSO" : ""}` : "请求人未记录"}</span>
            <span>${formatTime(batch.created_at)}</span>
          </div>
          ${summaryText ? `<div class="job-result-preview">${escapeHtml(summaryText)}</div>` : ""}
        </div>
        <div class="run-row-actions">
          <button class="button button-quiet" type="button" data-show-batch="${escapeHtml(batch.id)}">${expanded ? "收起日志" : "查看日志"}</button>
          ${canPublish && publishEnabled ? `<button class="button button-primary" type="button" data-publish-batch="${escapeHtml(batch.id)}">推送 AutoTriage</button>` : ""}
          ${canPublish && !publishEnabled ? '<button class="button button-quiet" type="button" disabled title="生产写入需可信 SSO 域名">推送需 SSO</button>' : ""}
          ${["running", "publishing"].includes(publishStatus) ? '<button class="button button-quiet" type="button" disabled>推送中…</button>' : ""}
          ${batchUrl ? `<a class="button button-quiet" href="${escapeHtml(batchUrl)}" target="_blank" rel="noreferrer">打开 AutoTriage</a>` : ""}
        </div>
        ${expanded ? renderPredictionBatchDetail(detail) : ""}
      </article>`;
    })
    .join("");
  list.querySelectorAll("[data-show-batch]").forEach((button) => {
    button.addEventListener("click", async () => {
      const batchId = button.dataset.showBatch;
      if (state.expandedPredictionBatchId === batchId) {
        state.expandedPredictionBatchId = "";
        renderPredictionBatches(state.predictionBatchTotal);
        return;
      }
      state.expandedPredictionBatchId = batchId;
      renderPredictionBatches(state.predictionBatchTotal);
      try {
        const data = await api(
          `/api/prediction-batches/${encodeURIComponent(batchId)}`
        );
        showPredictionBatch(data.batch || data.job || data);
      } catch (error) {
        if (state.expandedPredictionBatchId === batchId) {
          state.expandedPredictionBatchId = "";
          renderPredictionBatches(state.predictionBatchTotal);
        }
        showToast(error.message, true);
      }
    });
  });
  list.querySelectorAll("[data-publish-batch]").forEach((button) => {
    button.addEventListener("click", () => publishPredictionBatch(button.dataset.publishBatch, button));
  });
}

function showPredictionBatch(batch) {
  if (!batch?.id) return;
  state.predictionBatchDetails[batch.id] = batch;
  state.expandedPredictionBatchId = batch.id;
  renderPredictionBatches(state.predictionBatchTotal);
  requestAnimationFrame(() => {
    document
      .querySelector(`[data-batch-detail="${CSS.escape(batch.id)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

async function loadPredictionBatches() {
  if (!$("#predictionBatchList")) return;
  const requestSeq = ++state.batchListRequestSeq;
  const params = new URLSearchParams({ page_size: "200" });
  const requesterValue = $("#batchRequesterFilter")?.value || "";
  const requester = requesterValue === "__me__" ? state.session.username : requesterValue;
  const status = $("#batchStatusFilter")?.value || "";
  const modelId = $("#batchModelFilter")?.value || "";
  const promptFacet = parseBatchPromptFacetValue(
    $("#batchPromptFilter")?.value || ""
  );
  const inputProfile = $("#batchInputFilter")?.value || "";
  if (requester) params.set("requested_by", requester);
  if (status) params.set("status", status);
  if (modelId) params.set("model_id", modelId);
  if (promptFacet.version) params.set("prompt_version", promptFacet.version);
  if (promptFacet.mode) params.set("prompt_mode", promptFacet.mode);
  if (promptFacet.sha256) params.set("prompt_sha256", promptFacet.sha256);
  if (inputProfile) params.set("input_profile", inputProfile);
  const data = await api(`/api/prediction-batches?${params.toString()}`);
  if (requestSeq !== state.batchListRequestSeq) return;
  state.predictionBatches = data.items || [];
  state.predictionBatchTotal = data.total ?? state.predictionBatches.length;
  state.predictionRequesters = data.requesters || [];
  state.batchFacets = data.facets || {
    models: [],
    prompts: [],
    input_profiles: [],
  };
  const latestSafeExperiment = state.predictionBatches.find(
    (item) => item.summary?.safe_experiment
  )?.summary?.safe_experiment;
  const incomingModel = data.safe_experiment || data.default_model || data.model;
  state.batchDefaultModel = latestSafeExperiment
    ? { ...(state.batchDefaultModel || {}), ...latestSafeExperiment }
    : incomingModel || state.batchDefaultModel;
  renderBatchRuntimeSummary();
  renderBatchRequesterFilter();
  renderBatchCatalogFilters();
  renderPredictionBatches(state.predictionBatchTotal);
}

async function loadPredictionConfig() {
  const data = await api("/api/prediction-batches/config");
  state.batchDefaultModel = {
    ...(state.batchDefaultModel || {}),
    ...(data.model || {}),
  };
  state.config = {
    ...(state.config || {}),
    prediction_batch: {
      ...(state.config?.prediction_batch || {}),
      ...data,
    },
  };
  renderGatewayProviders();
  renderBatchRuntimeSummary();
  updatePredictionBatchCount();
  await Promise.all([loadGatewayModels(), loadBatchPrompts()]);
}

async function pollPredictionBatch(batchId) {
  clearTimeout(state.pollTimer);
  state.pollingBatchId = batchId;
  const tick = async () => {
    try {
      const data = await api(`/api/prediction-batches/${encodeURIComponent(batchId)}`);
      const batch = data.batch || data.job || data;
      showPredictionBatch(batch);
      state.predictionBatches = state.predictionBatches.map((item) =>
        item.id === batch.id ? { ...item, ...batch, items: undefined } : item
      );
      renderPredictionBatches(state.predictionBatchTotal);
      const batchRunning = ["queued", "running"].includes(batch.status);
      const publishRunning = ["running", "publishing"].includes(batch.publish_status);
      if (!batchRunning && !publishRunning) {
        clearTimeout(state.pollTimer);
        state.pollTimer = null;
        state.pollingBatchId = "";
        await loadPredictionBatches();
      } else if (state.pollingBatchId === batchId) {
        state.pollTimer = setTimeout(tick, 2500);
      }
    } catch (error) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
      state.pollingBatchId = "";
      showToast(error.message, true);
    }
  };
  await tick();
}

async function submitPredictionBatch(event) {
  event.preventDefault();
  const issueIds = predictionIssueIds();
  const invalid = issueIds.filter((issueId) => !/^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const maxIssues = Number(state.config?.prediction_batch?.max_issues || 0);
  const modelId = $("#predictionModelSelect")?.value || "";
  const selectedModel = state.gatewayModels.find((item) => item.id === modelId);
  const promptId = $("#predictionPromptSelect")?.value || "";
  const promptTemplate = $("#predictionPromptTemplate")?.value || "";
  const frameOffsetParts = String($("#predictionFrameOffsets")?.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean);
  const frameOffsets = frameOffsetParts.map((value) => Number(value));
  const useRaEvent = Boolean($("#predictionUseRaEvent")?.checked);
  const useRaOptions = Boolean($("#predictionUseRaOptions")?.checked);
  if (!issueIds.length) return showToast("请至少输入一个 Issue ID。", true);
  if (invalid.length) return showToast(`Issue ID 格式不合法：${invalid.slice(0, 3).join("、")}`, true);
  if (!modelId || state.gatewayModelStatus?.status !== "ready" || state.gatewayModelStatus?.stale) {
    return showToast("模型目录尚未就绪，请先刷新并选择可用模型。", true);
  }
  if (!promptId || !promptTemplate.trim()) {
    return showToast("请选择 Prompt，并保留非空正文。", true);
  }
  if (
    !frameOffsets.length ||
    frameOffsets.some((value) => !Number.isInteger(value))
  ) {
    return showToast("Camera 帧偏移必须是逗号分隔的整数。", true);
  }
  if (useRaOptions && !useRaEvent) {
    return showToast("启用 RA / SWAG Options 时必须同时启用 RA Events。", true);
  }
  const experimental = selectedModel?.validation_status !== "validated";
  if (
    experimental &&
    !window.confirm(
      `模型「${selectedModel?.display_name || modelId}」在线但尚未完成 RA 基线验证。仍要用它创建实验 Batch 吗？`
    )
  ) {
    return;
  }
  if (maxIssues && issueIds.length > maxIssues) {
    return showToast(`单批最多 ${maxIssues} 个 Issue；当前 ${issueIds.length} 个。`, true);
  }
  const button = $("#createPredictionBatchButton");
  button.disabled = true;
  button.textContent = "正在创建…";
  try {
    const data = await api("/api/prediction-batches", {
      method: "POST",
      body: JSON.stringify({
        issue_ids: issueIds,
        provider_id: state.selectedGatewayProviderId || "kylin",
        model_id: modelId,
        allow_experimental_model: experimental,
        prompt_id: promptId,
        prompt_template: promptTemplate,
        input_config: {
          profile_id: $("#predictionInputProfile")?.value || "camera_ra_event",
          frame_offsets_ms: frameOffsets,
          use_ra_event: useRaEvent,
          use_ra_options: useRaOptions,
          use_bev_animation: Boolean($("#predictionUseBev")?.checked),
        },
        name: $("#predictionBatchName").value.trim() || "",
        requested_by: state.session.username || "",
      }),
    });
    const batch = data.batch || data.job || data;
    showPredictionBatch(batch);
    showToast(`Batch 已创建，共 ${issueIds.length} 个 Issue。`);
    await loadPredictionBatches();
    if (batch.id && ["queued", "running"].includes(batch.status)) await pollPredictionBatch(batch.id);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "开始 Batch 预测";
    renderGatewayModels();
  }
}

async function publishPredictionBatch(batchId, button) {
  const batch = state.predictionBatches.find((item) => item.id === batchId);
  if (
    !window.confirm(
      `将把 Batch「${batch?.name || batchId}」的成功预测显式写入 AutoTriage，并保存关联记录链接。继续？`
    )
  ) {
    return;
  }
  button.disabled = true;
  button.textContent = "推送中…";
  try {
    const data = await api(
      `/api/prediction-batches/${encodeURIComponent(batchId)}/publish-autotriage`,
      {
        method: "POST",
        headers: { "X-RA-Triage-Request": "publish-v1" },
        body: JSON.stringify({ confirm: true }),
      }
    );
    const updated = data.batch || data.job || null;
    if (updated) showPredictionBatch(updated);
    showToast("AutoTriage 推送任务已接受，正在等待平台回查。");
    await loadPredictionBatches();
    const refreshed = state.predictionBatches.find((item) => item.id === batchId);
    if (refreshed) showPredictionBatch(refreshed);
    await pollPredictionBatch(batchId);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "推送 AutoTriage";
    }
  }
}

function currentImportKind() {
  return "model";
}

const IMPORT_EXAMPLES = Object.freeze({
  csv: {
    filename: "model_results.csv",
    description: "平铺表格，每行一个 Issue",
    content: [
      "issue_id,model_label,reason,confidence,ra_stuck_auto_result_info",
      'cn32171803,无需协助,"红灯持续亮起，前车停在停止线后，自车同步等待",0.96,"{""reason"":""红绿灯周期性等待"",""confidence"":0.96}"',
      'cn31954847,误触发,"前方大车遮挡，但红灯转绿后车流正常放行",0.88,"{""reason"":""排队等灯"",""confidence"":0.88}"',
      'cn32000543,正确触发,"前车双闪临停，右侧存在可通行空间",0.81,"{""reason"":""异常停车"",""confidence"":0.81}"',
    ].join("\n"),
  },
  json: {
    filename: "model_results.json",
    description: "支持原生 experiment + results 结果包",
    content: [
      "{",
      '  "experiment": {',
      '    "model_name": "Qwen3.5-9B-finetuned/base",',
      '    "prompt": "stuck_triage_auto_opt_api",',
      '    "input_profile": "Camera 9 帧 + RA Events + Ares Animation"',
      "  },",
      '  "results": [',
      "    {",
      '      "issue_id": "cn32171803",',
      '      "model_label": "无需协助",',
      '      "reason": "红绿灯周期性等待",',
      '      "confidence": 0.96',
      "    },",
      "    {",
      '      "issue_id": "cn31954847",',
      '      "ra_stuck_auto_result": "误触发",',
      '      "ra_stuck_auto_result_info": {',
      '        "reason": "排队等灯",',
      '        "confidence": 0.88',
      "      }",
      "    }",
      "  ]",
      "}",
    ].join("\n"),
  },
  xlsx: {
    filename: "model_results.xlsx",
    description: "Sheet1：首行是表头，后续每行一个 Issue",
    content: [
      "Sheet1",
      "",
      "issue_id       | model_label | reason                          | confidence | ra_stuck_auto_result_info",
      "cn32171803     | 无需协助     | 红绿灯周期性等待                  | 0.96       | {\"reason\":\"红绿灯周期性等待\"}",
      "cn31954847     | 误触发       | 排队等灯，红灯转绿后正常放行        | 0.88       | {\"reason\":\"排队等灯\"}",
      "cn32000543     | 正确触发     | 前车双闪临停，存在绕行空间          | 0.81       | {\"reason\":\"异常停车\"}",
    ].join("\n"),
  },
});

function renderImportExample(format = "csv") {
  const key = Object.prototype.hasOwnProperty.call(IMPORT_EXAMPLES, format) ? format : "csv";
  const example = IMPORT_EXAMPLES[key];
  const dialog = $("#importExamplesDialog");
  if (dialog) dialog.dataset.exampleFormat = key;
  document.querySelectorAll("[data-import-example-format]").forEach((tab) => {
    const active = tab.dataset.importExampleFormat === key;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("#importExampleFilename").textContent = example.filename;
  $("#importExampleDescription").textContent = example.description;
  $("#importExampleContent").textContent = example.content;
}

function openImportExamples() {
  renderImportExample("csv");
  openDialog("importExamplesDialog");
}

async function copyImportExample() {
  const format = $("#importExamplesDialog")?.dataset.exampleFormat || "csv";
  const example = IMPORT_EXAMPLES[format] || IMPORT_EXAMPLES.csv;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(example.content);
    } else {
      const input = document.createElement("textarea");
      input.value = example.content;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    showToast(`已复制 ${example.filename} 示例。`);
  } catch (error) {
    showToast(`复制失败，请直接选中示例内容：${error.message || "浏览器未授权剪贴板"}`, true);
  }
}

function updateImportFields() {
  $("#runNameField")?.classList.remove("hidden");
}

function activateRunSourceTab(kind = "upload") {
  const targetKind = ["upload", "autotriage", "trail"].includes(kind) ? kind : "upload";
  document.querySelectorAll("[data-run-source-tab]").forEach((tab) => {
    const active = tab.dataset.runSourceTab === targetKind;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-run-source-panel]").forEach((panel) => {
    const active = panel.dataset.runSourcePanel === targetKind;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
    panel.setAttribute("aria-hidden", String(!active));
  });
}

function setImportKind(kind) {
  updateImportFields();
  activateRunSourceTab("upload");
}

function openRunImport(kind = "model") {
  navigatePage("runs", { importKind: "model" });
  activateRunSourceTab("upload");
  window.setTimeout(() => $("#runsSourceCard")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
}

async function submitImport(event) {
  event.preventDefault();
  const file = $("#importFile").files[0];
  if (!file) return showToast("请选择文件。", true);
  const form = new FormData();
  form.append("file", file);
  form.append("run_name", $("#runNameInput").value.trim());
  form.append("created_by", state.session.username || "");
  const target = $("#importResult");
  target.classList.remove("hidden");
  target.textContent = "正在导入…";
  try {
    const result = await api("/api/import/model-results", { method: "POST", body: form });
    target.textContent = JSON.stringify(result, null, 2);
    showToast("模型 Run 已导入；可从列表切换对比。");
    await Promise.all([loadRuns(), loadOverview(), loadCases({ keepSelection: true }), loadClusters()]);
  } catch (error) {
    target.textContent = `导入失败：${error.message}`;
    showToast(error.message, true);
  }
}

function openAutoTriageImport() {
  activateRunSourceTab("autotriage");
}

async function submitAutoTriageImport(event) {
  event.preventDefault();
  const batchRef = $("#autotriageBatchInput")?.value.trim() || "";
  if (!batchRef) return showToast("请输入 AutoTriage Batch ID 或 records 链接。", true);
  const button = $("#importAutoTriageButton");
  const target = $("#autotriageImportResult");
  button.disabled = true;
  button.textContent = "正在拉取…";
  target.classList.remove("hidden");
  target.textContent = "正在通过服务器固定只读接口校验 Batch 与结果覆盖…";
  try {
    const result = await api("/api/import/autotriage", {
      method: "POST",
      body: JSON.stringify({
        batch_id: batchRef,
        run_name: $("#autotriageRunNameInput")?.value.trim() || "",
        created_by: state.session.username || "",
      }),
    });
    const coverage = result.coverage || {};
    const recordUrl = safeUrl(result.record_url);
    target.innerHTML = `
      <strong>${result.duplicate ? "已复用相同内容 Run" : "已创建 AutoTriage 快照 Run"}</strong>
      <span>Batch ${escapeHtml(result.batch_id)} · 接受 ${coverage.accepted_result_count ?? "—"} / 声明 ${coverage.declared_total ?? "—"} 条${coverage.partial ? " · 部分覆盖" : " · 覆盖完整"}</span>
      ${recordUrl ? `<a href="${escapeHtml(recordUrl)}" target="_blank" rel="noreferrer">打开 AutoTriage</a>` : ""}`;
    await loadRuns();
    renderRunManager();
    showToast(coverage.partial ? "Run 已拉取，但平台 Batch 为部分覆盖。" : "AutoTriage Run 已拉取。", Boolean(coverage.partial));
  } catch (error) {
    target.textContent = `拉取失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "拉取并创建 Run";
  }
}

async function syncTrail(mode = "preview") {
  const createRun = mode === "create";
  if (
    createRun &&
    !window.confirm(
      "将创建或复用一个本地 Run。不会写入 Trail，也不会修改 GT、人工复核或默认 Run。继续？"
    )
  ) {
    return;
  }
  const button = createRun ? $("#syncTrailButton") : $("#checkTrailButton");
  button.disabled = true;
  button.textContent = createRun ? "创建中…" : "检查中…";
  try {
    const result = await api("/api/trail-model-sync", {
      method: "POST",
      body: JSON.stringify({
        mode,
        requested_by: state.session.username || "",
      }),
    });
    state.trailInspection = result;
    state.config = {
      ...(state.config || {}),
      trail_sync: result,
      default_model_run_id: state.config?.default_model_run_id || "",
    };
    renderConfig();
    if (createRun && result.run_id) {
      await loadRuns();
    }
    showToast(
      result.message || (createRun ? "Trail 只读快照处理完成。" : "Trail 字段检查完成。"),
      ["failed", "unavailable"].includes(result.status)
    );
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = createRun ? "创建 Run" : "检查字段";
    renderTrailSyncState();
  }
}

async function refreshAll({ resetSelection = false } = {}) {
  await loadConfig();
  await loadRuns();
  await Promise.all([
    loadStatus(),
    loadOverview(),
    loadCases({ keepSelection: !resetSelection }),
    loadClusters(),
    loadReviewers(),
  ]);
}

async function reloadReviewGallery({
  includeOverview = true,
  historyMode = "push",
} = {}) {
  const reloadSeq = ++state.reviewReloadSeq;
  state.casePage = 1;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  const requests = [
    loadCases({ keepSelection: false, page: 1 }),
    loadClusters(),
  ];
  if (includeOverview) requests.push(loadOverview());
  await Promise.all(requests);
  if (reloadSeq !== state.reviewReloadSeq) return;
  showPage("review", { historyMode, issue: "" });
}

function bindEvents() {
  document.querySelectorAll("[data-page-target]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (
        element.tagName === "A" &&
        (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      ) {
        return;
      }
      event.preventDefault();
      navigatePage(element.dataset.pageTarget);
    });
  });
  $("#filterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await reloadReviewGallery();
  });
  $("#reviewAnalysisFilterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#analysisRunFilter").addEventListener("change", () => {
    const runId = $("#analysisRunFilter").value;
    const previouslyHadRun = Boolean(state.selectedRunId);
    const nextStatus = !runId
      ? "all"
      : previouslyHadRun
        ? checkedAnalysisComparisonStatus()
        : "mismatch";
    setAnalysisComparisonStatus(nextStatus, { hasRun: Boolean(runId) });
  });
  $("#resetReviewAnalysisButton").addEventListener("click", async () => {
    $("#analysisRunFilter").value = "";
    setAnalysisComparisonStatus("all", { hasRun: false });
    $("#analysisReviewerFilter").value = "";
    $("#analysisStatusFilter").value = "";
    $("#analysisGtFilter").value = "";
    $("#analysisAnnotationFilter").value = "";
    $("#analysisEvidenceFilter").value = "";
    $("#analysisTagFilter").value = "";
    state.reviewAnalysis.theme = "";
    $("#analysisSearchInput").value = "";
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#exportReviewAnalysisCsvButton").addEventListener("click", () => downloadReviewAnalysis("csv"));
  $("#exportReviewAnalysisXlsxButton").addEventListener("click", () => downloadReviewAnalysis("xlsx"));
  $("#analysisPagePrevious").addEventListener("click", () => {
    changeAnalysisPage(-1).catch((error) => showToast(error.message, true));
  });
  $("#analysisPageNext").addEventListener("click", () => {
    changeAnalysisPage(1).catch((error) => showToast(error.message, true));
  });
  $("#modelRunFilter").addEventListener("change", async () => {
    const previousRunId = state.selectedRunId;
    state.selectedRunId = $("#modelRunFilter").value;
    if (!state.selectedRunId) state.reviewComparisonStatus = "all";
    if (state.selectedRunId && !previousRunId) state.reviewComparisonStatus = "mismatch";
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    await reloadReviewGallery();
  });
  $("#comparisonFilter").addEventListener("change", async () => {
    state.reviewComparisonStatus = selectedReviewComparisonStatus();
    state.failureOnly = state.reviewComparisonStatus === "mismatch";
    renderAnalysisRunFilter();
    await reloadReviewGallery();
  });
  const clearClusterButton = $("#clearClusterButton");
  if (clearClusterButton) {
    clearClusterButton.addEventListener("click", async () => {
      state.clusterKey = "";
      await reloadReviewGallery({ includeOverview: false });
    });
  }
  $("#casePagePrevious").addEventListener("click", () => {
    changeCasePage(-1).catch((error) => showToast(error.message, true));
  });
  $("#casePageNext").addEventListener("click", () => {
    changeCasePage(1).catch((error) => showToast(error.message, true));
  });
  $("#casePageSize").addEventListener("change", (event) => {
    changeCasePageSize(event.target.value).catch((error) => showToast(error.message, true));
  });
  $("#refreshButton").addEventListener("click", async () => {
    try {
      await refreshAll();
      if (state.activePage === "analysis") {
        await loadReviewReasonAnalysis();
      } else if (state.selectedId) {
        await selectCase(state.selectedId, { updateRoute: false });
      }
      showToast("页面数据已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#refreshSystemStatusButton").addEventListener("click", async () => {
    const button = $("#refreshSystemStatusButton");
    button.disabled = true;
    try {
      await loadStatus();
      showToast(uiText("系统状态已刷新。", "System status refreshed."));
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  $("#checkTrailButton").addEventListener("click", () => syncTrail("preview"));
  $("#syncTrailButton").addEventListener("click", () => syncTrail("create"));
  $("#runManagerImportButton").addEventListener("click", () => {
    $("#importResult").classList.add("hidden");
    $("#importResult").textContent = "";
    activateRunSourceTab("upload");
  });
  $("#openAutoTriageImportButton").addEventListener("click", openAutoTriageImport);
  $("#openTrailImportButton").addEventListener("click", () => {
    activateRunSourceTab("trail");
  });
  $("#reviewUploadModelButton").addEventListener("click", () => openRunImport("model"));
  $("#predictFilteredButton").addEventListener("click", () => {
    const limit = predictionBatchLimit();
    if (state.caseTotal > limit) {
      showToast(
        `当前筛选有 ${state.caseTotal} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`,
        true
      );
      return;
    }
    if (state.cases.length !== state.caseTotal) {
      showToast(
        `当前仅加载 ${state.cases.length} / ${state.caseTotal} 个筛选结果，不能创建不完整 Batch。`,
        true
      );
      return;
    }
    openBatchDraft(
      state.cases.map((item) => item.issue_id),
      "filtered"
    );
  });
  $("#refreshRunsButton").addEventListener("click", async () => {
    try {
      await loadRuns();
      await loadOverview();
      showToast("模型 run 列表已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#runPersonFilter").addEventListener("change", renderRunManager);
  $("#runKindFilter").addEventListener("change", renderRunManager);
  $("#runSearchInput").addEventListener("input", renderRunManager);
  $("#batchRequesterFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  $("#batchStatusFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  ["#batchModelFilter", "#batchPromptFilter", "#batchInputFilter"].forEach((selector) => {
    $(selector).addEventListener("change", () => {
      loadPredictionBatches().catch((error) => showToast(error.message, true));
    });
  });
  $("#refreshPredictionBatchesButton").addEventListener("click", () => {
    loadPredictionBatches()
      .then(() => showToast("Batch 任务历史已刷新。"))
      .catch((error) => showToast(error.message, true));
  });
  $("#refreshGatewayModelsButton").addEventListener("click", () => {
    const button = $("#refreshGatewayModelsButton");
    button.disabled = true;
    loadGatewayModels({ refresh: true })
      .then(() => showToast("服务器模型目录已刷新。"))
      .catch((error) => showToast(error.message, true))
      .finally(() => {
        button.disabled = false;
      });
  });
  $("#predictionModelSelect").addEventListener("change", () => {
    state.selectedGatewayModelId = $("#predictionModelSelect").value;
    renderGatewayModels();
  });
  $("#predictionPromptSelect").addEventListener("change", loadSelectedPromptTemplate);
  $("#predictionPromptTemplate").addEventListener("input", updatePromptEditorSummary);
  $("#predictionInputProfile").addEventListener("change", applyBatchInputPreset);
  $("#predictionCameraPreset").addEventListener("change", applyCameraFramePreset);
  $("#predictionFrameOffsets").addEventListener("input", () => {
    syncCameraFramePreset();
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaEvent").addEventListener("change", () => {
    if (!$("#predictionUseRaEvent").checked) $("#predictionUseRaOptions").checked = false;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaOptions").addEventListener("change", () => {
    if ($("#predictionUseRaOptions").checked) $("#predictionUseRaEvent").checked = true;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseBev").addEventListener("change", renderBatchRuntimeSummary);
  $("#languageToggleButton").addEventListener("click", () => {
    applyUiLanguage(state.uiLanguage === "en" ? "zh" : "en");
  });
  $("#themeToggleButton").addEventListener("click", () => {
    applyColorTheme(state.colorTheme === "light" ? "dark" : "light");
  });
  $("#sidebarToggle").addEventListener("click", toggleSidebar);
  $("#sidebarBrandToggle").addEventListener("click", toggleSidebar);
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  $("#mediaDialog").addEventListener("close", cleanupMediaDialog);
  $("#raEventSearchInput").addEventListener("input", (event) => {
    renderRaEventRows(state.raEventDialog.events, event.target.value);
  });
  $("#raEventSearchButton").addEventListener("click", () => $("#raEventSearchInput")?.focus());
  $("#raEventDialog").addEventListener("close", () => {
    state.raEventDialog = { issueId: "", events: [], trailUrl: "" };
  });
  $("#importFile").addEventListener("change", () => {
    const filename = $("#importFileName");
    if (filename) filename.textContent = $("#importFile").files[0]?.name || "未选择文件";
  });
  $("#openImportExamplesButton").addEventListener("click", openImportExamples);
  document.querySelectorAll("[data-import-example-format]").forEach((tab) => {
    tab.addEventListener("click", () => renderImportExample(tab.dataset.importExampleFormat));
  });
  $("#copyImportExampleButton").addEventListener("click", () => copyImportExample().catch((error) => showToast(error.message, true)));
  $("#importForm").addEventListener("submit", submitImport);
  $("#autotriageImportForm").addEventListener("submit", submitAutoTriageImport);
  $("#predictionBatchIssues").addEventListener("input", () => {
    state.batchDraftSource = "";
    updatePredictionBatchCount();
    renderPredictionSourceSummary();
  });
  $("#predictionBatchForm").addEventListener("submit", submitPredictionBatch);
  $("#sourcePreviewPrevious").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page <= 1) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page - 1).catch((error) => showToast(error.message, true));
  });
  $("#sourcePreviewNext").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page >= state.sourcePreview.pageCount) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page + 1).catch((error) => showToast(error.message, true));
  });
  $("#mediaPrevButton").addEventListener("click", () => moveMedia(-1));
  $("#mediaNextButton").addEventListener("click", () => moveMedia(1));
  $("#mediaZoomOutButton").addEventListener("click", () => setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP));
  $("#mediaZoomResetButton").addEventListener("click", () => setMediaZoom(1, { resetScroll: true }));
  $("#mediaZoomInButton").addEventListener("click", () => setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP));
  $("#mediaOriginalSizeButton").addEventListener("click", showMediaAtOriginalSize);
  $("#mediaFullscreenButton").addEventListener("click", () => toggleMediaFullscreen());
  $("#mediaPreviewImage").addEventListener("load", () => {
    setMediaZoom(state.media.zoom);
  });
  bindMediaPanViewport($("#mediaViewport"));
  document.addEventListener("fullscreenchange", () => {
    updateMediaViewControls();
    window.requestAnimationFrame(updateMediaPanState);
  });
  document.addEventListener("keydown", (event) => {
    if (!$("#mediaDialog").open) {
      const target = event.target instanceof Element ? event.target : null;
      const interactiveTarget = target?.closest("input, textarea, select, button, a, [contenteditable='true']");
      const detailMediaActive =
        state.activePage === "review" &&
        Boolean(state.selectedCase) &&
        Boolean($("#detailHeroMedia")) &&
        !document.querySelector("dialog[open]");
      if (!detailMediaActive || interactiveTarget || event.ctrlKey || event.metaKey || event.altKey) return;
      const activate = (control) => {
        if (!control || control.disabled) return false;
        event.preventDefault();
        control.click();
        return true;
      };
      const key = event.key.toLowerCase();
      if (["b", "c", "v"].includes(key)) {
        const kind = { b: "bev", c: "camera", v: "video" }[key];
        const select = $("#detailMediaKindSelect");
        const option = select?.querySelector(`option[value="${kind}"]`);
        if (select && option && !option.disabled && select.value !== kind) {
          event.preventDefault();
          select.value = kind;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } else if (key === " " && state.detailMedia.kind === "video") {
        event.preventDefault();
        if (!event.repeat) $("#detailHeroMedia")?.querySelector("[data-video-play]")?.click();
      } else if (key === "arrowleft" || key === "arrowright") {
        const direction = key === "arrowleft" ? -1 : 1;
        const control = state.detailMedia.kind === "video"
          ? $("#detailHeroMedia")?.querySelector(`[data-video-jump="${direction}"]`)
          : $(direction < 0 ? "#detailMediaPreviousButton" : "#detailMediaNextButton");
        activate(control);
      } else if (key === "f") {
        if (!event.repeat) activate($("#detailMediaExpandButton"));
      }
      return;
    }
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) { event.preventDefault(); moveMedia(-1); }
    if (["ArrowRight", "ArrowDown"].includes(event.key)) { event.preventDefault(); moveMedia(1); }
    if (event.key.toLowerCase() === "b") switchMediaKind("bev");
    if (event.key.toLowerCase() === "c") switchMediaKind("camera");
    if (event.key.toLowerCase() === "v") switchMediaKind("video");
    if (event.key === " " && state.media.kind === "video") {
      event.preventDefault();
      $("#mediaVideoStage")?.querySelector("[data-video-play]")?.click();
    }
    if (["+", "="].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP); }
    if (["-", "_"].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP); }
    if (event.key === "0") {
      event.preventDefault();
      setMediaZoom(1, { resetScroll: true });
    }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleMediaFullscreen(); }
  });
  window.addEventListener("popstate", async () => {
    const route = parsePageRoute();
    if (route.page === "analysis") {
      const previousRunId = state.selectedRunId;
      const previousFailureOnly = state.failureOnly;
      const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
      const nextRunId =
        route.runId && state.modelRuns.some((run) => run.id === route.runId)
          ? route.runId
          : "";
      const nextComparisonStatus = nextRunId
        ? normalizedAnalysisComparisonStatus(
            route.analysisFilters.comparisonStatus,
            state.config?.default_failure_only ? "mismatch" : "all"
          )
        : "all";
      state.selectedRunId = nextRunId;
      state.reviewAnalysis.comparisonStatus = nextComparisonStatus;
      state.failureOnly = Boolean(
        nextRunId && nextComparisonStatus === "mismatch"
      );
      if (
        previousRunId !== state.selectedRunId ||
        previousFailureOnly !== state.failureOnly ||
        previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
      ) {
        state.reviewQueueStale = true;
      }
      $("#modelRunFilter").value = nextRunId;
      setReviewComparisonStatus(state.reviewComparisonStatus, {
        hasRun: Boolean(nextRunId),
      });
      renderAnalysisRunFilter();
      applyAnalysisRouteControls(route);
      showPage("analysis", { restoreRoute: true });
      renderActiveRun();
      renderRunManager();
      try {
        await Promise.all([loadReviewReasonAnalysis(), loadOverview()]);
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }
    if (route.page !== "review") {
      showPage(route.page, {
        issues: route.issues,
        source: route.source,
        importKind: route.importKind,
        restoreRoute: true,
      });
      return;
    }
    const nextRunId =
      route.runId && state.modelRuns.some((run) => run.id === route.runId)
        ? route.runId
        : "";
    const nextComparisonStatus = nextRunId
      ? normalizedReviewComparisonStatus(
          route.comparisonStatus,
          route.failureOnly ? "mismatch" : "all"
        )
      : "all";
    state.selectedRunId = nextRunId;
    $("#modelRunFilter").value = nextRunId;
    state.reviewComparisonStatus = nextComparisonStatus;
    setReviewComparisonStatus(nextComparisonStatus, {
      hasRun: Boolean(nextRunId),
    });
    applyReviewRouteControls(route);
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    if (!route.issue) {
      if (state.selectedId) clearPendingReviewImages();
      clearDetail({ showGallery: true });
    }
    showPage("review", {
      issue: route.issue,
      restoreRoute: true,
    });
    try {
      await Promise.all([
        loadCases({ keepSelection: true, page: route.casePage }),
        loadClusters(),
        loadOverview(),
      ]);
      if (route.issue) {
        if (route.issue !== state.selectedId || !state.selectedCase) {
          await selectCase(route.issue, { updateRoute: false });
        } else {
          setReviewView(route.issue);
          renderCaseNavigation();
        }
      }
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

async function bootstrap() {
  const initialRoute = parsePageRoute();
  applyColorTheme(
    localStorage.getItem("ra-triage-color-theme") || document.documentElement.dataset.colorTheme,
    { persist: false }
  );
  applyUiLanguage(localStorage.getItem("ra-triage-ui-language") || "zh", { persist: false });
  const savedSidebarState = localStorage.getItem("ra-triage-sidebar-collapsed");
  state.sidebarCollapsed = savedSidebarState === "true";
  applySidebarState();
  if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
  bindEvents();
  updateImportFields();
  showPage(initialRoute.page, {
    historyMode: initialRoute.legacyRoute ? "replace" : "",
    issue: initialRoute.issue,
    issues: initialRoute.issues,
    source: initialRoute.source,
    importKind: initialRoute.importKind,
    restoreRoute: true,
    loadPageData: false,
  });
  try {
    await Promise.all([loadConfig(), loadSession()]);
    state.selectedRunId =
      initialRoute.runId === "none"
        ? ""
        : initialRoute.runId || state.config.default_model_run_id || "";
    if (initialRoute.page === "analysis") {
      state.reviewAnalysis.comparisonStatus = state.selectedRunId
        ? normalizedAnalysisComparisonStatus(
            initialRoute.analysisFilters.comparisonStatus,
            state.config.default_failure_only ? "mismatch" : "all"
          )
        : "all";
      state.failureOnly =
        state.reviewAnalysis.comparisonStatus === "mismatch";
    } else {
      state.reviewComparisonStatus = state.selectedRunId
        ? normalizedReviewComparisonStatus(
            initialRoute.comparisonStatus,
            initialRoute.failureOnly || state.config.default_failure_only
              ? "mismatch"
              : "all"
          )
        : "all";
      state.failureOnly = state.reviewComparisonStatus === "mismatch";
    }
    await loadRuns({
      preferDefault: !initialRoute.runId,
      preserveEmpty: initialRoute.runId === "none",
    });
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    await loadReviewers();
    if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
    if (initialRoute.page === "analysis") applyAnalysisRouteControls(initialRoute);
    const initialPageRequests = [loadOverview()];
    let initialDetailRequest = null;
    if (initialRoute.page === "review") {
      initialPageRequests.push(
        loadCases({
          keepSelection: Boolean(initialRoute.issue),
          page: initialRoute.casePage,
        }),
        loadClusters()
      );
      if (initialRoute.issue) {
        initialDetailRequest = selectCase(initialRoute.issue, { updateRoute: false });
      }
    } else if (initialRoute.page === "status") {
      initialPageRequests.push(loadStatus());
    } else if (initialRoute.page === "prediction") {
      initialPageRequests.push(loadPredictionConfig(), loadPredictionBatches());
    }
    if (initialDetailRequest) {
      void Promise.all(initialPageRequests).catch((error) => {
        showToast(`辅助数据加载失败：${error.message}`, true);
      });
      await initialDetailRequest;
    } else {
      await Promise.all(initialPageRequests);
    }
    showPage(initialRoute.page, {
      historyMode: "replace",
      issue: initialRoute.issue,
      issues: initialRoute.issues,
      source: initialRoute.source,
      importKind: initialRoute.importKind,
      restoreRoute: true,
      loadPageData: false,
    });
    if (initialRoute.page === "analysis") await loadReviewReasonAnalysis();
  } catch (error) {
    showToast(`启动失败：${error.message}`, true);
  }
  startChangePolling();
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
